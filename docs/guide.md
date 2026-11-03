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

Interactive API docs are served at `http://<host>:8000/docs`. The HTTP routes are
versioned under `/v1`; the client handles that for you. See
[docs/configuration.md](configuration.md) for the full list of settings, and
`chesssnake config init` to write a fully commented starter config.

### Accounts and logging in

Every player is a user account, and everything but `/health` needs a login. Make
the first administrator on the server's own machine, straight in the database:

```commandline
chesssnake user create gabe --admin          # prompts for a password
```

The `user` command is the administrator's toolbox: `create` (with `--admin`,
`--password-stdin`, or `--no-password` for a bot), `show`, `set-role`, `rename`,
`set-password`, `disable`/`enable`, `link` (an external id), and `token` (an api
token for a bot, printed once). It uses the same `--database-url` /
`CHESSSNAKE__DATABASE__URL` as `init-db`.

Whether people can make their own accounts is a setting:

```toml
[api]
registration = "open"      # default "closed": only administrators create users
```

Everyone else logs in from wherever they play:

```commandline
chesssnake login --api-url http://localhost:8000
```

That stores a token (in `~/.config/chesssnake/credentials.json`, mode 0600, never
in the working directory) which `chesssnake play` and `chesssnake.connect()` then
use. A login lasts 30 days (`api.session_lifetime_days`); `chesssnake logout`
revokes it sooner.

Users and administrators can do different things: a user plays and challenges as
themselves; an administrator also creates and deletes games, manages accounts,
and can act for any player. The [REST reference](rest-api.md#who-may-do-what)
has the full table.

**A Discord bot, or any integration with ids of its own**, gets its own admin
account with no password and an api token:

```commandline
chesssnake user create discord-bot --admin --no-password
chesssnake user token discord-bot --name bot     # prints the token, once
```

It then maps each member onto a chesssnake user with one idempotent call
(`client.get_or_create_user_by_identity("discord", member_id, member_name)`,
or `POST /v1/users/discord/{member_id}`), and plays for them by passing
`player_id`.

### Upgrading the database

Until 1.0.0 a release may change the database schema without a migration. When the
changelog says the schema changed, recreate it:

```commandline
chesssnake init-db --drop
```

This deletes every user and game. `--init-db` on its own never alters existing
tables, and the server refuses to start on a database from an older chesssnake
rather than failing part way through a request.

## Playing from the terminal

`chesssnake play` is the third way to use the backend: a board and a prompt, with
no code to write.

Against a running api-endpoint, after `chesssnake login`:

```bash
chesssnake challenge bob                # bob: `chesssnake challenges`, then `chesssnake accept ID`
chesssnake games                        # your games in progress, with their ids
chesssnake play --game 7                # or: chesssnake play --vs bob
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

alice (white) vs bob (black)  |  game 7  |  white to move

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
| `new` | after a game: challenge your opponent to a rematch, or accept theirs |
| `save PATH` | write a PNG of the board |
| `help`, `quit` | |

Notes:

- **`--api-url` can be omitted** if `CHESSSNAKE__CLIENT__API_URL` is set.
- **You play as the user you logged in as.** The server enforces turn order, and the
  board faces your side.
- **Both players** run `play` on the same game. While you sit at the prompt the
  session **polls every 10 seconds** and announces the opponent's move when it lands;
  `--refresh SECONDS` changes the interval and `--refresh 0` turns it off. Every
  command re-reads the server first too, so you are never shown a stale position.
  (It is polling, not push; push arrives with websockets in 0.13.0.)
- **Rematches are challenges.** `new` after a game sends your opponent a challenge
  with the colours swapped, or accepts theirs if they sent one first. If a rematch
  starts while you are still looking at the old game, the session says so and `new`
  joins it.
- **An expired login ends the session** with a note to run `chesssnake login`, rather
  than failing on every line.
- `--white-name`, `--black-name` and `--me` are for `--local` games only.
- `--ascii` draws pieces as letters, and `--no-color` emits no escape codes at all, both
  useful over a flaky terminal or when piping to a file.
- **`quit`, Ctrl+D or Ctrl+C** all leave; Ctrl+C exits with status 130 and prints nothing.
  A remote game is saved on the server either way, and a local one is not saved at all.

Or skip all of that and run the published container, which is the easiest way to
stand one up: see [Deploying with Docker](#deploying-with-docker) below.

**2. Connect game clients.** Any number of clients can share the one endpoint.
`chesssnake.connect()` gives you a logged-in client; the endpoint comes from
`api_url` or `CHESSSNAKE__CLIENT__API_URL`, and the login from a username and
password, a `token`, `CHESSSNAKE__CLIENT__TOKEN`, or `chesssnake login`:

```Python3
from chesssnake import Game, connect

alice = connect("http://localhost:8000", username="alice", password="...")
challenge = alice.challenge("bob", color="white")    # players are usernames or ids

bob = connect("http://localhost:8000", username="bob", password="...")
state = bob.accept_challenge(challenge.id)           # this creates the game

game = Game.remote(state, client=alice)              # or Game.remote(game_id, client=...)
print(game.id)                                       # GET /v1/games/{id}

# The server validates and applies each move, then persists it. move() returns a
# MoveResult (from/to, check, castle/promotion/en) and raises the matching chess
# error if the move is illegal.
game.move("e4")

game.refresh()        # pull the latest state, e.g. after the opponent moved
game.render().show()  # render the board locally from the mirrored state
```

Because the **server** does the chess computation, an illegal move is rejected by
the server and surfaced as the usual exception (e.g.
`chesssnake.engine.errors.MoveIntoCheckError`). A frontend in another language reads
the JSON `{error_type, detail}` and the HTTP status instead.

The client sends its last-seen `version` with every action, so a stale or
duplicate action is refused rather than double-applied. A finished game keeps its
id and stays readable; a rematch is a new challenge and a new game.

Any REST client can drive a game without Python or a chess engine, for example:

```
POST /v1/auth/login              {"username": "alice", "password": "..."}  -> a token
POST /v1/challenges              {"opponent_id": 2, "color": "white"}      -> a challenge
POST /v1/challenges/{id}/accept  (as bob)                                  -> the new game
POST /v1/games/{id}/moves        {"move": "e4"}       -> new state (+ move detail)
POST /v1/games/{id}/resign
POST /v1/games/{id}/draw/offer
GET  /v1/games/{id}/legal-moves  -> the legal moves
GET  /v1/games/{id}/pgn          -> the game as PGN
GET  /v1/games/{id}/image?perspective=white  -> a PNG from white's point of view
GET  /v1/games/between?player1=1&player2=2   -> every game between two players
GET  /v1/games/record?player1=1&player2=2    -> head-to-head win/draw/loss record
```

Every request but the login carries `Authorization: Bearer <token>`. **The full
REST API is documented in [docs/rest-api.md](rest-api.md).**


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
      # Every /v1 route needs a login. Uncomment to let people register themselves.
      # CHESSSNAKE__API__REGISTRATION: "open"
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

Every route but `/health` needs a login, so make the first administrator before
anyone else needs it:

```sh
docker compose exec chesssnake chesssnake user create yourname --admin
```

Logins are passwords and bearer tokens, so serve it over **HTTPS** (a reverse proxy
such as Caddy in front of it) if it is reachable from anywhere you do not trust;
`chesssnake login` warns when it is about to send a password over plain HTTP to
another machine. There is no rate limit on logins: each attempt is deliberately
slow (Argon2), and at most four are checked at once, but a server open to the
internet should also be behind something that limits requests.

### Building it yourself

The repository has compose files that build from source instead of pulling, which
is what to use when working on chesssnake itself:

```sh
docker compose -f docker/compose.sqlite.yaml   up --build   # one container
docker compose -f docker/compose.postgres.yaml up --build   # api-endpoint + Postgres
./docker/smoke-test.sh                                      # build, then play a game against each
```
