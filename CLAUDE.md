# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`chesssnake` is a PyPI library (`pip install chesssnake`) for playing, visualizing, and persisting chess games. It has a pure-Python chess engine, a PIL-based board renderer, and a **3-tier persistence architecture**: a `Game` client that runs the engine locally and syncs state over REST → a FastAPI **api-endpoint** (`chesssnake api-endpoint`) → SQLite or PostgreSQL. Many game clients can share one api-endpoint/database. Current version is 0.11.0 (pre-1.0; the REST api-endpoint shipped in 0.7.0, the configuration system in 0.8.0, SQLite/SQLAlchemy in 0.9.0, the `play` CLI in 0.9.1, published container images in 0.9.2, the threadpool in 0.10.0, users and the redesigned schema in 0.11.0 — see `CHANGELOG.md`, with what is next in `ROADMAP.md`).

The package uses a **`src/` layout**: all importable code lives under `src/chesssnake/` (tests import the installed package, not a repo-root package).

## Commands

The project is managed with **uv**; all metadata lives in `pyproject.toml` (there is no `setup.py` or `requirements.txt`). The build backend is setuptools. Development is manual:

```bash
# Create/refresh the venv. Extras: `client` (requests, for remote games),
# `api` (fastapi + uvicorn + pydantic + sqlalchemy — runs on SQLite with no
# compiled deps), `postgres` (psycopg2, only for postgresql:// URLs).
# `.python-version` pins local dev to 3.12 because the `pg` test group's
# `pgserver` only ships cp311/cp312 wheels; the package itself supports 3.12-3.14
# and the SQLite tests run on all of them.
uv sync                                  # core only (local, in-memory games)
uv sync --extra api --extra client --extra postgres   # full stack (dev + pg groups are default)

# Run anything inside the managed environment
uv run python examples/example.py        # core (no-DB) smoke example

# Run the api-endpoint server (needs the `api` extra + a configured database.url / docker compose Postgres)
uv run chesssnake api-endpoint --host 0.0.0.0 --port 8000 --init-db
uv run chesssnake init-db                # just create the schema, then exit
uv run chesssnake init-db --drop         # drop every table first (pre-1.0 schema changes)
uv run chesssnake user create alice --admin   # accounts, straight in the database (also show/set-role/rename/link)
uv run chesssnake config init            # write a commented default config file
uv run chesssnake config show            # effective settings + where each came from

# Play at the terminal. --local needs nothing but the core install (no server, no
# requests); without it, --api-url / CHESSSNAKE__CLIENT__API_URL points at an endpoint.
uv run chesssnake play --local
uv run chesssnake play --api-url http://localhost:8000 --white alice --black bob --me alice

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

## Writing the changelog

`CHANGELOG.md` is the release notes: `scripts/release.sh` and the release workflow
both read the `## X.Y.Z` section out of it, so a version with no section fails the
release before anything is published. Every version gets an entry, in one format.

- **Keep a Changelog sections**, in this order, and only the ones that apply:
  `### Added`, `### Changed`, `### Deprecated`, `### Removed`, `### Fixed`,
  `### Security`. The heading is `## X.Y.Z - YYYY-MM-DD` with a hyphen.
- **Bullets, never paragraphs.** One change per bullet, one or two sentences.
  Wrap the text, do not stack several changes into one bullet.
- **Summary level.** Say what changed and why it matters to someone using the
  thing. Module names, call signatures and the reasoning behind a decision
  belong in the commit message, not here. Roughly one to six bullets per
  version; more than that usually means several bullets are really one.
- **Comparable depth.** Entries should look like siblings. "Major PostgreSQL
  changes." is too thin and a four-paragraph migration note is too much; both
  existed before 0.9.2 and both were rewritten.
- **No `**Breaking.**` marker.** Breaking changes are ordinary bullets under
  `### Changed` or `### Removed`; the note at the top of the file already says
  pre-1.0 minors may break. Dropping a Python version is a `### Removed` bullet.
- **No em-dashes** here or in any user-facing document (README, CHANGELOG,
  ROADMAP, everything under `docs/`). Use a colon, comma, semicolon or full
  stop. `CLAUDE.md` is exempt, being internal.
- `ROADMAP.md` holds planned versions in the same shape and is **hand-edited by
  Gabe**: do not rewrite its entries.

## Releasing

Pushing a tag `vX.Y.Z` releases that version: `.github/workflows/release.yml` builds
it, publishes the package to PyPI and the container image to
`ghcr.io/gabebecker2048/chesssnake`, then creates the GitHub release. Full runbook:
`docs/releasing.md`; cut one with `./scripts/release.sh X.Y.Z`.

- The version in `pyproject.toml` is the source of truth, and `CHANGELOG.md` must have
  a `## X.Y.Z` section — that section *is* the release notes, so a missing one fails
  the run before anything is published. `release.sh` checks both locally first.
- Upload uses **PyPI Trusted Publishing** (OIDC) and the automatic `GITHUB_TOKEN` for
  the registry, so there is no secret in the repo. The PyPI publisher is scoped to the
  `pypi` environment named in the workflow.
- The workflow **installs the built wheel into a clean venv** and renders a board from
  it. That exists to catch a missing `[tool.setuptools.package-data]` entry, which the
  test suite cannot see because it runs against the source tree — add a runtime asset
  without registering it there and only this would notice.
- The GitHub release is created **last**, after both registries have the version, so a
  release page never exists for something that was not published.
- The tag's date matters: GitHub derives a release's `created_at` from it and orders
  the releases page by it, which is why `release.sh` dates the tag to the commit.
- **Breaking changes are fine before 1.0.0, and there are no database migrations**
  (Gabe, 2026-11-03). A schema change in a pre-1.0 version drops and recreates; do
  not plan, propose or build migration tooling for one. Gabe is currently the only
  deployment. This changes at 1.0.0, which is the release that promises stability.

## Three-tier architecture

The public exports are `Game`, the challenge helpers (`challenge`, `challenge_exists`, `delete_challenge`), the head-to-head `record` helper, the user helpers (`create_user`, `get_user`, `user_for_identity`), the payloads (`GameState`, `MoveResult`, `User`), and the enums (`Color`, `GameStatus`, `PieceType`, `Termination`) — see `src/chesssnake/__init__.py`. `Game` is an `engine.Game` subclass built via **factory methods** (not a flag-laden constructor):

- `Game.local(white_name=..., black_name=...)` — pure in-memory game. No network, no `requests`/psycopg2 imported. The engine runs in-process; it has the **full rules** (draw-by-rule, resign, legal-move listing, FEN/PGN) so a local game behaves identically to a remote one.
- `Game.remote(white, black, group_id=..., player_id=..., generation=..., api_url=..., api_key=..., client=...)` — a game persisted through the api-endpoint, between two **users** given as ids or usernames (`_resolve_id`; usernames can never be all digits, which is what keeps that unambiguous). Names come only from the accounts: there are no name arguments. **The server runs the engine**: `move`/`draw_*`/`resign` send a request, and the returned state is mirrored into the local board (for rendering + accessors). Illegal moves raise the same `ChessError` types as local play. `refresh()` re-fetches state; `player_id` (if given) is asserted server-side; the client auto-sends its `version` and `generation` with every action. `game.id` is the server's game id. `generation=N` loads a specific past game (read-only); `Game.archive(...)` lists all games between the triple. Re-opening a triple whose current game is **over** starts a rematch (a new generation).

Gameplay state is read through intention-revealing accessors on `Game`: `to_move` (Color), `is_over` (bool), `result` (GameStatus: `IN_PLAY`/`WHITE_WON`/`BLACK_WON`/`DRAW`), `winner` (Color|None), `termination` (Termination|None), `draw_offered_by` (Color|None). The public `Game.move()` returns a `MoveResult` (from/to/san, check, castle/promotion/en, + the new state); rendering is separate (`render()` / `save(path)`). Other engine methods: `resign(player_id)`, `legal_moves()`, `pgn()`, `fen` (property), `Game.from_fen(...)`. *(The base `engine.Game.move()` returns the bare engine `Move`; the public `remote.Game` deliberately overrides it to return the richer `MoveResult` — the two `# type: ignore` lines in `remote/game.py` mark that intentional divergence.)*

The three tiers and where they live:

1. **Client** (`src/chesssnake/remote/`) — `Game` + the challenge functions (`game.py`); `ApiClient` (`client.py`) is a thin `requests`-style wrapper (talks to the `/v1` routes, sends an optional `X-API-Key`). For **remote** games the client does **no** chess computation — it sends moves and mirrors the returned state. For **local** games `move`/`draw_*` call the base `engine.Game` in-process. `requests` is imported lazily (only on the remote path), so local games stay dependency-free.
2. **Server** (`src/chesssnake/api/server.py`) — a FastAPI app built by `create_app(settings)` that **owns the engine** (the authoritative rules). `/health` is unversioned/open; all game+challenge routes live on a `/v1` `APIRouter` gated by an API-key dependency built per-app from settings (`_api_key_dependency`, active only when `api.require_auth` is true). Mutating routes (`/moves`, `/resign`, `/draw/*`) load the row + its `moves` history, build an `engine.Game` (via `serialize.game_from_state`), apply the action (which may raise `ChessError`), and persist the result — all inside one `apply_game_change` transaction; they accept an optional `player_id` (validated → `NotYourTurnError`/403), `expected_version` (→ `VersionConflictError`/409) and `generation` (→ `GenerationConflictError`/409). User routes create and look up accounts and their external-id links. Read routes: `GET .../` (state), `GET /v1/games/{id}`, `.../legal-moves`, `.../history`, `.../pgn` (text), `.../fen` (text), `.../image` (PNG). Errors map to JSON `{error_type, detail}` (chess→400, auth→403, not-found→404, challenge/version/user-exists→409, id/username→422, sql→500).
3. **Database** (`src/chesssnake/db/`) — SQLAlchemy Core, backend-agnostic. `db/operations.py` holds the query functions (`game_get_or_create`, `game_get`, `game_archive`, `game_history`, `apply_game_change`, `game_delete`, `current_games`, `game_exists`, `game_record`, `challenge*`) as Core expressions; `db/schema.py` the `MetaData`; `db/engine.py` the engine + `transaction()`/`locked_transaction()`; `db/postgres.py` and `db/sqlite.py` only what differs per dialect; `db/errors.py` the `GameError` types (`GameNotFoundError`, `NotYourTurnError`, `VersionConflictError`, …). The schema (six tables) is described under `db/` below: `users` own identity, `games` holds only games **in progress** (position as one FEN column), `moves` one row per played ply of those, and a game that ends is moved in the same transaction to `finished_games` with its moves collapsed to one `movetext` string. **This layer stays engine-free** — `apply_game_change` runs the caller's `mutate(row, history, now)` callback (the engine logic) between a locked read and the write, and persists the returned `GameChange` — see the locking note in the `db/` section below.

There are **three ways to drive the backend**, all hitting the same `/v1` routes and
the same rules: direct REST calls (any language, a custom frontend), the Python client
(`Game.remote(...)`), and the terminal client (`chesssnake play`). The CLI is built *on*
the client, not beside it — see `play.py` below — so adding a gameplay feature to
`engine` reaches all three without touching any of them.

The wire payloads are defined once in `src/chesssnake/dto.py`: `GameState` (the position as **FEN** + `status`/`version`/`generation`/`draw`/`termination` + `id`/`group_id`/`white_id`/`black_id`/`white_name`/`black_name`/`started_at`/`updated_at`), `MoveResult` (a move + resulting state, incl. `san`) and `User` — stdlib dataclasses, so the client needs no pydantic. Clients build them with `from_dict`, which **ignores unknown keys**, so adding a response field is never breaking; keep it that way. The FEN codec is `src/chesssnake/engine/fen.py` (`to_fen`/`from_fen`/`position_key`/`INITIAL_FEN`), and `src/chesssnake/serialize.py` bridges `GameState` ⇄ engine `Game` (`game_from_state` with history, `state_from_game`, `board_and_turn`). `src/chesssnake/cli.py` is the console-script entry point; `src/chesssnake/play.py` holds the `chesssnake play` session loop (see below); `src/chesssnake/assets.py` (`asset_path`) centralizes packaged-data lookups.

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

- `game.py` — `Game(BaseGame)` (built via `Game.local()`/`Game.remote()`) plus module-level challenge functions. The low-level `Game.__init__(*args, client=None, player_id=None, version=None, generation=None, game_id=None, **kwargs)` is internal — use the factories. For remote games, `move`/`resign`/`draw_*` call the client (sending `player_id` + the tracked `version` and `generation`) and pass the returned state to `_apply_state` (rebuilds the mirror board via `serialize.board_and_turn` from the FEN, updates `version`); `last_move` is a lightweight `_MoveMarker` for render highlighting. `legal_moves`/`pgn`/`history` proxy to the server when remote, or run the local engine otherwise.
  - A game is addressed by its id or by the triple `(group_id, white_id, black_id)` (user ids; `group_id` is a free namespace). `POST /v1/games` upserts-then-selects.
  - Module helpers `create_user`, `get_user`, `user_for_identity` (get-or-create by an external id, the call a bot makes), and the challenge/record helpers, all accept ids or usernames.
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
- **`allow_action()` gates every action.** Before 0.11.0 the server's mutating routes
  ignored `generation`, so a session left on a superseded generation had its move
  applied to the rematch (verified live: a session in a finished generation 1 played
  `d5` and it landed in generation 2's movetext). Since 0.11.0 every action carries the
  game's `generation` and the server refuses a stale one (`GenerationConflictError`),
  so this guard is no longer the only protection. It stays because it explains *why*
  and names the way out: `sync()` reads the **current** generation, sets
  `stale_generation` on drift, and `allow_action()` refuses until the player types `new`.
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

**Every `/v1` route is a plain `def`, deliberately.** The bodies are blocking:
synchronous SQLAlchemy, engine computation, PIL rendering. FastAPI only dispatches a
route to its worker threadpool when it is `def`; an `async def` route runs on the event
loop and blocks every other request for its whole duration. They were all `async def`
with no `await` anywhere until 0.10.0, so the server handled one request at a time.
`tests/integration/test_threadpool.py` fails if one goes back.

**`/health` is the one `async def` route, also deliberately.** It touches nothing, so
leaving it on the loop means it answers immediately while every worker thread is busy,
which is what keeps the container's two-second healthcheck honest under load. Note the
asymmetry this buys: `/health` is a *liveness* probe and after this change it cannot
report a wedged threadpool. That is the intended trade; a readiness probe would be a
separate feature. `require_api_key`, the exception handlers and `lifespan` stay async
too, since they do no blocking work and keeping auth on the loop avoids spending a
thread per request to compare a header.

Anything that runs in a worker thread must not assume request-scoped context survives a
further thread hop: `WRITE_TRANSACTION` (`db/engine.py`) is a `ContextVar`, and anyio
copies the context into the worker, so it is correct today precisely because nothing
inside `apply_game_change` offloads to another thread. If anything ever does, SQLite
silently falls back to a deferred `BEGIN` with no error, which is the bug class above.

- `server.py` — `create_app(settings)` builds the FastAPI app (settings on `app.state.settings`); a module-level PEP 562 `__getattr__` still resolves `chesssnake.api.server:app` lazily for ASGI import strings. `/health` is unversioned/open; `/v1` routes gated by the per-app api-key dependency. **29 routes in all**, pinned by `test_threadpool.py`. User routes: `POST /v1/users`, `GET /v1/users?username=`, `GET`/`PATCH /v1/users/{id}`, `GET`/`POST /v1/users/{provider}/{external_id}` (lookup / get-or-create), `PUT /v1/users/{id}/identities/{provider}/{external_id}` (link). Mutating routes (`POST .../moves` `{move, player_id?, expected_version?, generation?}`, `POST .../resign`, `POST .../draw/{offer|accept|decline}` `{player_id, expected_version?, generation?}`) build an `engine.Game` from the stored row + `moves` history and apply the action inside `apply_game_change` (one locked transaction); `_load_game` prepends the starting position's key to the history, since it is not stored. `_change` turns the engine game into a `GameChange`, setting `outcome` when the game is over, which is what moves it to the archive. Read routes: `GET .../` (state), `.../archive` (all generations), `.../legal-moves`, `.../history`, `.../pgn` + `.../fen` (`PlainTextResponse`), `.../image` (PNG). Read routes take an optional `?generation=` (a past game; default = the game in progress, else the last one played); `GET /v1/games/{id}` reads one by id; `/image` also takes `?perspective=white|black`. Group-level reads: `GET .../{g}/exists` and `GET .../{g}/record` (head-to-head win/draw/loss). Request bodies are pydantic; responses are `dto` dataclasses as dicts. Handlers: `ChessError`→400, `NotYourTurnError`→403, `GameNotFoundError`/`UserNotFoundError`→404, `ChallengeError`/`VersionConflictError`/`GenerationConflictError`/`UserExistsError`→409, `SQLIdError`/`UserValidationError`→422, `SQLError`→500, `GameError`→400. `lifespan` inits the pool from `settings.database` (schema init if `database.init_schema`); its `current_engine() is None` guard lets a second app share an existing pool, which is how the tests build an auth-requiring app alongside the open one.

### `db/` — the database layer (tier 3, **engine-free**)

Backend-agnostic SQLAlchemy Core. The `database.url` scheme picks the backend; there is no separate "which database" setting to drift.

- `__init__.py` — the common interface. Everything is lazy except `errors`, which `remote/client.py` imports for error mapping: the `client` extra installs neither SQLAlchemy nor psycopg2, so an eager import would break `pip install chesssnake[client]`.
- `schema.py` — the `MetaData` and six tables, in dependency order in `TABLES` (tests delete in reverse): `users` (server-assigned id, `username` unique on `lower(username)`, `role` 0/1, `password_hash`/`disabled_at` reserved for 0.12.0 auth), `user_identities` (PK `(provider, external_id)` → `user_id`: external ids such as Discord ids map onto users here, never by choosing user ids), `games` (in progress only; unique `(group_id, white_id, black_id)`; FEN, `draw`, `version`, `generation`), `moves` (`(game_id, ply)`, no ply-0 row), `finished_games` (the archive: same `id`, `status`/`termination`, `movetext`, final `fen`), `challenges`. **Every identifier is lowercase**: SQLAlchemy quotes anything else, and lowercase is the one spelling that is unquoted on both backends and gives identical result-row keys. Load-bearing details, each pinned by `tests/config/test_schema.py`:
  - **Assigned ids must render as exactly `INTEGER PRIMARY KEY AUTOINCREMENT` on SQLite** (`BigInteger().with_variant(Integer, "sqlite")` + `sqlite_autoincrement=True`; `Identity()` on PostgreSQL). BIGINT is not a rowid alias, and without AUTOINCREMENT SQLite reuses the highest id once that row is deleted, which archiving does, so a new game would collide with an archived one.
  - **No server-side timestamp defaults.** The ops layer writes every timestamp as UTC (`_utcnow`) and normalises reads (`_as_utc`): SQLite strips the offset rather than converting, so binding a non-UTC aware datetime would store the wrong instant silently.
  - `create_all(checkfirst=True)` never alters existing tables. Pre-1.0 a schema change is applied with `chesssnake init-db --drop` (`schema.drop_all`), not a migration.
- `engine.py` — `parse_url` (validates the scheme, rejects libpq keyword strings with the URL equivalent), `create_engine`/`initialize_engine`/`dispose_engine`, `transaction()`, and `locked_transaction()`. The process-wide engine handle lives here. `_engine_kwargs` is per-dialect: an in-memory SQLite database needs `StaticPool` and rejects pool sizing, a file one takes `QueuePool`, and PostgreSQL gets `pool_pre_ping`.
- `operations.py` — the query functions as Core expressions: users (`user_create`, `user_get`, `user_get_by_name`, `user_rename`, `user_set_role`), identities (`identity_get`, `identity_link`, `user_get_or_create_by_identity`), games, challenges. Public functions open their own transaction; the `_`-prefixed variants take a connection so `challenge()` can run its check-and-mutate atomically. Still **no `engine` import** — the chess logic arrives as `apply_game_change`'s `mutate(row, history, now)` callback, which returns a `GameChange`. Every game read returns the **same dict for an active and an archived game** (`_game_dict`; names joined from `users` twice), which is what lets the routes ignore where a game lives. An action on a triple with no game in progress hands the *finished* game to `mutate` read-only, so the engine itself raises `GameOverError` rather than this layer inventing an error.
  - The active-game lock is `FOR UPDATE OF games` (`lock_current_game(conn, stmt, of=games)`): the select joins `users`, and a bare `FOR UPDATE` would lock both players' rows and serialize every game they are in.
  - User uniqueness is pre-checked for a readable message, but the unique index is the guarantee: on PostgreSQL two creates can both pass the check, so an `IntegrityError` is reported as `UserExistsError` too (`test_concurrency.py` races six).
- `postgres.py` / `sqlite.py` — only what genuinely differs: the locking strategy, the dialect's `insert()` for `ON CONFLICT`, and creating a database. `sqlite.py`'s connect hook also sets **`PRAGMA foreign_keys=ON`**: SQLite ignores foreign keys otherwise, silently, so the backends would diverge on exactly what the schema relies on.
- `errors.py` — SQL/challenge/user exception hierarchy rooted at `GameError` (separate from the engine's `ChessError`; shared by client and server for error mapping, by class name, so renaming one is a wire change). Also holds `USERNAME_RE`/`PROVIDER_RE`/`EXTERNAL_ID_RE`, because it is the one `db` module the client and CLI import without SQLAlchemy.

**Any read-then-write must use `locked_transaction()`, not `transaction()`.** This is
the rule that the `game_get_or_create` bug in 0.10.0 broke. Under a plain deferred
`BEGIN`, SQLite starts the connection as a reader and must upgrade to a writer for the
write; if another writer holds the lock it refuses that upgrade with SQLITE_BUSY
**immediately**, because `sqlite_busy_timeout` does not apply to the upgrade path. The
symptom is a 500 `database is locked` on an ordinary request. `apply_game_change`,
`game_delete`, `challenge`, `challenge_create`, `game_get_or_create`, `user_create`,
`user_rename`, `identity_link` and `user_get_or_create_by_identity` are the
read-modify-writes; every other public function in `operations.py` is a plain read or a
write-first statement and may use `transaction()`.

**Locking is the thing to be careful about.** `apply_game_change` is a read-modify-write with the engine running in the middle. PostgreSQL serializes it with `SELECT … FOR UPDATE`; SQLite has no row locks, and **SQLAlchemy compiles `FOR UPDATE` away on SQLite silently rather than raising** — so a naive port looks correct and loses moves. SQLite instead takes the write lock as the transaction opens, via `BEGIN IMMEDIATE`, which is why write paths must use `locked_transaction()` and not `transaction()`. `require_write_transaction()` enforces that; `tests/integration/test_concurrency.py` proves it on both backends (and fails if the lock is removed).

## Conventions

- Docstrings are reStructuredText (`:param:`/`:type:`/`:raises:`) and thorough — match that style, and keep the `:raises:` lists accurate since they're the closest thing to a spec for `move()`.
- Piece movement is data-driven: `(di, dj)` direction-vector tables fed through the shared `_slide`/`_step` scan helpers in `pieces.py`. Add a piece or tweak movement by editing its direction table, not by unrolling per-direction blocks. (This replaces the engine's earlier hand-unrolled loops, which were consolidated in the Phase 2 refactor.)
- Enums are the source of truth for color/piece-type/status; convert to primitives (`int(color)`, `piecetype.value`) only at the serialization and rendering boundaries — never rely on `str()` of an enum member.