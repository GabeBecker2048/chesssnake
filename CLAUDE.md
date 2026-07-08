# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`chesssnake` is a PyPI library (`pip install chesssnake`) for playing, visualizing, and persisting chess games. It has a pure-Python chess engine, a PIL-based board renderer, and an optional PostgreSQL persistence layer. Current version is 0.6.6 (pre-1.0 — see `VersionHistory.md` for the roadmap).

## Commands

The project is managed with **uv**; all metadata lives in `pyproject.toml` (there is no `setup.py` or `requirements.txt`). The build backend is setuptools. Development is manual:

```bash
# Create/refresh the venv and install the project + an extra
uv sync --extra postgres-binary   # or: --extra postgres (psycopg2 from source)
uv sync                           # core only (no DB layer)

# Run anything inside the managed environment
uv run python example.py          # core (no-DB) smoke example

# Tests (the `dev` dependency group provides pytest + pgserver)
uv run pytest                     # everything under tests/
uv run pytest tests/unit          # fast, pure-Python chesslib tests (no DB)
uv run pytest tests/integration   # postgres layer; spins up a throwaway Postgres via
                                  # pgserver (no Docker/system Postgres needed)
uv run pytest tests/unit/test_rules.py::test_en_passant_capture  # a single test

# Add/remove dependencies (edits pyproject.toml + uv.lock)
uv add <pkg>
uv add --group dev <pkg>          # add a dev/test dependency
uv add --optional postgres <pkg>  # add to an extra

# Build the distributable
uv build

# Bring up a local Postgres for the persistence layer (schema auto-loaded from
# chesssnake/data/init.sql). Exposes Postgres on host port 5433.
docker compose up
```

Package data (`data/*.sql`, `data/*.ttf`, `data/img/*.png`) is declared under `[tool.setuptools.package-data]` in `pyproject.toml` and accessed at runtime via `importlib.resources.files('chesssnake')`. If you add runtime assets, register them there or they won't ship in the wheel. `uv.lock` is committed and should be kept in sync (`uv lock`).

## Two-layer architecture

The single public export is `Game`, but **which `Game` you get depends on whether psycopg2 is installed** (`chesssnake/__init__.py`):

- No psycopg2 → `chesssnake.chesslib.Game.Game` (in-memory only).
- psycopg2 or psycopg2-binary present → `chesssnake.postgres.Game.Game` (subclass adding SQL persistence).

`postgres.Game` extends `chesslib.Game`, overriding `move`/`draw_*` to call `update_db()`/`update_draw_status()` after delegating to `super()`. So the chess rules live in one place; the SQL subclass only adds persistence side effects. When changing gameplay behavior, edit `chesslib`; the postgres layer inherits it.

### `chesslib/` — the engine (no external deps beyond nothing)

- `Chess.py` (~3000 lines) is the core. Key classes:
  - `Piece` and subclasses `Rook/Knight/Bishop/Queen/King/Pawn`. Each piece implements `threatens(square, board)` (squares it attacks, ignoring pins), `can_move(square, board)` (legality including pin analysis), and a `@staticmethod find(...)` that resolves a target square + optional file/rank disambiguation back to the piece that made the move (this is how algebraic notation is parsed into a concrete piece).
  - `Square(i, j, piece)` and `Board`. **Coordinate system: `i` = row index 0–7 from the top (i=0 is rank 8, i=7 is rank 1); `j` = file index 0–7 (j=0 is file a). Color: `0` = white, `1` = black.** `board[i, j]` returns the `Square` or `None` if off-board — off-board returning `None` is load-bearing for the sliding-piece search loops.
  - `Board.status`: `0` in play, `1` checkmate, `2` stalemate/draw (the schema allows 0–4). Set inside `Board.move()`.
  - `Board.two_moveP`: the `Square` a pawn double-stepped to last move, for en passant.
  - `Move` class parses/validates coordinate notation; `Move.is_valid_c_notation()` is the notation gate called before any move.
- `ChessImg.py` — `img(board, p1, p2, move=None) -> PIL.Image`. Composites piece PNGs from `data/img/` onto a template, renders both white- and black-oriented boards, overlays player names (truncated to 10 chars) and highlights the last move in orange. All coordinates are in 68px tiles.
- `ChessError.py` — gameplay exception hierarchy rooted at `ChessError`. `move()` raises these for illegal/ambiguous input (see the `Game.move` docstring for the full list).

### `postgres/` — persistence

- `Game.py` — the SQL `Game` subclass plus a `Challenge` class (pending-challenge matchmaking) and a module-level `db_init(sql_creds, create_database)` bootstrap.
  - Games are keyed by the composite `(GroupId, WhiteId, BlackId)` — all BIGINTs. `sql_game_init` does an upsert-then-select so constructing a `Game` either loads the existing row or creates a fresh one.
  - `sql=True` (default) requires manual `game.update_db()`; `auto_sql=True` writes after every mutating call (fewer round-trips per the README).
  - Board persistence: `Board.disassemble_board()` serializes to a `;`-delimited string of `<type><color>`/`--` tokens plus a 6-char `moved` castling-rights string (documented in that method's docstring); `Board.assemble_board()` reverses it. These two must stay in sync.
- `PSql_Utils.py` — connection pooling (`initialize_connection_pool`), credential loading, and `execute_psql(statement, params)`, which every query goes through. `execute_psql` always commits on success and rolls back on error, and returns a list of dict-like rows (or `None`). It uses a `RealDictCursor`, so **query results are dict rows keyed by column name — and PostgreSQL folds unquoted identifiers to lowercase, so the keys are lowercase** (`row['opponentid']`, not `row['OpponentId']`) unless a query quotes the alias. Credentials come from `CHESSDB_CONN_STR` or the `CHESSDB_NAME/USER/PASS/HOST/PORT` env vars (host/port default to `localhost`/`5432`); pass a `sql_creds` dict to override.
- `data/init.sql` — idempotent schema for `Games` and `Challenges` (composite PKs `(GroupId, WhiteId, BlackId)` / `(GroupId, Challenger, Challenged)`, an `UpdatedAt` trigger, and partial-key indexes). `Turn`/`Draw`/`Status` are stored as `INTEGER` (not booleans) to match how the code reads them. There is no `Groups` table — `GroupId` is just a discriminator, not a foreign key.
- `GameError.py` — SQL/challenge exception hierarchy rooted at `GameError` (separate from `chesslib`'s `ChessError`).

## Conventions

- Docstrings are reStructuredText (`:param:`/`:type:`/`:raises:`) and thorough — match that style, and keep the `:raises:` lists accurate since they're the closest thing to a spec for `move()`.
- The sliding-piece `threatens`/`find` methods are intentionally repetitive (one unrolled block per direction) for performance; follow the existing pattern rather than abstracting it when editing.