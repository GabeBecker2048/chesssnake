#!/usr/bin/env bash
#
# Build the image and exercise both compose stacks end to end.
#
#   ./docker/smoke-test.sh              # both backends
#   ./docker/smoke-test.sh sqlite       # just one
#
# For each stack this brings the containers up, waits for the healthcheck,
# plays a real game over HTTP, and tears everything down again — including
# volumes, so repeated runs start from an empty database.
#
# Exits non-zero on the first failure. Uses python3 rather than curl/jq so it
# depends on nothing the repository does not already require.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${CHESSSNAKE_SMOKE_PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"
if [ $# -gt 0 ]; then STACKS=("$@"); else STACKS=(sqlite postgres); fi

# Tear down on any exit, including a failed assertion under `set -e`, so a bad
# run never leaves containers or volumes behind.
CURRENT_FILE=""
cleanup() {
    [ -n "$CURRENT_FILE" ] || return 0
    docker compose -f "$CURRENT_FILE" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

log()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAIL: %s\033[0m\n' "$*" >&2; exit 1; }

compose_file() {
    case "$1" in
        sqlite)   echo "$REPO_ROOT/docker/compose.sqlite.yaml" ;;
        postgres) echo "$REPO_ROOT/docker/compose.postgres.yaml" ;;
        *) fail "unknown stack '$1' (expected: sqlite, postgres)" ;;
    esac
}

wait_for_health() {
    local file=$1 deadline=$((SECONDS + 180))
    while (( SECONDS < deadline )); do
        if python3 -c "
import sys, urllib.request
try:
    sys.exit(0 if urllib.request.urlopen('${BASE}/health', timeout=2).status == 200 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
            return 0
        fi
        # Surface a container that died rather than silently waiting out the clock.
        if [ -z "$(docker compose -f "$file" ps --status running --quiet api)" ]; then
            docker compose -f "$file" logs --no-color api | tail -40
            fail "the api container is not running"
        fi
        sleep 2
    done
    docker compose -f "$file" logs --no-color | tail -60
    fail "timed out waiting for ${BASE}/health"
}

bootstrap_accounts() {
    # Accounts are made in the container, against the database, the way an
    # operator makes the first admin. The passwords are throwaway: the stack is
    # torn down with --volumes before and after.
    local file=$1
    printf 'ada-password\n' | docker compose -f "$file" exec -T api chesssnake user create ada --password-stdin >/dev/null
    printf 'bob-password\n' | docker compose -f "$file" exec -T api chesssnake user create bob --password-stdin >/dev/null
    docker compose -f "$file" exec -T api chesssnake user create bot --admin --no-password >/dev/null
    ADMIN_TOKEN="$(docker compose -f "$file" exec -T api chesssnake user token bot --name smoke-test 2>/dev/null)"
    [ -n "$ADMIN_TOKEN" ] || fail "could not mint an admin token"
}

play_a_game() {
    python3 - "$BASE" "$ADMIN_TOKEN" <<'PY'
import json, sys, urllib.error, urllib.request

base, admin = sys.argv[1], sys.argv[2]

def call(method, path, body=None, token=None, expect=None):
    """Return (status, parsed JSON or raw bytes).

    JSON vs bytes is decided by Content-Type, not by sniffing the first byte: a
    PGN export starts with tag pairs like [Event "?"], which looks exactly like
    a JSON array.
    """
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status, payload, ctype = resp.status, resp.read(), resp.headers.get_content_type()
    except urllib.error.HTTPError as e:
        status, payload, ctype = e.code, e.read(), e.headers.get_content_type()
    result = json.loads(payload) if ctype == "application/json" and payload else payload
    if expect is not None:
        assert status == expect, f"{method} {path}: expected {expect}, got {status}: {result!r}"
    return result

assert call("GET", "/health", expect=200)["status"] == "ok", "health did not report ok"
call("GET", "/v1/games", expect=401)

ada = call("POST", "/v1/auth/login", {"username": "ada", "password": "ada-password"}, expect=200)["token"]
bob = call("POST", "/v1/auth/login", {"username": "Bob", "password": "bob-password"}, expect=200)["token"]
call("POST", "/v1/auth/login", {"username": "ada", "password": "wrong-password"}, expect=401)

# The normal way to a game: ada challenges as white, bob accepts.
bob_id = call("GET", "/v1/users?username=bob", token=ada, expect=200)["id"]
challenge = call("POST", "/v1/challenges", {"opponent_id": bob_id, "color": "white"}, token=ada, expect=201)
game = call("POST", f"/v1/challenges/{challenge['id']}/accept", token=bob, expect=201)
url = f"/v1/games/{game['id']}"
assert (game["white_name"], game["black_name"]) == ("ada", "bob"), game

# Scholar's mate, each side moving as itself; it exercises checkmate detection.
for token, move in ((ada, "e4"), (bob, "e5"), (ada, "Qh5"), (bob, "Nc6"), (ada, "Bc4"), (bob, "Nf6"), (ada, "Qxf7")):
    result = call("POST", f"{url}/moves", {"move": move}, token=token, expect=200)
call("POST", f"{url}/moves", {"move": "a6"}, token=ada, expect=400)  # over now

assert result["san"] == "Qxf7#", f"expected mate, got {result['san']!r}"
assert result["state"]["status"] == 1 and result["state"]["termination"] == "checkmate", result["state"]

# The game survives as stored state, archived under the id it was played as.
assert call("GET", url, token=bob, expect=200)["status"] == 1, "the finished game did not persist"
pgn = call("GET", f"{url}/pgn", token=bob, expect=200).decode()
assert "1. e4 e5" in pgn and "Qxf7#" in pgn and '[White "ada"]' in pgn, pgn
png = call("GET", f"{url}/image", token=bob, expect=200)
assert png[:4] == b"\x89PNG", "the board image is not a PNG"
record = call("GET", f"/v1/games/record?player1={game['white_id']}&player2={bob_id}", token=ada, expect=200)
assert record["player1_wins"] == 1, record

# An admin token, as a bot would hold, maps an external id onto a user.
linked = call("POST", "/v1/users/discord/123456789012345678", {"username": "carol"}, token=admin, expect=200)
assert call("GET", "/v1/users/discord/123456789012345678", token=admin, expect=200)["id"] == linked["id"]
call("GET", "/v1/users/discord/123456789012345678", token=ada, expect=403)

call("POST", "/v1/auth/logout", token=ada, expect=204)
call("GET", "/v1/auth/me", token=ada, expect=401)

print(f"  game played and persisted; pgn tail: {pgn.strip().splitlines()[-1]}")
print(f"  board image: {len(png)} bytes")
PY
}

run_stack() {
    local stack=$1 file
    file="$(compose_file "$stack")"
    CURRENT_FILE="$file"

    log "$stack: building and starting"
    docker compose -f "$file" down --volumes --remove-orphans >/dev/null 2>&1 || true
    docker compose -f "$file" up --build --detach

    log "$stack: waiting for the api-endpoint"
    wait_for_health "$file"

    log "$stack: creating accounts"
    bootstrap_accounts "$file"

    log "$stack: playing a game"
    play_a_game

    log "$stack: confirming the configured backend"
    docker compose -f "$file" exec -T api chesssnake config show \
        | grep -E '^\s+url' \
        | grep -q "$([ "$stack" = sqlite ] && echo sqlite || echo postgresql)" \
        || fail "$stack: the running container is not using the expected backend"

    printf '\033[32m%s: OK\033[0m\n' "$stack"
    cleanup
    CURRENT_FILE=""
}

for stack in "${STACKS[@]}"; do
    run_stack "$stack"
done

log "all stacks passed"
