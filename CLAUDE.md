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

The public exports are `Game`, the challenge helpers (`challenge`, `challenge_exists`, `delete_challenge`), and the enums (`Color`, `GameStatus`, `PieceType`, `Termination`) — see `src/chesssnake/__init__.py`. `Game` is an `engine.Game` subclass built via **factory methods** (not a flag-laden constructor):

- `Game.local(white_name=..., black_name=...)` — pure in-memory game. No network, no `requests`/psycopg2 imported. The engine runs in-process; it has the **full rules** (draw-by-rule, resign, legal-move listing, FEN/PGN) so a local game behaves identically to a remote one.
- `Game.remote(white_id, black_id, group_id=..., player_id=..., generation=..., api_url=..., api_key=..., client=...)` — a game persisted through the api-endpoint. **The server runs the engine**: `move`/`draw_*`/`resign` send a request, and the returned state is mirrored into the local board (for rendering + accessors). Illegal moves raise the same `ChessError` types as local play. `refresh()` re-fetches state; `player_id` (if given) is asserted server-side; the client auto-sends its `version` for optimistic concurrency. `generation=N` loads a specific past game (read-only); `Game.archive(...)` lists all games between the triple. Re-opening a triple whose current game is **over** starts a rematch (a new generation).

Gameplay state is read through intention-revealing accessors on `Game`: `to_move` (Color), `is_over` (bool), `result` (GameStatus: `IN_PLAY`/`WHITE_WON`/`BLACK_WON`/`DRAW`), `winner` (Color|None), `termination` (Termination|None), `draw_offered_by` (Color|None). The public `Game.move()` returns a `MoveResult` (from/to/san, check, castle/promotion/en, + the new state); rendering is separate (`render()` / `save(path)`). Other engine methods: `resign(player_id)`, `legal_moves()`, `pgn()`, `fen` (property), `Game.from_fen(...)`. *(The base `engine.Game.move()` returns the bare engine `Move`; the public `remote.Game` deliberately overrides it to return the richer `MoveResult` — the two `# type: ignore` lines in `remote/game.py` mark that intentional divergence.)*

The three tiers and where they live:

1. **Client** (`src/chesssnake/remote/`) — `Game` + the challenge functions (`game.py`); `ApiClient` (`client.py`) is a thin `requests`-style wrapper (talks to the `/v1` routes, sends an optional `X-API-Key`). For **remote** games the client does **no** chess computation — it sends moves and mirrors the returned state. For **local** games `move`/`draw_*` call the base `engine.Game` in-process. `requests` is imported lazily (only on the remote path), so local games stay dependency-free.
2. **Server** (`src/chesssnake/api/server.py`) — a FastAPI `app` that **owns the engine** (the authoritative rules). `/health` is unversioned/open; all game+challenge routes live on a `/v1` `APIRouter` gated by an optional API-key dependency (`require_api_key`, active only when `CHESSSNAKE_API_KEY` is set). Mutating routes (`/moves`, `/resign`, `/draw/*`) load the row + its `Moves` history, build an `engine.Game` (via `serialize.game_from_state`), apply the action (which may raise `ChessError`), and persist the result — all inside one `apply_game_change` transaction; they accept an optional `player_id` (validated → `NotYourTurnError`/403) and `expected_version` (→ `VersionConflictError`/409). Read routes: `GET .../` (state), `.../legal-moves`, `.../history`, `.../pgn` (text), `.../fen` (text), `.../image` (PNG). Errors map to JSON `{error_type, detail}` (chess→400, auth→403, not-found→404, challenge/version→409, id→422, sql→500).
3. **Database** (`src/chesssnake/db/`) — the SQL, behind a common interface (`db/__init__.py`; room for a future `db/sqlite.py`). `db/postgres.py` holds the query functions (`game_get_or_create`, `game_get`, `game_history`, `apply_game_change`, `game_delete`, `current_games`, `game_exists`, `challenge*`); `db/sql.py` the pool + `execute_psql` + the `transaction()` context manager; `db/errors.py` the `GameError` types (`GameNotFoundError`, `NotYourTurnError`, `VersionConflictError`, …); `data/init.sql` the schema. The **`Games`** table stores the position as a single `Fen` column plus `Status`/`Draw`/`Termination`/`Version` (no more per-field board columns); the **`Moves`** table stores one row per ply (`San` + `PositionKey`, plus a ply-0 row for the initial position) for PGN and threefold detection. **This layer stays engine-free** — `apply_game_change` runs the caller's `mutate(row, history)` callback (the engine logic) between a `SELECT … FOR UPDATE` and the `UPDATE`, bumping `Version` and appending `Moves` rows atomically.

The wire payloads are defined once in `src/chesssnake/dto.py`: `GameState` (the position as **FEN** + `status`/`version`/`generation`/`draw`/`termination`/names) and `MoveResult` (a move + resulting state, incl. `san`) — stdlib dataclasses, so the client needs no pydantic. The FEN codec is `src/chesssnake/engine/fen.py` (`to_fen`/`from_fen`/`position_key`/`INITIAL_FEN`), and `src/chesssnake/serialize.py` bridges `GameState` ⇄ engine `Game` (`game_from_state` with history, `state_from_game`, `board_and_turn`). `src/chesssnake/cli.py` is the console-script entry point; `src/chesssnake/assets.py` (`asset_path`) centralizes packaged-data lookups.

When changing **gameplay** behavior, edit `engine` — every tier (local games and the server) inherits it. When changing **persistence or the wire protocol**, edit `db/postgres.py` (SQL) and/or `dto.py` (payloads) + `serialize.py` (bridge), and mirror the endpoint in `api/server.py` + the method in `remote/client.py`.

### `engine/` — the chess engine (no external deps beyond Pillow, for rendering)

`Chess.py` was split into focused modules; the package `__init__.py` re-exports the public names so `from chesssnake.engine import Board, Move, Square, Game, Color, PieceType, GameStatus, render_board` works.

- `enums.py` — `Color(IntEnum)` (WHITE=0/BLACK=1, with `.opponent`), `PieceType` (a plain `Enum`; `.value` is the letter code — never `str()` an enum member), `GameStatus(IntEnum)` (`IN_PLAY=0`/`WHITE_WON=1`/`BLACK_WON=2`/`DRAW=3`, with `.won_by(color)`), and `Termination(str, Enum)` (checkmate/resignation/stalemate/threefold/fifty_move/insufficient_material/agreement). A win is `WHITE_WON`/`BLACK_WON` (checkmate **or** resignation); the reason is the `Termination`.
- `pieces.py` — `Piece` and subclasses `Rook/Knight/Bishop/Queen/King/Pawn`. Movement uses `(di, dj)` direction-vector tables through shared `_slide`/`_step` scan helpers. Each piece implements `threatens`, `can_move`, `find_all(...) -> list[Square]` (never raises) and `find_one(...) -> Square` (resolves notation, raises on 0/ambiguous). Sliding pieces share `_pinned_move_allowed`.
- `square.py` — `Square(i, j, piece)`. **Coordinate system: `i` = row 0–7 from the top (i=0 is rank 8); `j` = file 0–7 (j=0 is file a). Piece color: `Color.WHITE`=0, `Color.BLACK`=1.**
- `fen.py` — the board serialization format (standard **FEN**, replacing the old bespoke string): `to_fen(board, turn)`, `from_fen(fen) -> (board, turn)`, `position_key(board, turn)` (first four FEN fields, for threefold), `INITIAL_FEN`.
- `board.py` — `Board`. `board[i, j]` returns the `Square` or `None` if off-board (load-bearing for scan loops). `board.lifted(square)` temporarily removes a piece (pin/mate analysis). `Board.move()` sets `status`/`termination` and updates `halfmove_clock`/`fullmove_number`; it detects checkmate, stalemate, `insufficient_material()`, and the fifty-move rule (threefold is applied by `Game.move`, which holds the position history). `Board.legal_moves(turn)` enumerates fully-legal moves. `two_moveP` is the pawn's landing square for en passant.
- `san.py` — `to_san(board, prev, to, piece, ...)` builds a **postable** move string (chesssnake notation), used by `legal_moves`. PGN-style formatting (`O-O`, `=Q`) is applied at export in `game.pgn()`.
- `move.py` — the `Move` class parses/validates one algebraic move against a board.
- `notation.py` — `FILES`/`RANKS`, coord↔notation helpers, `is_valid_c_notation`, `matches_disambiguation`. `Board.get_coords`/`get_c_notation`/`Move.is_valid_c_notation` are facades delegating here.
- `image.py` — `render_board(board, white_name, black_name, move=None, perspective=None) -> PIL.Image`; composites cached piece PNGs, 68px tiles, last-move highlight. `perspective=None` → the wide both-orientations-with-names image; `perspective=Color.WHITE`/`BLACK` (or `"white"`/`"black"`) → a single board from that side (board only, via the shared `_render_side`).
- `errors.py` — gameplay exception hierarchy rooted at `ChessError`.
- `game.py` — the base `Game` controller that `remote/game.py`'s `Game` subclasses. Holds `turn` (Color), `draw` (Color|None), `move_history` (SAN, for PGN) and `position_history` (keys, for threefold). Methods: `move` (records SAN + threefold), `resign`, `draw_*`, `legal_moves`, `pgn`, `fen` (property), `from_fen` (classmethod).

### `remote/` — the client (tier 1)

- `game.py` — `Game(BaseGame)` (built via `Game.local()`/`Game.remote()`) plus module-level challenge functions. The low-level `Game.__init__(*args, client=None, player_id=None, version=None, **kwargs)` is internal — use the factories. For remote games, `move`/`resign`/`draw_*` call the client (sending `player_id` + the tracked `version`) and pass the returned state to `_apply_state` (rebuilds the mirror board via `serialize.board_and_turn` from the FEN, updates `version`); `last_move` is a lightweight `_MoveMarker` for render highlighting. `legal_moves`/`pgn`/`history` proxy to the server when remote, or run the local engine otherwise.
  - Games are keyed by the composite `(group_id, white_id, black_id)` — all BIGINTs. `POST /v1/games` upserts-then-selects.
- `client.py` — `ApiClient(base_url, session=None, api_key=None)`. Prefixes `/v1`, adds `X-API-Key` when set. `session` defaults to `requests.Session()` but can be **injected** (tests pass a FastAPI `TestClient`). `move()` → `dto.MoveResult`; `get_state`/`get_or_create_game`/`resign`/draw → `dto.GameState`; `legal_moves`/`history` → lists; `pgn`/`fen` → text; `image()` → PNG bytes. **Error mapping** covers both `engine.errors` and `db.errors`: `_build_error_registry` maps class name→class, and `_raise` reconstructs via `cls.__new__(cls); exc.args=(detail,)` so `except PromotionError`/`except VersionConflictError` work.

### `api/` — the server (tier 2, **owns the engine**)

- `server.py` — the FastAPI `app`. `/health` is unversioned/open; `/v1` routes gated by `require_api_key`. Mutating routes (`POST .../moves` `{move, player_id?, expected_version?}`, `POST .../resign`, `POST .../draw/{offer|accept|decline}` `{player_id, expected_version?}`) build an `engine.Game` from the stored row + `Moves` history and apply the action inside `apply_game_change` (one locked transaction). Read routes: `GET .../` (state), `.../archive` (all generations), `.../legal-moves`, `.../history`, `.../pgn` + `.../fen` (`PlainTextResponse`), `.../image` (PNG). Read routes take an optional `?generation=` (a past game; default = current); `/image` also takes `?perspective=white|black`. Request bodies are pydantic; responses are `dto` dataclasses as dicts. Handlers: `ChessError`→400, `NotYourTurnError`→403, `GameNotFoundError`→404, `ChallengeError`/`VersionConflictError`→409, `SQLIdError`→422, `SQLError`→500, `GameError`→400. `lifespan` inits the pool (schema init if `CHESSSNAKE_INIT_DB`).

### `db/` — the database layer (tier 3, **engine-free**)

- `__init__.py` — the common interface: re-exports the operation functions and `errors`/`sql`/`postgres` so callers use `chesssnake.db`. A future `db/sqlite.py` can implement the same functions behind this interface.
- `postgres.py` — the PostgreSQL backend. "Current" game = the max-`Generation` row for a triple (`_IDS` is the shared WHERE clause). `game_get_or_create` returns the current game, or creates the next generation when the current one is **over** (rematch) — race-safe via `ON CONFLICT` + re-select. `game_get(…, generation=None)` / `game_history(…, generation)` / `game_delete(…, generation=None)` default to the current game; `game_archive` lists all generations. `apply_game_change` locks + mutates the **current** game (`… ORDER BY Generation DESC LIMIT 1 FOR UPDATE` → `mutate(row, history)` → `UPDATE`+bump `Version`+append `Moves`, one `transaction()`; enforces `expected_version`). `game_exists`/`current_games` are **active-only** (`Status = 0`), so a finished game doesn't block a rematch. Deals only in primitives/dicts — **no `engine` import**; the engine-derived initial FEN/key are passed *in*. Validates ids via `validate_ids`.
- `sql.py` — connection pooling (`initialize_connection_pool`), credential loading, `execute_psql(statement, params)` (single statement, commits/rolls back, returns dict rows), and `transaction()` (a context manager yielding a cursor for multi-statement atomic read-modify-write). It uses a `RealDictCursor`, so **query results are dict rows keyed by column name — and PostgreSQL folds unquoted identifiers to lowercase, so the keys are lowercase** (`row['opponentid']`, not `row['OpponentId']`) unless a query quotes the alias. Credentials come from `CHESSDB_CONN_STR` or the `CHESSDB_NAME/USER/PASS/HOST/PORT` env vars (host/port default to `localhost`/`5432`); pass a `sql_creds` dict to override.
- `data/init.sql` — idempotent schema for `Games`, `Moves`, and `Challenges`. A triple can own **many** games, one per `Generation` (the "current" game = highest generation; earlier ones are the read-only archive). `Games` PK `(GroupId, WhiteId, BlackId, Generation)` stores `Fen TEXT`, `Draw`/`Status` (INTEGER; Status 0–3), `Termination TEXT`, `Version INTEGER`, names, and an `UpdatedAt` trigger. `Moves` PK `(GroupId, WhiteId, BlackId, Generation, Ply)` stores `San` + `PositionKey`. There is no `Groups` table — `GroupId` is just a discriminator, not a foreign key.
- `errors.py` — SQL/challenge exception hierarchy rooted at `GameError` (an `Exception` subclass, separate from the engine's `ChessError`; shared by client and server for error mapping). (Its `### db/` header replaces the former `postgres/` package.)

## Conventions

- Docstrings are reStructuredText (`:param:`/`:type:`/`:raises:`) and thorough — match that style, and keep the `:raises:` lists accurate since they're the closest thing to a spec for `move()`.
- Piece movement is data-driven: `(di, dj)` direction-vector tables fed through the shared `_slide`/`_step` scan helpers in `pieces.py`. Add a piece or tweak movement by editing its direction table, not by unrolling per-direction blocks. (This replaces the engine's earlier hand-unrolled loops, which were consolidated in the Phase 2 refactor.)
- Enums are the source of truth for color/piece-type/status; convert to primitives (`int(color)`, `piecetype.value`) only at the serialization and rendering boundaries — never rely on `str()` of an enum member.