![](https://github.com/GabeBecker2048/chesssnake/raw/main/logo/chesssnake_logo_250.png)


# Chesssnake

*chesssnake* is a feature-packed Python library for playing, visualizing, and storing chess games

Pronounced "chess - snake", in reference to Python being a type of snake. It is not pronounced cheesecake

## Features

- Play chess in Python with an easy-to-use and intuitive API
- Store and retrieve chess games through a REST **api-endpoint** backed by PostgreSQL — many game clients can share one database, without writing any SQL
- Generate PNG or JPEG images files of your game
- PIL image support for manipulating images of your chess games
- Includes a highly optimized python-only chess library

## Architecture

chesssnake is split into three tiers so that many lightweight game clients — in any language — can share a single database through one authoritative server:

1. **Game client** — sends a move (e.g. `"e4"`) over REST and receives the new state or a structured error. It never needs a chess engine of its own.
2. **api-endpoint** — a REST server (`chesssnake api-endpoint`) that **runs the chess engine**: it validates and applies every move, is the single source of truth for the rules, and stores the result.
3. **Database** — the api-endpoint owns the PostgreSQL connection and does all SQL.

Because the server owns the rules, any frontend (web, mobile, a chat bot, …) can use the chesssnake backend by speaking REST — no chess logic required on the client side. (A `Game.local(...)` game still runs the engine in-process, with no server needed.)

## Installation

### Basic Installation

To install the core features of Chesssnake (local, in-memory games and image rendering), run:

```bash
pip install chesssnake
```

### To play remote (persisted) games

Install the client extra (adds `requests`):
```commandline
pip install chesssnake[client]
```

### To run the api-endpoint server

Install the api extra (adds FastAPI, uvicorn, and a PostgreSQL driver):
```commandline
pip install chesssnake[api]
```

## Usage
This library's API is focused around a `Game` object. Every `Game` object represents a game between two players.

Build games with the factory methods: `Game.local(...)` for an in-memory game, or `Game.remote(...)` for one persisted through an api-endpoint (see below).

### Basic usage

A simple example:
```Python3
from chesssnake import Game

# Initialize a new local game
game = Game.local(white_name="Bob", black_name="Phil")

# Make moves — move() returns the Move that was played
game.move('e4')  # Bob's move
game.move('e5')  # Phil's move

# Print the board
print(game)

# Rendering is separate from moving:
game.move('Nc3')
game.render().show()           # a PIL image (both perspectives + names)
game.render(perspective="white").show()  # or a single board from one side's POV
# (a nameless game's wide image omits the bottom name strip)
game.save('/path/to/img.png')  # or write it straight to disk
```

### Inspecting game state

Use the intention-revealing accessors instead of raw internals:

```Python3
game.to_move          # Color.WHITE or Color.BLACK — whose turn it is
game.is_over          # True once the game has ended
game.result           # a GameStatus: IN_PLAY, WHITE_WON, BLACK_WON, or DRAW
game.winner           # the winning Color, else None
game.termination      # why it ended: a Termination (checkmate, resignation, ...) or None
game.draw_offered_by  # the Color with an open draw offer, else None
```

`Color`, `GameStatus`, `PieceType`, and `Termination` are importable from `chesssnake`.

### More chess features

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

### Persisting games through the api-endpoint

To store and retrieve games, run the api-endpoint server and point your `Game` clients at it.

**1. Run the server.** The server reads its database credentials from environment variables. There are many ways to set these; for this example I use the [python-dotenv](https://pypi.org/project/python-dotenv/) package with a `.env` file:

```commandline
CHESSDB_NAME='name_of_your_postgresql_db'
CHESSDB_USER='user_for_your_postgresql_db'
CHESSDB_PASS='password_for_your_postgresql_user'
CHESSDB_HOST='host_for_your_postgresql_db'   # optional, defaults to localhost
CHESSDB_PORT='port_for_your_postgres_db'     # optional, defaults to 5432
```
(You can also set a single `CHESSDB_CONN_STR` connection string instead.)

Then start the server (the `--init-db` flag creates the schema on first run):

```commandline
chesssnake api-endpoint --host 0.0.0.0 --port 8000 --init-db
```

Interactive API docs are served at `http://<host>:8000/docs`. The HTTP routes are versioned under `/v1`; the client handles that for you. To require authentication, set `CHESSSNAKE_API_KEY` on the server and pass the same `api_key=` to `Game.remote(...)`.

**2. Connect game clients.** Any number of clients can share the one endpoint. Use `Game.remote(...)`, giving the endpoint URL via the `api_url` argument or the `CHESSSNAKE_API_URL` environment variable:

```Python3
from chesssnake import Game

# If a game already exists for these ids it is loaded; otherwise a new one is created.
# Games are unique per (white_id, black_id, group_id) — all BIGINTs.
game = Game.remote(
  123,            # white_id
  456,            # black_id
  group_id=789,
  white_name="Bob",
  black_name="Phil",
  api_url="http://localhost:8000",
  # api_key="...",  # if the server requires one
)

# The server validates and applies each move, then persists it. move() returns a
# MoveResult (from/to, check, castle/promotion/en) and raises the matching chess
# error if the move is illegal.
game.move('e4')  # Bob's move
game.move('e5')  # Phil's move

game.refresh()   # pull the latest state (e.g. after the opponent moved elsewhere)
game.render().show()  # render the board locally from the mirrored state
```

Because the **server** does the chess computation, an illegal move is rejected by the server and surfaced as the usual exception (e.g. `chesssnake.engine.errors.MoveIntoCheckError`). A frontend in another language would instead read the JSON `{error_type, detail}` and the HTTP status.

Optionally pass `player_id=` to `Game.remote(...)` so the server validates that this
client only acts for its own side, and the client sends its last-seen `version` so a
stale/duplicate action is rejected rather than double-applied.

Once a game finishes, calling `POST /v1/games` (or `Game.remote(...)`) again starts a
**rematch** — a new game between the same players — while the finished game is kept in
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

**The full REST API is documented in [docs/rest-api.md](docs/rest-api.md).**

Matchmaking helpers (`challenge`, `challenge_exists`, `delete_challenge`) and the
head-to-head `record` helper are also importable from `chesssnake`.

## REST API reference

Every endpoint — request/response shapes, all error codes, and how a client should
interpret each response — is documented in **[docs/rest-api.md](docs/rest-api.md)**.
Any HTTP client, in any language, can drive a full game with it.