# Guide

Everything beyond the [README](../README.md): the Python API, running games
through an api-endpoint, playing in a terminal, and deploying with Docker.

- [The Python API](#the-python-api)
- [Inspecting game state](#inspecting-game-state)
- [More chess features](#more-chess-features)
- [Persisting games through the api-endpoint](#persisting-games-through-the-api-endpoint)
- [Playing from the terminal](#playing-from-the-terminal)
- [Deploying with Docker](#deploying-with-docker)

See also [docs/rest-api.md](rest-api.md) for every endpoint, and
[docs/configuration.md](configuration.md) for every setting.

This library's API is focused around a `Game` object. Every `Game` object represents a game between two players.

Build games with the factory methods: `Game.local(...)` for an in-memory game, or `Game.remote(...)` for one persisted through an api-endpoint (see below).

## The Python API

A simple example:
```Python3
from chesssnake import Game

# Initialize a new local game
game = Game.local(white_name="Bob", black_name="Alice")

# Make moves. move() returns the Move that was played
game.move('e4')  # Bob's move
game.move('e5')  # Alice's move

# Print the board
print(game)

# Rendering is separate from moving:
game.move('Nc3')
game.render().show()           # a PIL image (both perspectives + names)
game.render(perspective="white").show()  # or a single board from one side's POV
# (a nameless game's wide image omits the bottom name strip)
game.save('/path/to/img.png')  # or write it straight to disk
```

## Inspecting game state

Use the intention-revealing accessors instead of raw internals:

```Python3
game.to_move          # Color.WHITE or Color.BLACK, whose turn it is
game.is_over          # True once the game has ended
game.result           # a GameStatus: IN_PLAY, WHITE_WON, BLACK_WON, or DRAW
game.winner           # the winning Color, else None
game.termination      # why it ended: a Termination (checkmate, resignation, ...) or None
game.draw_offered_by  # the Color with an open draw offer, else None
```

`Color`, `GameStatus`, `PieceType`, and `Termination` are importable from `chesssnake`.

## More chess features

Every game (local or remote) supports the full rules and standard formats:

```Python3
game.legal_moves()    # list of legal moves ({from, to, san, promotion})
game.resign(player_id)  # resign; the opponent wins
game.move("Qh4")      # draw-by-rule (threefold, fifty-move, insufficient material,
                      #   stalemate) is detected automatically and ends the game
game.fen              # the position as standard FEN (interoperable with any chess tool)
print(game.pgn())     # export the game as PGN
```

All six FEN fields are also exposed directly on the game (local or remote):

```Python3
game.to_move          # active color (FEN field 2)
game.castling_rights  # e.g. "KQkq", or None if none (FEN field 3)
game.en_passant       # e.g. "e3" or None          (FEN field 4)
game.halfmove_clock   # plies since last pawn move/capture (FEN field 5)
game.fullmove_number  # the move number            (FEN field 6)
```

The board is stored and exchanged as standard **FEN**, so any chess library or tool
can read a chesssnake position.

## Persisting games through the api-endpoint

To store and retrieve games, run the api-endpoint server and point your `Game` clients at it.

**1. Run the server.** The server needs a database connection string. Set it in a
`chesssnake.toml` file:

```toml
[database]
url = "sqlite:///chesssnake.db"
```

That is the whole database setup for SQLite: no server to install or run. To use
PostgreSQL instead, install `chesssnake[api,postgres]` and change the one value:

```toml
[database]
url = "postgresql://user:password@localhost:5432/chesssnake"
```

or as an environment variable, or as a flag, whichever suits your deployment:

```commandline
CHESSSNAKE__DATABASE__URL='sqlite:///chesssnake.db'
chesssnake api-endpoint --database-url 'sqlite:///chesssnake.db'
```

Those are the same setting reached three ways. Every setting works like this, with
**command-line flags beating environment variables, which beat the config file,
which beats the built-in default**. Environment variable names are derived
mechanically from the setting's name: `[api] port` is always
`CHESSSNAKE__API__PORT`. To see what is in effect and where each value came from:

```commandline
chesssnake config show
```

Then start the server (the `--init-db` flag creates the schema on first run):

```commandline
chesssnake api-endpoint --host 0.0.0.0 --port 8000 --init-db
```

Interactive API docs are served at `http://<host>:8000/docs`. The HTTP routes are versioned under `/v1`; the client handles that for you. To require authentication, turn it on explicitly and give the server a key. Enabling it without a key is a startup error rather than a server that quietly accepts everything:

```commandline
CHESSSNAKE__API__API_KEY='...' chesssnake api-endpoint --require-auth
```

Then pass the same `api_key=` to `Game.remote(...)`. See
[docs/configuration.md](configuration.md) for the full list of settings, and
`chesssnake config init` to write a fully commented starter config.

## Playing from the terminal

`chesssnake play` is the third way to use the backend: a board and a prompt, with
no code to write.

Against a running api-endpoint (the game is persisted, and the server runs the engine):

```bash
chesssnake play --api-url http://localhost:8000 --group 1 --white 10 --black 20 --me 10
```

Or offline, with no server and nothing but the core install:

```bash
chesssnake play --local
```

```
8  ♜  ♞  ♝  ♛  ♚  ♝  ♞  ♜
7  ♟  ♟  ♟  ♟  ♟  ♟  ♟  ♟
6  ·  ·  ·  ·  ·  ·  ·  ·
5  ·  ·  ·  ·  ·  ·  ·  ·
4  ·  ·  ·  ·  ·  ·  ·  ·
3  ·  ·  ·  ·  ·  ·  ·  ·
2  ♙  ♙  ♙  ♙  ♙  ♙  ♙  ♙
1  ♖  ♘  ♗  ♕  ♔  ♗  ♘  ♖
   a  b  c  d  e  f  g  h

Bob (white) vs Alice (black)  |  gen 1  |  white to move

> e4
```

Type a move in algebraic notation, or one of:

| Command | |
|---|---|
| `moves` | list every legal move |
| `board` / `flip` | redraw / view from the other side |
| `fen` / `pgn` | the position as FEN / the game as PGN |
| `draw`, `accept`, `decline` | offer a draw, answer an offer |
| `resign` | resign |
| `refresh` | check the server now (it also polls on its own) |
| `new` | rematch, once the game is over |
| `save PATH` | write a PNG of the board |
| `help`, `quit` | |

Notes:

- **`--api-url` can be omitted** if `CHESSSNAKE__CLIENT__API_URL` is set. With neither,
  `play` tells you so instead of hanging.
- **`--me ID` is worth passing.** Turn order is then enforced, so you cannot
  accidentally move for your opponent, and the board faces your side. Without it the
  session acts as whoever is to move, which is what one person at one keyboard wants.
- **Two players** each run `play` with the same `--group/--white/--black` and their own
  `--me`. While you sit at the prompt the session **polls every 10 seconds** and announces
  the opponent's move when it lands; `--refresh SECONDS` changes the interval and
  `--refresh 0` turns it off. (One poll is a single small GET, measured at ~25 ms against
  a LAN deployment, so the interval is about how live it feels, not about load.) Every command re-reads the server first too, so you are
  never shown a stale position. (It is polling, not push: see
  `docs/realtime-websockets.md` for the design that would make moves arrive instantly.)
- **A rematch started elsewhere is noticed.** Re-opening a finished game starts a new
  generation, so if your opponent does that while you are still looking at the old one,
  the session says so and refuses to act until you type `new`. That refusal is
  load-bearing: the server's mutating routes act on whichever generation is *current*,
  so a move sent from a superseded session would otherwise land in the new game.
- `--ascii` draws pieces as letters, and `--no-color` emits no escape codes at all, both
  useful over a flaky terminal or when piping to a file.
- **Auth**, if the endpoint runs with `api.require_auth` on: `--api-key KEY`, or set
  `CHESSSNAKE__CLIENT__API_KEY` to keep it out of your shell history. It is sent as the
  `X-API-Key` header. A missing or wrong key fails immediately with
  `Invalid or missing API key` rather than showing you an empty board.
- **`quit`, Ctrl+D or Ctrl+C** all leave; Ctrl+C exits with status 130 and prints nothing.
  A remote game is saved on the server either way, and a local one is not saved at all.

Or skip all of that and run the published container, which is the easiest way to
stand one up: see [Deploying with Docker](#deploying-with-docker) below.

**2. Connect game clients.** Any number of clients can share the one endpoint. Use `Game.remote(...)`, giving the endpoint URL via the `api_url` argument or the `CHESSSNAKE__CLIENT__API_URL` environment variable:

```Python3
from chesssnake import Game

# If a game already exists for these ids it is loaded; otherwise a new one is created.
# Games are unique per (white_id, black_id, group_id), all BIGINTs.
game = Game.remote(
  123,            # white_id
  456,            # black_id
  group_id=789,
  white_name="Bob",
  black_name="Alice",
  api_url="http://localhost:8000",
  # api_key="...",  # if the server requires one
)

# The server validates and applies each move, then persists it. move() returns a
# MoveResult (from/to, check, castle/promotion/en) and raises the matching chess
# error if the move is illegal.
game.move('e4')  # Bob's move
game.move('e5')  # Alice's move

game.refresh()   # pull the latest state (e.g. after the opponent moved elsewhere)
game.render().show()  # render the board locally from the mirrored state
```

Because the **server** does the chess computation, an illegal move is rejected by the server and surfaced as the usual exception (e.g. `chesssnake.engine.errors.MoveIntoCheckError`). A frontend in another language would instead read the JSON `{error_type, detail}` and the HTTP status.

Optionally pass `player_id=` to `Game.remote(...)` so the server validates that this
client only acts for its own side, and the client sends its last-seen `version` so a
stale/duplicate action is rejected rather than double-applied.

Once a game finishes, calling `POST /v1/games` (or `Game.remote(...)`) again starts a
**rematch**, a new game between the same players, while the finished game is kept in
the archive and stays readable via `?generation=`.

Any REST client can drive a game without Python or a chess engine, for example:

```
POST /v1/games/789/123/456/moves        {"move": "e4"}      -> new state (+ move detail)
POST /v1/games/789/123/456/resign       {"player_id": 123}
POST /v1/games/789/123/456/draw/offer   {"player_id": 123}
GET  /v1/games/789/123/456/legal-moves  -> the legal moves
GET  /v1/games/789/123/456/pgn          -> the game as PGN
GET  /v1/games/789/123/456/fen          -> the position as FEN
GET  /v1/games/789/123/456/image?perspective=white  -> a PNG from white's POV
GET  /v1/games/789/123/456/archive      -> past games between these players
GET  /v1/games/789/record?player1=123&player2=456  -> head-to-head win/draw/loss record
```

**The full REST API is documented in [docs/rest-api.md](rest-api.md).**

Matchmaking helpers (`challenge`, `challenge_exists`, `delete_challenge`) and the
head-to-head `record` helper are also importable from `chesssnake`.


## Deploying with Docker

Images are published to
[`ghcr.io/gabebecker2048/chesssnake`](https://github.com/GabeBecker2048/chesssnake/pkgs/container/chesssnake)
on every release, for `linux/amd64` and `linux/arm64`. Nothing is built locally.

One image serves both backends. Which one you get is decided at runtime by
`CHESSSNAKE__DATABASE__URL`, not at build time, so moving from SQLite to
PostgreSQL later is a change to one value plus a database service.

### SQLite: one container

The whole stack. No database server, and the database is a file on a volume you
can back up by copying it.

```yaml
services:
  chesssnake:
    image: ghcr.io/gabebecker2048/chesssnake:latest   # or :0.9 to stay on 0.9.x
    restart: unless-stopped
    user: "1000:1000"              # who owns ./data (`id -u`:`id -g`)
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    environment:
      # Four slashes: sqlite://<empty host>/<absolute path>.
      CHESSSNAKE__DATABASE__URL: sqlite:////data/chesssnake.db
      CHESSSNAKE__DATABASE__INIT_SCHEMA: "1"          # idempotent, safe to leave on
      # Auth is off unless you turn it on explicitly. Setting only the key does
      # nothing, and require_auth without a key is a startup error.
      # CHESSSNAKE__API__REQUIRE_AUTH: "1"
      # CHESSSNAKE__API__API_KEY: "<long random>"
    # The server only writes to /data.
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 512m
```

Then, in that folder:

```sh
mkdir data           # so it is yours, not root's
docker compose up -d
curl localhost:8000/health
```

`user:` and the `mkdir` go together. A bind mount does not inherit the image's
ownership of `/data` the way a named volume does, so without them the database
would be unwritable. Update with `docker compose pull && docker compose up -d`.

**Do not scale this past one replica**, and do not put `./data` on NFS. SQLite
serializes writers through a single file lock, and that locking is unreliable
over NFS.

### PostgreSQL: two containers

For more than one api-endpoint process, or if you already run Postgres.

```yaml
services:
  chesssnake:
    image: ghcr.io/gabebecker2048/chesssnake:latest
    restart: unless-stopped
    depends_on:
      postgres: { condition: service_healthy }   # not just "started"
    ports:
      - "8000:8000"
    environment:
      CHESSSNAKE__DATABASE__URL: postgresql://chesssnake:${POSTGRES_PASSWORD:?set it in .env}@postgres:5432/chesssnake
      CHESSSNAKE__DATABASE__INIT_SCHEMA: "1"
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]

  postgres:
    image: postgres:17
    restart: unless-stopped
    environment:
      POSTGRES_DB: chesssnake
      POSTGRES_USER: chesssnake
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set it in .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U chesssnake -d chesssnake"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pgdata:
```

Put `POSTGRES_PASSWORD=...` in a `.env` beside the compose file. The
`service_healthy` condition matters: without it the api-endpoint can start
against a server still initialising.

### Exposing it

The api-endpoint has **no login of its own** unless you set
`CHESSSNAKE__API__REQUIRE_AUTH=1` and a key, and every route is a write surface,
so anyone who can reach it can play, resign or start a rematch in any game. Keep
it on a trusted network, or put it behind a reverse proxy, or turn auth on.
Clients then send the key as `api_key=` or the `X-API-Key` header.

### Building it yourself

The repository has compose files that build from source instead of pulling, which
is what to use when working on chesssnake itself:

```sh
docker compose -f docker/compose.sqlite.yaml   up --build   # one container
docker compose -f docker/compose.postgres.yaml up --build   # api-endpoint + Postgres
./docker/smoke-test.sh                                      # build, then play a game against each
```
