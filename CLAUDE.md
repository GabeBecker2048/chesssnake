# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`chesssnake` is a PyPI library (`pip install chesssnake`) for playing, visualizing, and persisting chess games. It has a pure-Python chess engine, a PIL-based board renderer, and a **3-tier persistence architecture**: a `Game` client that runs the engine locally and syncs state over REST → a FastAPI **api-endpoint** (`chesssnake api-endpoint`) → SQLite or PostgreSQL. Many game clients can share one api-endpoint/database. Current version is 0.9.0 (pre-1.0; the REST api-endpoint shipped in 0.7.0, the configuration system in 0.8.0, SQLite/SQLAlchemy in 0.9.0 — see `VersionHistory.md`).

The package uses a **`src/` layout**: all importable code lives under `src/chesssnake/` (tests import the installed package, not a repo-root package).

## Commands

The project is managed with **uv**; all metadata lives in `pyproject.toml` (there is no `setup.py` or `requirements.txt`). The build backend is setuptools. Development is manual:

```bash
# Create/refresh the venv. Extras: `client` (requests, for remote games),
# `api` (fastapi + uvicorn + pydantic + sqlalchemy — runs on SQLite with no
# compiled deps), `postgres` (psycopg2, only for postgresql:// URLs).
# `.python-version` pins local dev to 3.12 because the `pg` test group's
# `pgserver` only ships cp311/cp312 wheels; the package itself supports 3.11-3.14
# and the SQLite tests run on all of them.
uv sync                                  # core only (local, in-memory games)
uv sync --extra api --extra client --extra postgres --group dev --group pg   # full stack

# Run anything inside the managed environment
uv run python examples/example.py        # core (no-DB) smoke example

# Run the api-endpoint server (needs the `api` extra + a configured database.url / docker compose Postgres)
uv run chesssnake api-endpoint --host 0.0.0.0 --port 8000 --init-db
uv run chesssnake init-db                # just create the schema, then exit
uv run chesssnake config init            # write a commented default config file
uv run chesssnake config show            # effective settings + where each came from

# Tests (`dev` provides pytest/fastapi/httpx/sqlalchemy; `pg` provides pgserver + psycopg2)
uv run pytest                            # everything under tests/
uv run pytest tests/unit                 # fast, pure-Python engine tests (no DB)
uv run pytest tests/integration          # API + remote-Game stack, run against BOTH backends:
                                         # a temp SQLite file and a throwaway Postgres (pgserver)
CHESSSNAKE_TEST_BACKENDS=sqlite uv run pytest tests/integration   # SQLite only (no pgserver needed)
uv run pytest tests/config               # config + CLI; needs pydantic but no database
uv run pytest tests/unit/test_rules.py::test_en_passant_capture  # a single test

# Add/remove dependencies (edits pyproject.toml + uv.lock)
uv add <pkg>
uv add --group dev <pkg>                 # add a dev/test dependency
uv add --optional api <pkg>              # add to the `api` extra

# Build the distributable
uv build

# Bring up a local Postgres for the api-endpoint to talk to (create the schema with
# `chesssnake init-db`). Exposes Postgres on host port 5433.
docker compose up
```

Package data (`data/*.sql`, `data/*.ttf`, `data/img/*.png`) is declared under `[tool.setuptools.package-data]` in `pyproject.toml` and accessed at runtime via `chesssnake.assets.asset_path("img/template.png")` (a thin wrapper over `importlib.resources`). If you add runtime assets, register them there or they won't ship in the wheel. `uv.lock` is committed and should be kept in sync (`uv lock`).

## Three-tier architecture

The public exports are `Game`, the challenge helpers (`challenge`, `challenge_exists`, `delete_challenge`), the head-to-head `record` helper, and the enums (`Color`, `GameStatus`, `PieceType`, `Termination`) — see `src/chesssnake/__init__.py`. `Game` is an `engine.Game` subclass built via **factory methods** (not a flag-laden constructor):

- `Game.local(white_name=..., black_name=...)` — pure in-memory game. No network, no `requests`/psycopg2 imported. The engine runs in-process; it has the **full rules** (draw-by-rule, resign, legal-move listing, FEN/PGN) so a local game behaves identically to a remote one.
- `Game.remote(white_id, black_id, group_id=..., player_id=..., generation=..., api_url=..., api_key=..., client=...)` — a game persisted through the api-endpoint. **The server runs the engine**: `move`/`draw_*`/`resign` send a request, and the returned state is mirrored into the local board (for rendering + accessors). Illegal moves raise the same `ChessError` types as local play. `refresh()` re-fetches state; `player_id` (if given) is asserted server-side; the client auto-sends its `version` for optimistic concurrency. `generation=N` loads a specific past game (read-only); `Game.archive(...)` lists all games between the triple. Re-opening a triple whose current game is **over** starts a rematch (a new generation).

Gameplay state is read through intention-revealing accessors on `Game`: `to_move` (Color), `is_over` (bool), `result` (GameStatus: `IN_PLAY`/`WHITE_WON`/`BLACK_WON`/`DRAW`), `winner` (Color|None), `termination` (Termination|None), `draw_offered_by` (Color|None). The public `Game.move()` returns a `MoveResult` (from/to/san, check, castle/promotion/en, + the new state); rendering is separate (`render()` / `save(path)`). Other engine methods: `resign(player_id)`, `legal_moves()`, `pgn()`, `fen` (property), `Game.from_fen(...)`. *(The base `engine.Game.move()` returns the bare engine `Move`; the public `remote.Game` deliberately overrides it to return the richer `MoveResult` — the two `# type: ignore` lines in `remote/game.py` mark that intentional divergence.)*

The three tiers and where they live:

1. **Client** (`src/chesssnake/remote/`) — `Game` + the challenge functions (`game.py`); `ApiClient` (`client.py`) is a thin `requests`-style wrapper (talks to the `/v1` routes, sends an optional `X-API-Key`). For **remote** games the client does **no** chess computation — it sends moves and mirrors the returned state. For **local** games `move`/`draw_*` call the base `engine.Game` in-process. `requests` is imported lazily (only on the remote path), so local games stay dependency-free.
2. **Server** (`src/chesssnake/api/server.py`) — a FastAPI app built by `create_app(settings)` that **owns the engine** (the authoritative rules). `/health` is unversioned/open; all game+challenge routes live on a `/v1` `APIRouter` gated by an API-key dependency built per-app from settings (`_api_key_dependency`, active only when `api.require_auth` is true). Mutating routes (`/moves`, `/resign`, `/draw/*`) load the row + its `Moves` history, build an `engine.Game` (via `serialize.game_from_state`), apply the action (which may raise `ChessError`), and persist the result — all inside one `apply_game_change` transaction; they accept an optional `player_id` (validated → `NotYourTurnError`/403) and `expected_version` (→ `VersionConflictError`/409). Read routes: `GET .../` (state), `.../legal-moves`, `.../history`, `.../pgn` (text), `.../fen` (text), `.../image` (PNG). Errors map to JSON `{error_type, detail}` (chess→400, auth→403, not-found→404, challenge/version→409, id→422, sql→500).
3. **Database** (`src/chesssnake/db/`) — SQLAlchemy Core, backend-agnostic. `db/operations.py` holds the query functions (`game_get_or_create`, `game_get`, `game_archive`, `game_history`, `apply_game_change`, `game_delete`, `current_games`, `game_exists`, `game_record`, `challenge*`) as Core expressions; `db/schema.py` the `MetaData`; `db/engine.py` the engine + `transaction()`/`locked_transaction()`; `db/postgres.py` and `db/sqlite.py` only what differs per dialect; `db/errors.py` the `GameError` types (`GameNotFoundError`, `NotYourTurnError`, `VersionConflictError`, …). The **`Games`** table stores the position as a single `Fen` column plus `Status`/`Draw`/`Termination`/`Version` (no more per-field board columns); the **`Moves`** table stores one row per ply (`San` + `PositionKey`, plus a ply-0 row for the initial position) for PGN and threefold detection. **This layer stays engine-free** — `apply_game_change` runs the caller's `mutate(row, history)` callback (the engine logic) between a locked read and the `UPDATE`, bumping `version` and appending `moves` rows atomically — see the locking note in the `db/` section below.

The wire payloads are defined once in `src/chesssnake/dto.py`: `GameState` (the position as **FEN** + `status`/`version`/`generation`/`draw`/`termination`/names) and `MoveResult` (a move + resulting state, incl. `san`) — stdlib dataclasses, so the client needs no pydantic. The FEN codec is `src/chesssnake/engine/fen.py` (`to_fen`/`from_fen`/`position_key`/`INITIAL_FEN`), and `src/chesssnake/serialize.py` bridges `GameState` ⇄ engine `Game` (`game_from_state` with history, `state_from_game`, `board_and_turn`). `src/chesssnake/cli.py` is the console-script entry point; `src/chesssnake/assets.py` (`asset_path`) centralizes packaged-data lookups.

When changing **gameplay** behavior, edit `engine` — every tier (local games and the server) inherits it. When changing **persistence or the wire protocol**, edit `db/postgres.py` (SQL) and/or `dto.py` (payloads) + `serialize.py` (bridge), and mirror the endpoint in `api/server.py` + the method in `remote/client.py`.

## Configuration (`src/chesssnake/config.py`)

Every setting is declared **once**, as a field on a section model in `config.py`. Defaults, types, help text, secret-ness, and the environment-variable name are all derived from that declaration — there is no second table to keep in sync. Adding a setting means adding one field.

- **Four layers**, later wins: built-in default → TOML config file → environment variable → explicit CLI override (`Override` objects passed to `resolve()`).
- **Env names are mechanical**: `CHESSSNAKE__{SECTION}__{KEY}`, e.g. `[api] port` ⇄ `CHESSSNAKE__API__PORT`. Derive them with `env_name(section, key)` — never hardcode one in `src/` without a test asserting it matches (see `remote/game.py`'s `API_URL_ENV` and `db/errors.py`'s `SQLAuthError`, both of which hardcode names precisely because their modules must not import `config`).
- **Provenance is tracked per key**: `resolve()` records which layer supplied each value, surfaced by `settings.source(section, key)` and printed by `chesssnake config show`. Keep it truthful — that is why `[client]` is rejected in config files (the client only reads env, so a file value would be reported but never used).
- Sections use `extra="forbid"`, so a typo'd key is a startup error, not a silently ignored line. Unknown `CHESSSNAKE__*` env vars warn.
- Env values arrive as strings and are coerced by pydantic's lax mode (`"8000"`→int, `"true"/"1"/"yes"/"on"`→bool). **Do not hand-roll parsing.**
- Pydantic lives in the **`api` extra**, so `config.py` must never be imported from the core/local-game path. `cli.py` imports it lazily and exits with an install hint. **`db/` must never import `config`** — it is also loaded by the `client` extra.
- Bootstrap vars `CHESSSNAKE_CONFIG` and `CHESSSNAKE_HOME` use a **single** underscore, so they can't collide with the `CHESSSNAKE__` setting prefix.
- Auth is explicit: `api.require_auth`. Enabling it without `api.api_key` is a validation error; setting a key *without* `require_auth` produces an advisory (`Settings.advisories()`), logged at startup and printed by `config show`.

Full reference: `docs/configuration.md`. The commented default file shipped by `chesssnake config init` is `src/chesssnake/data/chesssnake.toml` (registered under `[tool.setuptools.package-data]`); tests assert it stays valid and documents every schema field, so **add a documented block there whenever you add a setting**.

### `engine/` — the chess engine (no external deps beyond Pillow, for rendering)

`Chess.py` was split into focused modules; the package `__init__.py` re-exports the public names so `from chesssnake.engine import Board, Move, Square, Game, Color, PieceType, GameStatus, render_board` works.

- `enums.py` — `Color(IntEnum)` (WHITE=0/BLACK=1, with `.opponent`), `PieceType` (a plain `Enum`; `.value` is the letter code — never `str()` an enum member), `GameStatus(IntEnum)` (`IN_PLAY=0`/`WHITE_WON=1`/`BLACK_WON=2`/`DRAW=3`, with `.won_by(color)`), and `Termination(str, Enum)` (checkmate/resignation/stalemate/threefold/fifty_move/insufficient_material/agreement). A win is `WHITE_WON`/`BLACK_WON` (checkmate **or** resignation); the reason is the `Termination`.
- `pieces.py` — `Piece` and subclasses `Rook/Knight/Bishop/Queen/King/Pawn`. Movement uses `(di, dj)` direction-vector tables through shared `_slide`/`_step` scan helpers. Each piece implements `threatens`, `can_move`, `find_all(...) -> list[Square]` (never raises) and `find_one(...) -> Square` (resolves notation, raises on 0/ambiguous). Sliding pieces share `_pinned_move_allowed`.
- `square.py` — `Square(i, j, piece)`. **Coordinate system: `i` = row 0–7 from the top (i=0 is rank 8); `j` = file 0–7 (j=0 is file a). Piece color: `Color.WHITE`=0, `Color.BLACK`=1.**
- `fen.py` — the board serialization format (standard **FEN**, replacing the old bespoke string): `to_fen(board, turn)`, `from_fen(fen) -> (board, turn)`, `position_key(board, turn)` (first four FEN fields, for threefold), `INITIAL_FEN`.
- `board.py` — `Board`. `board[i, j]` returns the `Square` or `None` if off-board (load-bearing for scan loops). `board.lifted(square)` temporarily removes a piece (pin/mate analysis). `Board.move()` sets `status`/`termination` and updates `halfmove_clock`/`fullmove_number`; it detects checkmate, stalemate, `insufficient_material()`, and the fifty-move rule (threefold is applied by `Game.move`, which holds the position history). `Board.legal_moves(turn)` enumerates fully-legal moves. State is kept in FEN's own form: `board.en_passant` is the FEN en-passant target square as an algebraic string (e.g. `"e3"`, or `None`), and `board.castling` is the FEN castling-rights letters (subset of `"KQkq"`, `""` when none) — updated on each move and read directly by `King.can_castle`. These plus the clocks are the six FEN fields, surfaced on `Game` as `fen`/`to_move`/`castling_rights`/`en_passant`/`halfmove_clock`/`fullmove_number`.
- `san.py` — `to_san(board, prev, to, piece, ...)` builds a **postable** move string (chesssnake notation), used by `legal_moves`. PGN-style formatting (`O-O`, `=Q`) is applied at export in `game.pgn()`.
- `move.py` — the `Move` class parses/validates one algebraic move against a board.
- `notation.py` — `FILES`/`RANKS`, coord↔notation helpers, `is_valid_c_notation`, `matches_disambiguation`. `Board.get_coords`/`get_c_notation`/`Move.is_valid_c_notation` are facades delegating here.
- `image.py` — `render_board(board, white_name, black_name, move=None, perspective=None) -> PIL.Image`; composites cached piece PNGs, 68px tiles, last-move highlight. `perspective=None` → the wide both-orientations image (the bottom name strip is dropped when *both* names are empty); `perspective=Color.WHITE`/`BLACK` (or `"white"`/`"black"`) → a single board from that side (board only, via the shared `_render_side`).
- `errors.py` — gameplay exception hierarchy rooted at `ChessError`.
- `game.py` — the base `Game` controller that `remote/game.py`'s `Game` subclasses. Holds `turn` (Color), `draw` (Color|None), `move_history` (SAN, for PGN) and `position_history` (keys, for threefold). Methods: `move` (records SAN + threefold), `resign`, `draw_*`, `legal_moves`, `pgn`, `fen` (property), `from_fen` (classmethod).

### `remote/` — the client (tier 1)

- `game.py` — `Game(BaseGame)` (built via `Game.local()`/`Game.remote()`) plus module-level challenge functions. The low-level `Game.__init__(*args, client=None, player_id=None, version=None, **kwargs)` is internal — use the factories. For remote games, `move`/`resign`/`draw_*` call the client (sending `player_id` + the tracked `version`) and pass the returned state to `_apply_state` (rebuilds the mirror board via `serialize.board_and_turn` from the FEN, updates `version`); `last_move` is a lightweight `_MoveMarker` for render highlighting. `legal_moves`/`pgn`/`history` proxy to the server when remote, or run the local engine otherwise.
  - Games are keyed by the composite `(group_id, white_id, black_id)` — all BIGINTs. `POST /v1/games` upserts-then-selects.
- `client.py` — `ApiClient(base_url, session=None, api_key=None)`. Prefixes `/v1`, adds `X-API-Key` when set. `session` defaults to `requests.Session()` but can be **injected** (tests pass a FastAPI `TestClient`). `move()` → `dto.MoveResult`; `get_state`/`get_or_create_game`/`resign`/draw → `dto.GameState`; `legal_moves`/`history` → lists; `pgn`/`fen` → text; `image()` → PNG bytes. **Error mapping** covers both `engine.errors` and `db.errors`: `_build_error_registry` maps class name→class, and `_raise` reconstructs via `cls.__new__(cls); exc.args=(detail,)` so `except PromotionError`/`except VersionConflictError` work.

### `api/` — the server (tier 2, **owns the engine**)

- `server.py` — `create_app(settings)` builds the FastAPI app (settings on `app.state.settings`); a module-level PEP 562 `__getattr__` still resolves `chesssnake.api.server:app` lazily for ASGI import strings. `/health` is unversioned/open; `/v1` routes gated by the per-app api-key dependency. Mutating routes (`POST .../moves` `{move, player_id?, expected_version?}`, `POST .../resign`, `POST .../draw/{offer|accept|decline}` `{player_id, expected_version?}`) build an `engine.Game` from the stored row + `Moves` history and apply the action inside `apply_game_change` (one locked transaction). Read routes: `GET .../` (state), `.../archive` (all generations), `.../legal-moves`, `.../history`, `.../pgn` + `.../fen` (`PlainTextResponse`), `.../image` (PNG). Read routes take an optional `?generation=` (a past game; default = current); `/image` also takes `?perspective=white|black`. Group-level reads: `GET .../{g}/exists` and `GET .../{g}/record` (head-to-head win/draw/loss). Request bodies are pydantic; responses are `dto` dataclasses as dicts. Handlers: `ChessError`→400, `NotYourTurnError`→403, `GameNotFoundError`→404, `ChallengeError`/`VersionConflictError`→409, `SQLIdError`→422, `SQLError`→500, `GameError`→400. `lifespan` inits the pool from `settings.database` (schema init if `database.init_schema`); its `connection_pool is None` guard lets a second app share an existing pool, which is how the tests build an auth-requiring app alongside the open one.

### `db/` — the database layer (tier 3, **engine-free**)

Backend-agnostic SQLAlchemy Core. The `database.url` scheme picks the backend; there is no separate "which database" setting to drift.

- `__init__.py` — the common interface. Everything is lazy except `errors`, which `remote/client.py` imports for error mapping: the `client` extra installs neither SQLAlchemy nor psycopg2, so an eager import would break `pip install chesssnake[client]`.
- `schema.py` — the `MetaData` and the three `Table` definitions. **Every identifier is lowercase, deliberately**: the pre-0.9.0 `init.sql` used unquoted mixed case, which PostgreSQL folds to lowercase, and SQLAlchemy *quotes* anything not already lowercase — so `Column("GroupId", …)` would emit `games."GroupId"` and fail against every deployed database. Lowercase keeps it unquoted, keeps deployed databases working, and makes result-row keys lowercase on both backends (which is what `dto.GameState.from_row` expects). `create_all(checkfirst=True)` replaces the old script; it also leaves existing tables untouched, so a 0.8.0 database never gains a missing index.
- `engine.py` — `parse_url` (validates the scheme, rejects libpq keyword strings with the URL equivalent), `create_engine`/`initialize_engine`/`dispose_engine`, `transaction()`, and `locked_transaction()`. The process-wide engine handle lives here. `_engine_kwargs` is per-dialect: an in-memory SQLite database needs `StaticPool` and rejects pool sizing, a file one takes `QueuePool`, and PostgreSQL gets `pool_pre_ping`.
- `operations.py` — all fourteen query functions as Core expressions. Public functions open their own transaction; the `_`-prefixed variants take a connection so `challenge()` can run its check-and-mutate atomically. Still **no `engine` import** — the chess logic arrives as `apply_game_change`'s `mutate` callback.
- `postgres.py` / `sqlite.py` — only what genuinely differs: the locking strategy, the dialect's `insert()` for `ON CONFLICT`, and creating a database.
- `errors.py` — SQL/challenge exception hierarchy rooted at `GameError` (separate from the engine's `ChessError`; shared by client and server for error mapping).

**Locking is the thing to be careful about.** `apply_game_change` is a read-modify-write with the engine running in the middle. PostgreSQL serializes it with `SELECT … FOR UPDATE`; SQLite has no row locks, and **SQLAlchemy compiles `FOR UPDATE` away on SQLite silently rather than raising** — so a naive port looks correct and loses moves. SQLite instead takes the write lock as the transaction opens, via `BEGIN IMMEDIATE`, which is why write paths must use `locked_transaction()` and not `transaction()`. `require_write_transaction()` enforces that; `tests/integration/test_concurrency.py` proves it on both backends (and fails if the lock is removed).

## Conventions

- Docstrings are reStructuredText (`:param:`/`:type:`/`:raises:`) and thorough — match that style, and keep the `:raises:` lists accurate since they're the closest thing to a spec for `move()`.
- Piece movement is data-driven: `(di, dj)` direction-vector tables fed through the shared `_slide`/`_step` scan helpers in `pieces.py`. Add a piece or tweak movement by editing its direction table, not by unrolling per-direction blocks. (This replaces the engine's earlier hand-unrolled loops, which were consolidated in the Phase 2 refactor.)
- Enums are the source of truth for color/piece-type/status; convert to primitives (`int(color)`, `piecetype.value`) only at the serialization and rendering boundaries — never rely on `str()` of an enum member.