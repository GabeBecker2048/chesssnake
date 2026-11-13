#!/usr/bin/env python3
"""Time the api-endpoint over real HTTP, the way a player and a bot use it.

Start a server with open registration on a throwaway database, then point this at it:

    CHESSSNAKE__DATABASE__URL=sqlite:///bench.db \\
        uv run chesssnake api-endpoint --init-db --port 8123 -o api.registration=open &
    uv run python scripts/bench_server.py http://127.0.0.1:8123

It registers two players, plays seeded random games through the REST routes and
reports the median time of each request: posting a move, listing legal moves,
reading the game, and fetching the board image (first view of a position, and a
repeat view of the same one). Uses only the standard library, and only routes
every version since 0.12 has, so it measures an older server too. Results are
recorded in docs/benchmarks.md.
"""

import http.client
import json
import random
import secrets
import statistics
import sys
import time
from urllib.parse import urlparse


def main(url, games=3, plies=60):
    parsed = urlparse(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80)

    def call(method, path, body=None, token=None, raw=False):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        start = time.perf_counter()
        conn.request(method, "/v1" + path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = conn.getresponse()
        data = response.read()
        elapsed = (time.perf_counter() - start) * 1000
        return response.status, (data if raw else json.loads(data or b"null")), elapsed

    suffix = secrets.token_hex(3)
    tokens = {}
    for name in ("white", "black"):
        user = f"bench{name}{suffix}"
        status, body, _ = call("POST", "/auth/register", {"username": user, "password": "benchmark password"})
        if status != 201:
            sys.exit(f"registration failed ({status}): start the server with -o api.registration=open")
        tokens[name] = body["token"]
    black_id = call("GET", "/auth/me", None, tokens["black"])[1]["id"]

    rng = random.Random(3)
    timings = {
        "POST move": [],
        "GET legal-moves": [],
        "GET game": [],
        "GET image, first view": [],
        "GET image, repeat": [],
    }
    for _ in range(games):
        challenge = call("POST", "/challenges", {"opponent_id": black_id, "color": "white"}, tokens["white"])[1]
        state = call("POST", f"/challenges/{challenge['id']}/accept", None, tokens["black"])[1]
        game_id, version = state["id"], state["version"]
        for ply in range(plies):
            who = "white" if ply % 2 == 0 else "black"
            _, legal, ms = call("GET", f"/games/{game_id}/legal-moves", None, tokens[who])
            timings["GET legal-moves"].append(ms)
            if not legal["moves"]:
                break
            move = rng.choice(legal["moves"])["san"]
            status, result, ms = call(
                "POST", f"/games/{game_id}/moves", {"move": move, "expected_version": version}, tokens[who]
            )
            timings["POST move"].append(ms)
            if status != 200:
                break
            version = result["state"]["version"]
            timings["GET game"].append(call("GET", f"/games/{game_id}", None, tokens[who])[2])
            if ply % 5 == 0:
                timings["GET image, first view"].append(
                    call("GET", f"/games/{game_id}/image", None, tokens[who], raw=True)[2]
                )
                timings["GET image, repeat"].append(
                    call("GET", f"/games/{game_id}/image", None, tokens[who], raw=True)[2]
                )
            if result["state"]["status"] != 0:
                break
        call("POST", f"/games/{game_id}/resign", {"expected_version": version}, tokens["white"])

    info = call("GET", "/info")[1]
    print(f"server {info.get('version', '?')} at {url}")
    for name, values in timings.items():
        print(f"  {name:22s} n={len(values):3d}  median {statistics.median(values):6.2f} ms")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
