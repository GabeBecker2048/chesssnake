![](https://github.com/GabeBecker2048/chesssnake/blob/main/logo/chesssnake_logo_250.png)


# Chesssnake

*chesssnake* is a feature-packed Python library for playing, visualizing, and storing chess games

Pronounced "chess - snake", in reference to Python being a type of snake. It is not pronounced cheesecake

## Features

- Play chess in Python with an easy-to-use and intuitive API
- Store and retrieve chess games in a PostgreSQL database, without having to write any sql
  - Highly optimized SQL included
- Generate PNG or JPEG images files of your game
- PIL image support for manipulating images of your chess games
- Includes a highly optimized python-only chess library

## Installation

### Basic Installation

To install the core features of Chesssnake, run:

```bash
pip install chesssnake
```

### With PostgreSQL Support

This library uses [psycopg2](https://pypi.org/project/psycopg2/) to communicate with postgres. There are two ways to install psycopg2: with a binary or from source

To install chesssnake with PostgresSQL support, using psycopg2-binary **(recommended for beginners, development, and for non-serious purposes)**
```commandline
pip install chesssnake[postgres-binary]
```

To install chesssnake with PostgresSQL support, using psycopg2 from source **(recommended for production and packaging)**
```commandline
pip install chesssnake[postgres]
```

See [psycopg2 build prerequisites](https://www.psycopg.org/docs/install.html#build-prerequisites) for prerequisites when installing from source

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

### With PostgreSQL support

If you've installed chesssnake with PostgreSQL support, you can store and retrieve games from a database.

Before using chesssnake, you must create environment variables that point to your database. There are many ways to do this, but for this example I will use the [python-dotenv](https://pypi.org/project/python-dotenv/) package to load variables from a `.env` file

Create a file named `.env`. Add your database information
```commandline
CHESSDB_NAME='name_of_your_postgresql_db'
CHESSDB_USER='user_for_your_postgresql_db'
CHESSDB_PASS='password_for_your_postgresql_user'
CHESSDB_HOST='host_for_your_postgresql_db'
CHESSDB_PORT='port_for_your_postgres_db'
```
`CHESSDB_HOST` and `CHESSDB_PORT` are optional, and will default to `localhost` and `5432` respectively

Now creating and storing games with PostgreSQL is easy:

```Python3
from chesssnake import Game
from dotenv import load_dotenv

# load our env vars
load_dotenv()

# Initialize a new game with PostgreSQL
## If a game already exists in our database, we load the game into memory
## If it doesn't, chesssnake creates a new game in the database and loads a new game into memory
## Uniqueness of games is determined by unique combinations of "white_id", "black_id", and "group_id" (all BIG INTs)
game = Game(
  white_id=123,
  black_id=456,
  group_id=789,
  white_name="Bob", 
  black_name="Phil", 
  sql=True
)

game.move('e4') # Bob's move
game.move('e5') # Phil's move

# update the database with any new moves
game.update_db()
```

If you use `auto_sql` instead of `sql`, your games will be automatically updated with every move and with less transactions.

For more information on using chesssnake with PostgreSQL, see the docs (coming soon)