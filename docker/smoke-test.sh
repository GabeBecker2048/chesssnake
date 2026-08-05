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

play_a_game() {
    python3 - "$BASE" <<'PY'
import json, sys, urllib.request

base = sys.argv[1]

def call(method, path, body=None):
    """Return parsed JSON for JSON responses, raw bytes otherwise.

    Decided by Content-Type, not by sniffing the first byte: a PGN export starts
    with tag pairs like [Event "?"], which looks exactly like a JSON array.
    """
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = resp.read()
        is_json = resp.headers.get_content_type() == "application/json"
    return json.loads(payload) if is_json else payload

assert call("GET", "/health")["status"] == "ok", "health did not report ok"

game = call("POST", "/v1/games", {"group_id": 1, "white_id": 2, "black_id": 3,
                                  "white_name": "Ada", "black_name": "Bob"})
assert game["version"] == 1, f"unexpected initial version {game['version']}"

# Scholar's mate: a real game, and it exercises checkmate detection.
for move in ("e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7"):
    result = call("POST", "/v1/games/1/2/3/moves", {"move": move})

assert result["san"] == "Qxf7#", f"expected mate, got {result['san']!r}"
assert result["state"]["status"] == 1, f"expected white to win, got {result['state']['status']}"
assert result["state"]["termination"] == "checkmate", result["state"]["termination"]

# The game must survive as stored state, not just in that one response.
reloaded = call("GET", "/v1/games/1/2/3")
assert reloaded["status"] == 1, "the finished game did not persist"

pgn = call("GET", "/v1/games/1/2/3/pgn").decode()
assert "1. e4 e5" in pgn and "Qxf7#" in pgn, pgn

png = call("GET", "/v1/games/1/2/3/image")
assert png[:4] == b"\x89PNG", "the board image is not a PNG"

record = call("GET", "/v1/games/1/record?player1=2&player2=3")
assert record["player1_wins"] == 1, record

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
