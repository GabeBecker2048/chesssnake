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
This library's API is focused around a `Game` object. Every `Game` object represents a game between two players

### Basic usage

A simple example:
```Python3
from chesssnake import Game

# Initialize a new game
game = Game(white_name="Bob", black_name="Phil")

# Make moves
game.move('e4') # Bob's move
game.move('e5') # Phil's move

# Print the board
print(game)

# make the move, return a PIL image object, and show the board in png format
game.move('Nc3', img=True).show()

# save the board as a png
game.save('/path/to/your/image1.png')

# make the move, and save the board as a png
game.move('Bc5', save='/path/to/your/image2.png')
```

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

Interactive API docs are served at `http://<host>:8000/docs`.

**2. Connect game clients.** Any number of clients can share the one endpoint. Set `remote=True` and give the endpoint URL via the `api_url` argument or the `CHESSSNAKE_API_URL` environment variable:

```Python3
from chesssnake import Game

# If a game already exists for these ids it is loaded; otherwise a new one is created.
# Games are unique per (white_id, black_id, group_id) — all BIGINTs.
game = Game(
  white_id=123,
  black_id=456,
  group_id=789,
  white_name="Bob",
  black_name="Phil",
  remote=True,
  api_url="http://localhost:8000",
)

game.move('e4')  # Bob's move
game.move('e5')  # Phil's move

# push the new state to the api-endpoint
game.sync()
```

Pass `auto_sync=True` instead of calling `sync()` to have every move and draw action pushed to the endpoint automatically.

Without `remote=True`, a `Game` is a purely local, in-memory game (no server or database required).

For more information, see the docs (coming soon)