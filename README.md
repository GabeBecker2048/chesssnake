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

chesssnake is split into three tiers so that many lightweight game clients can share a single database:

1. **Game client** — the `Game` object runs the chess engine locally and syncs game state over REST.
2. **api-endpoint** — a REST server (`chesssnake api-endpoint`) that exposes a thin persistence API.
3. **Database** — the api-endpoint owns the PostgreSQL connection and does all SQL.

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
game.render().show()           # a PIL image of the board (last move highlighted)
game.save('/path/to/img.png')  # or write it straight to disk
```

### Inspecting game state

Use the intention-revealing accessors instead of raw internals:

```Python3
game.to_move          # Color.WHITE or Color.BLACK — whose turn it is
game.is_over          # True once the game has ended
game.result           # a GameStatus: IN_PLAY, CHECKMATE, or DRAW
game.winner           # the winning Color on checkmate, else None
game.draw_offered_by  # the Color with an open draw offer, else None
```

`Color`, `GameStatus`, and `PieceType` are importable from `chesssnake`.

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

game.move('e4')  # Bob's move
game.move('e5')  # Phil's move — each move is synced automatically (auto_sync defaults to True)
```

Remote games sync after every move and draw action by default. Pass `auto_sync=False` to batch changes and push them yourself with `game.sync()`. A remote game is also a context manager that syncs on exit, so a forgotten `sync()` can't silently drop moves:

```Python3
with Game.remote(123, 456, group_id=789, api_url="http://localhost:8000", auto_sync=False) as game:
    game.move('e4')
    game.move('e5')
# state is pushed here, on exit
```

Matchmaking helpers (`challenge`, `challenge_exists`, `delete_challenge`) are also importable from `chesssnake`.

For more information, see the docs (coming soon)