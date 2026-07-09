# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`chesssnake` is a PyPI library (`pip install chesssnake`) for playing, visualizing, and persisting chess games. It has a pure-Python chess engine, a PIL-based board renderer, and a **3-tier persistence architecture**: a `Game` client that runs the engine locally and syncs state over REST → a FastAPI **api-endpoint** (`chesssnake api-endpoint`) → PostgreSQL. Many game clients can share one api-endpoint/database. Current version is 0.6.7 (pre-1.0; the REST api-endpoint is the in-progress 0.7.0 work — see `VersionHistory.md`).

The package uses a **`src/` layout**: all importable code lives under `src/chesssnake/` (tests import the installed package, not a repo-root package).

## Commands

The project is managed with **uv**; all metadata lives in `pyproject.toml` (there is no `setup.py` or `requirements.txt`). The build backend is setuptools. Development is manual:

```bash
# Create/refresh the venv. Extras: `client` (requests, for remote games),
# `api` (fastapi + uvicorn + psycopg2, for the server).
uv sync                                  # core only (local, in-memory games)
uv sync --extra api --extra client --group dev   # everything needed to run + test the full stack

# Run anything inside the managed environment
uv run python examples/example.py        # core (no-DB) smoke example

# Run the api-endpoint server (needs the `api` extra + CHESSDB_* env / docker compose Postgres)
uv run chesssnake api-endpoint --host 0.0.0.0 --port 8000 --init-db
uv run chesssnake init-db                # just create the schema, then exit

# Tests (the `dev` group provides pytest, pgserver, fastapi, requests, httpx)
uv run pytest                            # everything under tests/
uv run pytest tests/unit                 # fast, pure-Python engine tests (no DB)
uv run pytest tests/integration          # API + remote-Game stack; spins up a throwaway
                                         # Postgres via pgserver (no Docker/system Postgres)
uv run pytest tests/unit/test_rules.py::test_en_passant_capture  # a single test

# Add/remove dependencies (edits pyproject.toml + uv.lock)
uv add <pkg>
uv add --group dev <pkg>                 # add a dev/test dependency
uv add --optional api <pkg>              # add to the `api` extra

# Build the distributable
uv build

# Bring up a local Postgres for the api-endpoint to talk to (schema auto-loaded from
# src/chesssnake/data/init.sql). Exposes Postgres on host port 5433.
docker compose up
```

Package data (`data/*.sql`, `data/*.ttf`, `data/img/*.png`) is declared under `[tool.setuptools.package-data]` in `pyproject.toml` and accessed at runtime via `chesssnake.assets.asset_path("img/template.png")` (a thin wrapper over `importlib.resources`). If you add runtime assets, register them there or they won't ship in the wheel. `uv.lock` is committed and should be kept in sync (`uv lock`).

## Three-tier architecture

The public exports are `Game`, the challenge helpers (`challenge`, `challenge_exists`, `delete_challenge`), and the enums (`Color`, `GameStatus`, `PieceType`) — see `src/chesssnake/__init__.py`. `Game` is an `engine.Game` subclass built via **factory methods** (not a flag-laden constructor):

- `Game.local(white_name=..., black_name=...)` — pure in-memory game. No network, no `requests`/psycopg2 imported. The engine runs in-process.
- `Game.remote(white_id, black_id, group_id=..., api_url=..., api_key=..., client=...)` — a game persisted through the api-endpoint. **The server runs the engine**: `move`/`draw_*` send a request, and the returned state is mirrored into the local board (for rendering + accessors). Illegal moves raise the same `ChessError` types as local play. `refresh()` re-fetches server state (e.g. the opponent moved). `api_url` falls back to `CHESSSNAKE_API_URL`.

Gameplay state is read through intention-revealing accessors on `Game`: `to_move` (Color), `is_over` (bool), `result` (GameStatus), `winner` (Color|None), `draw_offered_by` (Color|None). The public `Game.move()` returns a `MoveResult` (from/to squares, check, castle/promotion/en, + the new state); rendering is separate (`render()` / `save(path)`). *(The base `engine.Game.move()` returns the bare engine `Move`; the public `remote.Game` deliberately overrides it to return the richer `MoveResult` — the two `# type: ignore` lines in `remote/game.py` mark that intentional divergence.)*

The three tiers and where they live:

1. **Client** (`src/chesssnake/remote/`) — `Game` + the challenge functions (`game.py`); `ApiClient` (`client.py`) is a thin `requests`-style wrapper (talks to the `/v1` routes, sends an optional `X-API-Key`). For **remote** games the client does **no** chess computation — it sends moves and mirrors the returned state. For **local** games `move`/`draw_*` call the base `engine.Game` in-process. `requests` is imported lazily (only on the remote path), so local games stay dependency-free.
2. **Server** (`src/chesssnake/api/server.py`) — a FastAPI `app` that **owns the engine** (the authoritative rules). `/health` is unversioned/open; all game+challenge routes live on a `/v1` `APIRouter` gated by an optional API-key dependency (`require_api_key`, active only when `CHESSSNAKE_API_KEY` is set). Move/draw routes load the row, build an `engine.Game` (via `serialize.game_from_state`), apply the action (which may raise `ChessError`), and persist the result — all inside one `apply_game_change` transaction. Domain errors map to JSON `{error_type, detail}` with status codes (chess error→400, id→422, not-found→404, challenge→409, sql→500); the client re-raises the matching `ChessError`/`GameError` type.
3. **Database** (`src/chesssnake/db/`) — the SQL, behind a common interface (`db/__init__.py` re-exports the operations so callers depend on `chesssnake.db`, leaving room for a future `db/sqlite.py`). `db/postgres.py` holds the query functions (`game_get_or_create`, `game_get`, `apply_game_change`, `game_delete`, `current_games`, `game_exists`, `challenge*`); `db/sql.py` the pool + `execute_psql` + the `transaction()` context manager; `db/errors.py` the `GameError` types (incl. `GameNotFoundError`); `data/init.sql` the schema. **This layer stays engine-free** — `apply_game_change` runs the caller's `mutate` callback (the engine logic) between a `SELECT … FOR UPDATE` and the `UPDATE`, so concurrent moves on one game can't clobber each other.

The wire payloads are defined once in `src/chesssnake/dto.py`: `GameState` (persisted state) and `MoveResult` (a move + resulting state) — stdlib dataclasses, so the client needs no pydantic. `src/chesssnake/serialize.py` bridges `GameState` ⇄ engine objects (`board_from_state`, `game_from_state`, `state_from_game`), used by both the server (to drive the engine) and the client (to mirror state for rendering). `src/chesssnake/cli.py` is the `chesssnake` console-script entry point (`api-endpoint`, `init-db`); `src/chesssnake/assets.py` (`asset_path`) centralizes packaged-data lookups.

When changing **gameplay** behavior, edit `engine` — every tier (local games and the server) inherits it. When changing **persistence or the wire protocol**, edit `db/postgres.py` (SQL) and/or `dto.py` (payloads) + `serialize.py` (bridge), and mirror the endpoint in `api/server.py` + the method in `remote/client.py`.

### `engine/` — the chess engine (no external deps beyond Pillow, for rendering)

`Chess.py` was split into focused modules; the package `__init__.py` re-exports the public names so `from chesssnake.engine import Board, Move, Square, Game, Color, PieceType, GameStatus, render_board` works.

- `enums.py` — `Color(IntEnum)` (WHITE=0/BLACK=1, with `.opponent`), `PieceType` (a plain `Enum`; `.value` is the letter code `'K'/'Q'/...`, used at serialization/render boundaries — never `str()` an enum member), and `GameStatus(IntEnum)` (IN_PLAY/CHECKMATE/DRAW). These are threaded through the engine; **serialization always converts via `int(color)` / `piecetype.value`** so the wire format stays byte-identical across Python versions.
- `pieces.py` — `Piece` and subclasses `Rook/Knight/Bishop/Queen/King/Pawn`. Movement uses `(di, dj)` direction-vector tables through shared `_slide`/`_step` scan helpers. Each piece implements `threatens(square, board)` (squares it attacks, ignoring pins), `can_move(square, board)` (pin-aware), `find_all(...) -> list[Square]` (never raises; used for threat detection) and `find_one(...) -> Square` (resolves algebraic notation, validates the target, raises on 0/ambiguous). Sliding pieces share `_pinned_move_allowed`.
- `square.py` — `Square(i, j, piece)`. **Coordinate system: `i` = row index 0–7 from the top (i=0 is rank 8, i=7 is rank 1); `j` = file index 0–7 (j=0 is file a). Piece color: `Color.WHITE`=0, `Color.BLACK`=1.**
- `board.py` — `Board`. `board[i, j]` returns the `Square` or `None` if off-board — off-board returning `None` is load-bearing for the sliding-piece scan loops. `board.lifted(square)` is a context manager that temporarily removes a piece (used by pin/mate analysis).
  - `Board.status`: a `GameStatus` (`IN_PLAY`/`CHECKMATE`/`DRAW`; the schema allows 0–4). Set inside `Board.move()`.
  - `Board.two_moveP`: the `Square` a pawn double-stepped to last move, for en passant.
- `move.py` — the `Move` class parses/validates one algebraic move against a board.
- `notation.py` — the `FILES`/`RANKS` constants, coordinate↔notation helpers (`get_coords`, `get_c_notation`), `is_valid_c_notation` (the notation gate called before any move), and `matches_disambiguation`. `Board.get_coords`/`Board.get_c_notation`/`Move.is_valid_c_notation` are kept as thin facades delegating here.
- `image.py` — `render_board(board, white_name, black_name, move=None) -> PIL.Image`. Composites piece PNGs from `data/img/` (cached) onto a template, renders both white- and black-oriented boards via `_render_side`, overlays player names (truncated to 10 chars) and highlights the last move in orange. All coordinates are in 68px tiles.
- `errors.py` — gameplay exception hierarchy rooted at `ChessError`. `move()` raises these for illegal/ambiguous input (see the `Game.move` docstring for the full list).
- `game.py` — the base `Game` controller (turns, move validation, draw offers, rendering) that `remote/game.py`'s `Game` subclasses. `turn` is a `Color`; `draw` is `Color | None`.

### `remote/` — the client (tier 1)

- `game.py` — `Game(BaseGame)` (built via `Game.local()`/`Game.remote()`, described above) plus module-level challenge functions `challenge`/`challenge_exists`/`delete_challenge` (pending-challenge matchmaking; each takes `api_url=`/`api_key=`/`client=`). The low-level `Game.__init__(*args, client=None, **kwargs)` is internal — use the factories. For remote games, `move`/`draw_*` call the client and pass the returned `GameState` to `_apply_state` (which rebuilds the mirror board via `serialize.board_from_state`); `last_move` is set to a lightweight `_MoveMarker` for render highlighting.
  - Games are keyed by the composite `(group_id, white_id, black_id)` — all BIGINTs. `POST /v1/games` does an upsert-then-select so a game either loads the existing row or creates a fresh one.
- `client.py` — `ApiClient(base_url, session=None, api_key=None)`. Prefixes every request with `/v1` and (if set) an `X-API-Key` header. `session` defaults to a `requests.Session()` but can be **injected** (the tests pass a FastAPI `TestClient`, which is request-compatible — this is how the integration tests drive the app in-process). `move()` returns a `dto.MoveResult`; `get_state`/`get_or_create_game`/draw methods return `dto.GameState`; `image()` returns PNG bytes. Non-2xx → re-raises the mapped exception. **Error mapping** covers both `engine.errors` (`ChessError`…) and `db.errors` (`GameError`…): `_build_error_registry` maps class name→class, and `_raise` reconstructs the exception with `cls.__new__(cls); exc.args=(detail,)` (bypassing the custom constructors) so `except PromotionError` still works.

### `api/` — the server (tier 2, **owns the engine**)

- `server.py` — the FastAPI `app`. `/health` is unversioned and open; game+challenge routes live on a `/v1` `APIRouter` with a `require_api_key` dependency (enforced only when `CHESSSNAKE_API_KEY` is set, checked per-request). Key routes: `POST .../moves` (body `{move}`) and `POST .../draw/offer|accept|decline` (body `{player_id}`) build an `engine.Game` from the stored row, apply the action, and persist — inside `apply_game_change` (one locked transaction); `GET .../` returns state, `GET .../image` returns a PNG (rendered server-side). Request bodies (`GameCreate`/`MoveBody`/`DrawBody`/`ChallengeBody`) are pydantic; responses are `dto` dataclasses serialized to dicts. Exception handlers map `ChessError`→400, `SQLIdError`→422, `GameNotFoundError`→404, `ChallengeError`→409, `SQLError`→500, `GameError`→400. A `lifespan` handler initializes the pool from env creds (schema init if `CHESSSNAKE_INIT_DB`).

### `db/` — the database layer (tier 3, **engine-free**)

- `__init__.py` — the common interface: re-exports the operation functions and `errors`/`sql`/`postgres` so callers use `chesssnake.db`. A future `db/sqlite.py` can implement the same functions behind this interface.
- `postgres.py` — the PostgreSQL backend: `game_get_or_create`, `game_get`, `apply_game_change` (SELECT…FOR UPDATE → `mutate(row)` callback → UPDATE, all in one `transaction()`), `game_delete`, `current_games`, `game_exists`, `challenge*`, `db_init`. Deals only in primitives/dicts — **no `engine` import**; the chess logic is the server's `mutate` callback. Validates ids via `validate_ids`.
- `sql.py` — connection pooling (`initialize_connection_pool`), credential loading, `execute_psql(statement, params)` (single statement, commits/rolls back, returns dict rows), and `transaction()` (a context manager yielding a cursor for multi-statement atomic read-modify-write). It uses a `RealDictCursor`, so **query results are dict rows keyed by column name — and PostgreSQL folds unquoted identifiers to lowercase, so the keys are lowercase** (`row['opponentid']`, not `row['OpponentId']`) unless a query quotes the alias. Credentials come from `CHESSDB_CONN_STR` or the `CHESSDB_NAME/USER/PASS/HOST/PORT` env vars (host/port default to `localhost`/`5432`); pass a `sql_creds` dict to override.
- `data/init.sql` — idempotent schema for `Games` and `Challenges` (composite PKs `(GroupId, WhiteId, BlackId)` / `(GroupId, Challenger, Challenged)`, an `UpdatedAt` trigger, and partial-key indexes). `Turn`/`Draw`/`Status` are stored as `INTEGER` (not booleans) to match how the code reads them. There is no `Groups` table — `GroupId` is just a discriminator, not a foreign key.
- `errors.py` — SQL/challenge exception hierarchy rooted at `GameError` (an `Exception` subclass, separate from the engine's `ChessError`; shared by client and server for error mapping). (Its `### db/` header replaces the former `postgres/` package.)

## Conventions

- Docstrings are reStructuredText (`:param:`/`:type:`/`:raises:`) and thorough — match that style, and keep the `:raises:` lists accurate since they're the closest thing to a spec for `move()`.
- Piece movement is data-driven: `(di, dj)` direction-vector tables fed through the shared `_slide`/`_step` scan helpers in `pieces.py`. Add a piece or tweak movement by editing its direction table, not by unrolling per-direction blocks. (This replaces the engine's earlier hand-unrolled loops, which were consolidated in the Phase 2 refactor.)
- Enums are the source of truth for color/piece-type/status; convert to primitives (`int(color)`, `piecetype.value`) only at the serialization and rendering boundaries — never rely on `str()` of an enum member.