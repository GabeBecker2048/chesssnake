# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`chesssnake` is a PyPI library (`pip install chesssnake`) for playing, visualizing, and persisting chess games. It has a pure-Python chess engine, a PIL-based board renderer, and a **3-tier persistence architecture**: a `Game` client that runs the engine locally and syncs state over REST → a FastAPI **api-endpoint** (`chesssnake api-endpoint`) → SQLite or PostgreSQL. Many game clients can share one api-endpoint/database. Current version is 0.9.1 (pre-1.0; the REST api-endpoint shipped in 0.7.0, the configuration system in 0.8.0, SQLite/SQLAlchemy in 0.9.0, the `play` CLI in 0.9.1 — see `VersionHistory.md`).

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
uv sync --extra api --extra client --extra postgres   # full stack (dev + pg groups are default)

# Run anything inside the managed environment
uv run python examples/example.py        # core (no-DB) smoke example

# Run the api-endpoint server (needs the `api` extra + a configured database.url / docker compose Postgres)
uv run chesssnake api-endpoint --host 0.0.0.0 --port 8000 --init-db
uv run chesssnake init-db                # just create the schema, then exit
uv run chesssnake config init            # write a commented default config file
uv run chesssnake config show            # effective settings + where each came from

# Play at the terminal. --local needs nothing but the core install (no server, no
# requests); without it, --api-url / CHESSSNAKE__CLIENT__API_URL points at an endpoint.
uv run chesssnake play --local
uv run chesssnake play --api-url http://localhost:8000 --group 1 --white 10 --black 20 --me 10

# Tests. Both dependency groups install by default, so a bare `uv run pytest` covers
# both backends; CI's SQLite matrix opts out with --no-group pg (no pgserver wheels).
uv run pytest                            # everything under tests/
uv run pytest tests/unit                 # fast, pure-Python engine tests (no DB; incl. the play session + text board)
uv run pytest tests/integration          # API + remote-Game stack, run against BOTH backends:
                                         # a temp SQLite file and a throwaway Postgres (pgserver)
CHESSSNAKE_TEST_BACKENDS=sqlite uv run pytest tests/integration   # SQLite only (no pgserver needed)
uv run pytest tests/config               # config + CLI; needs pydantic but no database
uv run pytest tests/unit/test_rules.py::test_en_passant_capture  # a single test

# Add/remove dependencies (edits pyproject.toml + uv.lock)
uv add <pkg>
uv add --group dev <pkg>                 # add a dev/test dependency
uv add --optional api <pkg>              # add to the `api` extra

# Build the distributable (what the release workflow publishes)
uv build

# Bring up a local Postgres for the api-endpoint to talk to (create the schema with
# `chesssnake init-db`). Exposes Postgres on host port 5433.
docker compose up

# Run the whole stack in containers (image built from docker/build/Dockerfile).
# One image serves both; the backend is chosen at runtime by database.url.
docker compose -f docker/compose.sqlite.yaml up --build     # single container, no DB server
docker compose -f docker/compose.postgres.yaml up --build   # api-endpoint + PostgreSQL
./docker/smoke-test.sh                                      # build + play a game against each
```

Package data (`data/*.sql`, `data/*.ttf`, `data/img/*.png`) is declared under `[tool.setuptools.package-data]` in `pyproject.toml` and accessed at runtime via `chesssnake.assets.asset_path("img/template.png")` (a thin wrapper over `importlib.resources`). If you add runtime assets, register them there or they won't ship in the wheel. `uv.lock` is committed and should be kept in sync (`uv lock`).

## Releasing

Publishing a **GitHub release** publishes the same version to PyPI, via
`.github/workflows/release.yml`. Full runbook: `docs/releasing.md`.

- The version in `pyproject.toml` is the source of truth; the tag only has to agree
  with it (`v0.9.1` or `0.9.1`). The workflow's first job fails on a mismatch, before
  anything is built — tagging a version the project does not claim would otherwise be
  rejected by PyPI as a duplicate, or publish something unintended.
- Upload uses **PyPI Trusted Publishing** (OIDC), not an API token, so there is no
  secret in the repo. It requires the `pypi` environment named in the workflow to match
  the publisher configured on PyPI.
- The workflow re-runs lint, mypy and the full suite before building, then **installs
  the built wheel into a clean venv** and renders a board from it. That step exists to
  catch a missing `[tool.setuptools.package-data]` entry, which the test suite cannot
  see because it runs against the source tree — add a runtime asset without
  registering it there and only this would notice.
- **PyPI is currently on 0.6.6**, which predates the api-endpoint. 0.7.0–0.9.0 are
  marked Released in `VersionHistory.md` but were never uploaded, so `pip install
  chesssnake` does not get any of what the README documents.

## Three-tier architecture

The public exports are `Game`, the challenge helpers (`challenge`, `challenge_exists`, `delete_challenge`), the head-to-head `record` helper, and the enums (`Color`, `GameStatus`, `PieceType`, `Termination`) — see `src/chesssnake/__init__.py`. `Game` is an `engine.Game` subclass built via **factory methods** (not a flag-laden constructor):

- `Game.local(white_name=..., black_name=...)` — pure in-memory game. No network, no `requests`/psycopg2 imported. The engine runs in-process; it has the **full rules** (draw-by-rule, resign, legal-move listing, FEN/PGN) so a local game behaves identically to a remote one.
- `Game.remote(white_id, black_id, group_id=..., player_id=..., generation=..., api_url=..., api_key=..., client=...)` — a game persisted through the api-endpoint. **The server runs the engine**: `move`/`draw_*`/`resign` send a request, and the returned state is mirrored into the local board (for rendering + accessors). Illegal moves raise the same `ChessError` types as local play. `refresh()` re-fetches state; `player_id` (if given) is asserted server-side; the client auto-sends its `version` for optimistic concurrency. `generation=N` loads a specific past game (read-only); `Game.archive(...)` lists all games between the triple. Re-opening a triple whose current game is **over** starts a rematch (a new generation).

Gameplay state is read through intention-revealing accessors on `Game`: `to_move` (Color), `is_over` (bool), `result` (GameStatus: `IN_PLAY`/`WHITE_WON`/`BLACK_WON`/`DRAW`), `winner` (Color|None), `termination` (Termination|None), `draw_offered_by` (Color|None). The public `Game.move()` returns a `MoveResult` (from/to/san, check, castle/promotion/en, + the new state); rendering is separate (`render()` / `save(path)`). Other engine methods: `resign(player_id)`, `legal_moves()`, `pgn()`, `fen` (property), `Game.from_fen(...)`. *(The base `engine.Game.move()` returns the bare engine `Move`; the public `remote.Game` deliberately overrides it to return the richer `MoveResult` — the two `# type: ignore` lines in `remote/game.py` mark that intentional divergence.)*

The three tiers and where they live:

1. **Client** (`src/chesssnake/remote/`) — `Game` + the challenge functions (`game.py`); `ApiClient` (`client.py`) is a thin `requests`-style wrapper (talks to the `/v1` routes, sends an optional `X-API-Key`). For **remote** games the client does **no** chess computation — it sends moves and mirrors the returned state. For **local** games `move`/`draw_*` call the base `engine.Game` in-process. `requests` is imported lazily (only on the remote path), so local games stay dependency-free.
2. **Server** (`src/chesssnake/api/server.py`) — a FastAPI app built by `create_app(settings)` that **owns the engine** (the authoritative rules). `/health` is unversioned/open; all game+challenge routes live on a `/v1` `APIRouter` gated by an API-key dependency built per-app from settings (`_api_key_dependency`, active only when `api.require_auth` is true). Mutating routes (`/moves`, `/resign`, `/draw/*`) load the row + its `Moves` history, build an `engine.Game` (via `serialize.game_from_state`), apply the action (which may raise `ChessError`), and persist the result — all inside one `apply_game_change` transaction; they accept an optional `player_id` (validated → `NotYourTurnError`/403) and `expected_version` (→ `VersionConflictError`/409). Read routes: `GET .../` (state), `.../legal-moves`, `.../history`, `.../pgn` (text), `.../fen` (text), `.../image` (PNG). Errors map to JSON `{error_type, detail}` (chess→400, auth→403, not-found→404, challenge/version→409, id→422, sql→500).
3. **Database** (`src/chesssnake/db/`) — SQLAlchemy Core, backend-agnostic. `db/operations.py` holds the query functions (`game_get_or_create`, `game_get`, `game_archive`, `game_history`, `apply_game_change`, `game_delete`, `current_games`, `game_exists`, `game_record`, `challenge*`) as Core expressions; `db/schema.py` the `MetaData`; `db/engine.py` the engine + `transaction()`/`locked_transaction()`; `db/postgres.py` and `db/sqlite.py` only what differs per dialect; `db/errors.py` the `GameError` types (`GameNotFoundError`, `NotYourTurnError`, `VersionConflictError`, …). The **`Games`** table stores the position as a single `Fen` column plus `Status`/`Draw`/`Termination`/`Version` (no more per-field board columns); the **`Moves`** table stores one row per ply (`San` + `PositionKey`, plus a ply-0 row for the initial position) for PGN and threefold detection. **This layer stays engine-free** — `apply_game_change` runs the caller's `mutate(row, history)` callback (the engine logic) between a locked read and the `UPDATE`, bumping `version` and appending `moves` rows atomically — see the locking note in the `db/` section below.

There are **three ways to drive the backend**, all hitting the same `/v1` routes and
the same rules: direct REST calls (any language, a custom frontend), the Python client
(`Game.remote(...)`), and the terminal client (`chesssnake play`). The CLI is built *on*
the client, not beside it — see `play.py` below — so adding a gameplay feature to
`engine` reaches all three without touching any of them.

The wire payloads are defined once in `src/chesssnake/dto.py`: `GameState` (the position as **FEN** + `status`/`version`/`generation`/`draw`/`termination`/names) and `MoveResult` (a move + resulting state, incl. `san`) — stdlib dataclasses, so the client needs no pydantic. The FEN codec is `src/chesssnake/engine/fen.py` (`to_fen`/`from_fen`/`position_key`/`INITIAL_FEN`), and `src/chesssnake/serialize.py` bridges `GameState` ⇄ engine `Game` (`game_from_state` with history, `state_from_game`, `board_and_turn`). `src/chesssnake/cli.py` is the console-script entry point; `src/chesssnake/play.py` holds the `chesssnake play` session loop (see below); `src/chesssnake/assets.py` (`asset_path`) centralizes packaged-data lookups.

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
- `text.py` — `render_text(board, perspective=None, *, figurines=True, coordinates=True, color=False, move=None) -> str`; the **sibling of `image.py`**, same job in text. Has **no dependencies at all**, not even Pillow, which is what lets `chesssnake play --local` work from a core install. `perspective=None` means white's view (there is no sensible side-by-side text form, unlike `render_board`). `color=False` emits **no escape sequence at all**, so output pipes and diffs cleanly — keep it that way, the tests compare plain strings. The last-move highlight only applies when `color` is on.
- `errors.py` — gameplay exception hierarchy rooted at `ChessError`.
- `game.py` — the base `Game` controller that `remote/game.py`'s `Game` subclasses. Holds `turn` (Color), `draw` (Color|None), `move_history` (SAN, for PGN) and `position_history` (keys, for threefold). Methods: `move` (records SAN + threefold), `resign`, `draw_*`, `legal_moves`, `pgn`, `fen` (property), `from_fen` (classmethod).

### `remote/` — the client (tier 1)

- `game.py` — `Game(BaseGame)` (built via `Game.local()`/`Game.remote()`) plus module-level challenge functions. The low-level `Game.__init__(*args, client=None, player_id=None, version=None, **kwargs)` is internal — use the factories. For remote games, `move`/`resign`/`draw_*` call the client (sending `player_id` + the tracked `version`) and pass the returned state to `_apply_state` (rebuilds the mirror board via `serialize.board_and_turn` from the FEN, updates `version`); `last_move` is a lightweight `_MoveMarker` for render highlighting. `legal_moves`/`pgn`/`history` proxy to the server when remote, or run the local engine otherwise.
  - Games are keyed by the composite `(group_id, white_id, black_id)` — all BIGINTs. `POST /v1/games` upserts-then-selects.
- `client.py` — `ApiClient(base_url, session=None, api_key=None)`. Prefixes `/v1`, adds `X-API-Key` when set. `session` defaults to `requests.Session()` but can be **injected** (tests pass a FastAPI `TestClient`). `move()` → `dto.MoveResult`; `get_state`/`get_or_create_game`/`resign`/draw → `dto.GameState`; `legal_moves`/`history` → lists; `pgn`/`fen` → text; `image()` → PNG bytes. **Error mapping** covers both `engine.errors` and `db.errors`: `_build_error_registry` maps class name→class, and `_raise` reconstructs via `cls.__new__(cls); exc.args=(detail,)` so `except PromotionError`/`except VersionConflictError` work.

### `play.py` — the terminal client (`chesssnake play`)

The interactive session: a board, a prompt, and a command table. It is the **third
way to drive the backend**, and it is built *on* `remote.Game` rather than beside it —
`Session` talks only to a `Game` and never to HTTP, which is why **one loop plays both
a local and a remote game**. Anything it does, the client could already do.

- **`Session` takes its two streams as arguments** (`stdin=`, `stdout=`), which is the
  whole reason this is not inside `cli.py`: `tests/unit/test_play.py` drives the real
  loop against a real `Game.local()` with `io.StringIO`, so there is **no terminal, no
  server and no subprocess** in those tests. Keep that property — do not reach for
  `print()` or `input()` in here.
- **Unknown input is a move.** `dispatch()` looks the first word up in `DISPATCH` and
  otherwise hands the whole line to `game.move()`. That is why every command is a
  lowercase word that cannot collide with algebraic notation.
- **`actor()` decides whose action it is.** With `--me` it is always that player.
  Without it, the default is *whoever is to move* — one person at one keyboard playing
  both sides — except for `accept`/`decline`, which default to the **opponent of the
  offerer**, since the side to move may well be the player who offered.
- **`--me` turn-order enforcement is asymmetric, on purpose.** For a **remote** game the
  server checks it and is the authority, so the session must not duplicate the rule. For
  a **local** game there is no server to ask and `engine.Game.move()` takes no player id,
  so `dispatch()` checks `is_players_turn` itself and raises `NotYourTurnError` —
  otherwise `--me` would silently mean nothing offline.
- **`sync()` runs before every informational command** (`board`, `fen`, `moves`, `pgn`),
  and this is load-bearing rather than belt-and-braces: `legal_moves`/`pgn`/`history` are
  **proxied to the server** while the board and `fen` come from the local mirror, so
  without it the two disagree the moment the opponent moves — `moves` would list the
  legal moves of a position not on screen. It returns whether the version actually moved
  on, so the caller can redraw and say so instead of silently changing the board. There
  is still **no polling**: nothing arrives while the prompt sits idle.
- **`allow_action()` gates every action, and the refusal is load-bearing.** The server's
  **mutating routes ignore `generation`** and always act on the *current* game, while
  reads are pinned to one (`GET .../?generation=`). So a session left on a superseded
  generation does not get a clean refusal — its move is applied to whichever game is
  current, and only an accidental version or legality mismatch stops it. Verified against
  a live endpoint: a session sitting in a finished generation 1 played `d5` and it landed
  in generation 2's movetext. `sync()` therefore reads the **current** generation, sets
  `stale_generation` on drift, and `allow_action()` refuses until the player types `new`.
  **The real fix is server-side** (have the mutating routes take and validate a
  generation); until then this guard is the only thing preventing it from the CLI.
- **`wait_for_line()` is the one thing the session does unasked**, polling every
  `--refresh` seconds (default 10, `0` disables; one poll is a single small GET, measured
  at ~25 ms against a LAN deployment, so the interval is a feel decision not a load one). `select` rather than a thread, so one
  thread touches the game and the output stream and there is nothing to shut down. It
  falls back to a blocking read for a local game, `--refresh 0`, a stdin with no real fd
  (a `StringIO`, as the tests use), or a platform whose `select` will not take one. A
  quiet poll prints nothing; a change redraws and re-issues the prompt.
- **Ctrl+C is an exit, not a crash.** `run()` catches `KeyboardInterrupt` around both the
  read and the dispatch and returns **130**; `cli.py`'s `main()` catches it around every
  subcommand as well. Without this it propagated out of `select()` and printed a traceback
  through the console script, which tells the player nothing. Verified by sending a real
  SIGINT to a pty-backed `chesssnake play`.
- **Errors are normal input.** `ChessError`, `GameError` and `ValueError` are caught per
  line and printed; only a failure to *reach* the endpoint escapes, and `cli.py` turns
  that into an exit with the URL in the message rather than a prompt that cannot work.
- The game-over note fires **on the transition only** (`was_over` vs `is_over`); printing
  it after every command turned the one line that matters into noise.
- `cli.py`'s `_run_play` deliberately **never imports `config`**: a local game needs only
  the core install, and a remote one needs only a URL, which `Game.remote` already reads
  from `CHESSSNAKE__CLIENT__API_URL`. It hardcodes that variable name (argparse needs it
  at parser-build time, and importing `remote` would pull Pillow into every
  `config show`), with `test_play.py::test_cli_env_name_matches_the_client` keeping the
  copy honest — the same pattern as `remote/game.py` and `db/errors.py`.

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