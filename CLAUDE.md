# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`chesssnake` is a PyPI library (`pip install chesssnake`) for playing, visualizing, and persisting chess games. It has a pure-Python chess engine, a PIL-based board renderer, and a **3-tier persistence architecture**: a `Game` client that runs the engine locally and syncs state over REST → a FastAPI **api-endpoint** (`chesssnake api-endpoint`) → SQLite or PostgreSQL. Many game clients can share one api-endpoint/database. Current version is 0.15.1 (pre-1.0; the REST api-endpoint shipped in 0.7.0, the configuration system in 0.8.0, SQLite/SQLAlchemy in 0.9.0, the `play` CLI in 0.9.1, published container images in 0.9.2, the threadpool in 0.10.0, users and the redesigned schema in 0.11.0, logins and challenge-created games in 0.12.0, websocket live updates in 0.13.0, the web UI in 0.14.0, the rewritten engine and frozen engine API in 0.15.0, pin-based legality and legal moves pushed with each move in 0.15.1 — see `CHANGELOG.md`, with what is next in `ROADMAP.md`).

The package uses a **`src/` layout**: all importable code lives under `src/chesssnake/` (tests import the installed package, not a repo-root package).

## Commands

The project is managed with **uv**; all metadata lives in `pyproject.toml` (there is no `setup.py` or `requirements.txt`). The build backend is setuptools. Development is manual:

```bash
# Create/refresh the venv. Extras: `client` (requests, for remote games),
# `api` (fastapi + uvicorn + pydantic + sqlalchemy — runs on SQLite with no
# compiled deps), `postgres` (psycopg 3, only for postgresql:// URLs; psycopg2 is refused since 0.14.4).
# `.python-version` pins local dev to 3.12 because the `pg` test group's
# `pgserver` only ships cp311/cp312 wheels; the package itself supports 3.12-3.14
# and the SQLite tests run on all of them.
uv sync                                  # core only (local, in-memory games)
uv sync --extra api --extra client --extra postgres   # full stack (dev + pg groups are default)

# Run anything inside the managed environment
uv run python examples/example.py        # core (no-DB) smoke example

# Run the api-endpoint server (needs the `api` extra + a configured database.url / docker compose Postgres)
uv run chesssnake api-endpoint --host 0.0.0.0 --port 8000 --init-db
uv run chesssnake api-endpoint --init-db -o websocket.enabled=true   # with live updates at /v1/ws
                                         # the web UI is at http://localhost:8000/ (web.enabled, on by default)
uv run chesssnake init-db                # just create the schema, then exit
uv run chesssnake init-db --drop         # drop every table first (pre-1.0 schema changes)
uv run chesssnake user create alice --admin   # accounts, straight in the database; prompts for a password
                                               # (also show/set-role/rename/link/set-password/disable/enable/token)
uv run chesssnake config init            # write a commented default config file
uv run chesssnake config show            # effective settings + where each came from

# Play at the terminal. --local needs nothing but the core install (no server, no
# requests); without it, --api-url / CHESSSNAKE__CLIENT__API_URL points at an endpoint.
uv run chesssnake play --local
uv run chesssnake login --api-url http://localhost:8000   # stores a token (never in the cwd)
uv run chesssnake challenge bob && uv run chesssnake games  # bob: `chesssnake accept ID`
uv run chesssnake play --game 7                           # or --vs bob

# Tests. Both dependency groups install by default, so a bare `uv run pytest` covers
# both backends; CI's SQLite matrix opts out with --no-group pg (no pgserver wheels).
uv run pytest                            # everything under tests/
uv run pytest tests/unit                 # fast, pure-Python engine tests (no DB; incl. the play session + text board)
uv run pytest tests/integration          # API + remote-Game stack, run against BOTH backends:
                                         # a temp SQLite file and a throwaway Postgres (pgserver)
                                         # (the shared app has websockets ON, so every REST test also
                                         # runs the publish path; test_play_live.py runs real uvicorn)
CHESSSNAKE_TEST_BACKENDS=sqlite uv run pytest tests/integration   # SQLite only (no pgserver needed)
uv run pytest tests/config               # config + CLI; needs pydantic but no database
uv run pytest tests/unit/test_rules.py::test_en_passant_capture  # a single test
uv run pytest tests/unit -m slow         # deep perft + 200 more differential games (~40 s; CI's engine-deep job)
uv run python scripts/bench_engine.py    # engine speed; see docs/benchmarks.md
uv run python scripts/bench_vs_python_chess.py   # engine vs python-chess (dev-only reference)
uv run python scripts/bench_server.py URL     # a running api-endpoint over HTTP (open registration, throwaway DB)

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
- **From 1.0.0 to the end of 1.x: minor database changes only** (Gabe, 2026-11-13). Adding a
  table, column or index is fine; a large migration needs a major version bump. A minor
  change still needs a way to apply it to a live database without `init-db --drop`, which
  does not exist yet (`create_all` adds missing tables but never alters one, and the server
  refuses to start on a stale table), so the first schema change after 1.0.0 must bring that
  mechanism with it, kept as small as the changes it serves.
- **The public surface is pinned**: the engine by `tests/unit/test_public_engine_api.py`,
  everything else (Python API, REST routes, settings, CLI) by `tests/config/test_public_api.py`
  against `tests/config/public_api.json`. A failure there means the API changed; regenerate
  the JSON only after deciding the change is intended (`uv run python -m
  tests.config.test_public_api --write`), and review its diff like code.

## Three-tier architecture

The public exports are `Game`, `connect` (a logged-in `ApiClient`), `ApiClient` (lazily, from `remote/client.py`), the payloads (`GameState`, `MoveResult`, `User`, `Challenge`, `LoginResult`, `TokenInfo`), and the enums (`Color`, `GameStatus`, `PieceType`, `Termination`) — see `src/chesssnake/__init__.py`. `Game` is an `engine.Game` subclass built via **factory methods** (not a flag-laden constructor):

- `Game.local(white_name=..., black_name=...)` — pure in-memory game. No network, no `requests`/psycopg imported. The engine runs in-process; it has the **full rules** (draw-by-rule, resign, legal-move listing, FEN/PGN) so a local game behaves identically to a remote one.
- `Game.remote(game_id, *, client=None, api_url=None, token=None, player_id=None)` — one game on the api-endpoint, **by its id** (or a `GameState`), acting as the client's logged-in user. Games are created by accepting a challenge (`ApiClient.accept_challenge`) or by an admin (`ApiClient.create_game`), never by opening one. **The server runs the engine**: `move`/`draw_*`/`resign` send a request, and the returned state is mirrored into the local board (for rendering + accessors). Illegal moves raise the same `ChessError` types as local play. `refresh()` re-fetches state; the client auto-sends its `version` with every action; `player_id` is only for admins acting for someone. A finished game keeps its id and stays readable; a rematch is a new challenge and a new game.

Gameplay state is read through intention-revealing accessors on `Game`: `to_move` (Color), `is_over` (bool), `result` (GameStatus: `IN_PLAY`/`WHITE_WON`/`BLACK_WON`/`DRAW`), `winner` (Color|None), `termination` (Termination|None), `draw_offered_by` (Color|None). The public `Game.move()` returns a `MoveResult` (from/to/san, check, castle/promotion/en, + the new state); rendering is separate (`render()` / `save(path)`). Other engine methods: `resign(player_id)`, `legal_moves()`, `pgn()`, `fen` (property), `Game.from_fen(...)`. *(The base `engine.Game.move()` returns the bare engine `Move`; the public `remote.Game` deliberately overrides it to return the richer `MoveResult` — the two `# type: ignore` lines in `remote/game.py` mark that intentional divergence.)*

The three tiers and where they live:

1. **Client** (`src/chesssnake/remote/`) — `Game` and `connect` (`game.py`); `ApiClient` (`client.py`) is a thin `requests`-style wrapper with one method per route, sending `Authorization: Bearer <token>`; `credentials.py` stores `chesssnake login` tokens. For **remote** games the client does **no** chess computation — it sends moves and mirrors the returned state. For **local** games `move`/`draw_*` call the base `engine.Game` in-process. `requests` is imported lazily (only on the remote path), so local games stay dependency-free.
2. **Server** (`src/chesssnake/api/server.py`) — a FastAPI app built by `create_app(settings)` that **owns the engine** (the authoritative rules). `/health` is unversioned/open; `/v1/auth/login`, `/v1/auth/register` and `/v1/info` are the only other unauthenticated API routes (the web UI's static files at `/` and `/assets` are open too, see `api/web.py`); everything else is on the `/v1` `APIRouter`, whose router-level `Depends(current_principal)` (`api/auth.py`) requires a bearer token. Games are addressed **by id** (`/v1/games/{id}/...`). Mutating routes (`/moves`, `/resign`, `/draw/*`) resolve who acts (`acting_as`), load the row + its `moves` history, build an `engine.Game` (via `serialize.game_from_state`), apply the action (which may raise `ChessError`), and persist the result — all inside one `apply_game_change` transaction; `expected_version` → `VersionConflictError`/409. Challenge routes create games (accept → 201 `GameState`). Errors map to JSON `{error_type, detail}` (chess→400, auth→401, forbidden/turn→403, not-found→404, conflict→409, validation→422, busy→503, sql→500).
3. **Database** (`src/chesssnake/db/`) — SQLAlchemy Core, backend-agnostic. `db/operations.py` holds the query functions (users, tokens, identities, challenges, and the id-keyed game functions) as Core expressions; `db/schema.py` the `MetaData`; `db/engine.py` the engine + `transaction()`/`locked_transaction()`; `db/postgres.py` and `db/sqlite.py` only what differs per dialect; `db/errors.py` the `GameError` types (`GameNotFoundError`, `NotYourTurnError`, `VersionConflictError`, …). The schema (eight tables) is described under `db/` below: `users` own identity, `auth_tokens` hold login and api tokens (hashes only), `challenges` are how games start, `games` holds only games **in progress** (position as one FEN column), `moves` one row per played ply of those, and a game that ends is moved in the same transaction to `finished_games` with its moves collapsed to one `movetext` string. **This layer stays engine-free** — `apply_game_change` runs the caller's `mutate(row, history, now)` callback (the engine logic) between a locked read and the write, and persists the returned `GameChange` — see the locking note in the `db/` section below.

There are **three ways to drive the backend**, all hitting the same `/v1` routes and
the same rules: direct REST calls (any language, a custom frontend), the Python client
(`Game.remote(...)`), and the terminal client (`chesssnake play`). The CLI is built *on*
the client, not beside it — see `play.py` below — so adding a gameplay feature to
`engine` reaches all three without touching any of them.

The wire payloads are defined once in `src/chesssnake/dto.py`: `GameState` (the position as **FEN** + `status`/`version`/`generation`/`draw`/`termination` + `id`/`group_id`/`white_id`/`black_id`/`white_name`/`black_name`/`started_at`/`updated_at`), `MoveResult` (a move + resulting state, incl. `san`) and `User` — stdlib dataclasses, so the client needs no pydantic. Clients build them with `from_dict`, which **ignores unknown keys**, so adding a response field is never breaking; keep it that way. The FEN codec is `src/chesssnake/engine/_fen.py` (public as `Board.from_fen`/`Board.fen`), and `src/chesssnake/serialize.py` bridges `GameState` ⇄ engine `Game` (`game_from_state` with history, `state_from_game`, `board_and_turn`). `src/chesssnake/cli.py` is the console-script entry point; `src/chesssnake/play.py` holds the `chesssnake play` session loop (see below); `src/chesssnake/assets.py` (`asset_path`) centralizes packaged-data lookups.

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
- There is no auth on/off setting: every `/v1` route but login/register needs a token. `api.registration` (`closed`/`open`) and `api.session_lifetime_days` are the only auth settings. `Settings.advisories()` remains as a hook (currently empty). The 0.11 `api.require_auth`/`api.api_key` are gone, and `extra="forbid"` turns a stale one in a file into a startup error.

- `[websocket]` (0.13) holds every live-update knob; `enabled` defaults to **false**. `allowed_origins` is the first list-valued setting: a TOML array in a file, **comma-separated** in `CHESSSNAKE__WEBSOCKET__ALLOWED_ORIGINS`, normalized (lowercase, no trailing `/`), with `*` alone or not at all; `config show` prints it comma-joined. Cross-field limits are `model_validator`s. `cli.py` passes the transport keys (pings, `ws_max_size`, compression, `timeout_graceful_shutdown`) to `uvicorn.run`; `ws_max_queue` is not passed because uvicorn ignores it, and the app enforces `max_message_bytes` itself for `--factory` deployments that skip those flags.

Full reference: `docs/configuration.md`. The commented default file shipped by `chesssnake config init` is `src/chesssnake/data/chesssnake.toml` (registered under `[tool.setuptools.package-data]`); tests assert it stays valid and documents every schema field, so **add a documented block there whenever you add a setting**.

### `engine/` — the chess engine (no external deps beyond Pillow, for rendering)

**The public engine API is exactly `chesssnake.engine.__all__`** (`Board`, `Piece`, `Move`, `Game`, the enums, `errors`, `INITIAL_FEN`, `render_board`, `render_text`), frozen at 1.0.0. `tests/unit/test_public_engine_api.py` pins `__all__` and the public members of `Board`/`Move`/`Piece`, so a change to the API fails a test rather than happening by accident. Everything else, every `_`-prefixed module included, is internal: 0.16.0 is planned to replace the inside of `Board` with bitboards behind this API. Rewritten in 0.15.0 (it was 0.14.4's object-per-square engine with a `deepcopy` per candidate move).

- `enums.py` — `Color(IntEnum)` (WHITE=0/BLACK=1, with `.opponent`), `PieceType` (a plain `Enum`; `.value` is the letter code — never `str()` an enum member), `GameStatus(IntEnum)` (`IN_PLAY=0`/`WHITE_WON=1`/`BLACK_WON=2`/`DRAW=3`, with `.won_by(color)`), and `Termination(str, Enum)` (checkmate/resignation/stalemate/threefold/fifty_move/insufficient_material/agreement). A win is `WHITE_WON`/`BLACK_WON` (checkmate **or** resignation); the reason is the `Termination`.
- `piece.py` — `Piece`, a frozen slotted dataclass `(type, color)` with `.symbol` (FEN letter) and `from_symbol`. `PIECES[(type, color)]` holds the **twelve canonical instances**; the board only ever stores those, which is what lets the move generator compare pieces with `is` in its hot loops. Anything that puts a piece on the grid must go through `PIECES` (as `_fen.parse` and `Board._from_grid` do).
- `move.py` — `Move`, a frozen dataclass of what was played: `from_square`/`to_square` (names; castling is the king's move, `e1`→`g1`), `piece`, `san` (chesssnake notation **with** the `+`/`#` suffix, which is what the history records), `promotion` (`PieceType|None`), `captured`, `castle` (`"K"`/`"Q"`/`None`, the wire's form), `en_passant`, and `.uci`. Returned by `Board.move` and `engine.Game.move`; `remote.Game.move` still returns the richer `dto.MoveResult` (the two `# type: ignore` lines). The wire's `promotion` is the letter, so routes convert with `.value`.
- `_notation.py` — square numbering: **index `i * 8 + j`, `i` the row from the top (0 is rank 8), `j` the file (0 is a)**, so a8=0, h8=7, a1=56, h1=63. `NAMES`/`index()`/`name()`; `SAN_RE` and `UCI_RE` (the whole accepted syntax, one regex each; UCI is unambiguous against SAN because SAN never puts a rank right after a pawn's file); `is_valid_notation`; `move_squares` (above).
- `_fen.py` — `parse(fen)` validates every field and raises `ValueError` saying which (6 fields, 8 ranks of 8, **exactly one king each**, castling/ep/clock syntax), returning the raw parts; `write(board)`; `placement(grid)`; `INITIAL_FEN`. Public access is `Board.from_fen`/`Board.fen`.
- `board.py` — `Board`, a 64-entry list of `Piece|None` plus the six FEN fields as plain attributes (`turn`, `castling` as FEN letters, `en_passant` as a square name, the clocks) and `status`/`termination`. Internals, all private:
  - **Precomputed tables** at import: `KNIGHT_TARGETS`, `KING_TARGETS`, `PAWN_ATTACKS[color]`, and per-square rays (`ORTHOGONAL_RAYS`/`DIAGONAL_RAYS`/`QUEEN_RAYS`, nearest square first). Movement is data: change a table, not a loop.
  - A **ply** is a plain tuple `(from, to, promotion, flag)`, flag one of `NORMAL`/`DOUBLE_STEP`/`EN_PASSANT`/`CASTLE_K`/`CASTLE_Q` (`_san.py` and `_parse.py` mirror the numbers; keep them in step).
  - `_pseudo(color)` generates from the tables; `_make(ply)` plays it in place and returns an undo record (captured piece, castling, ep, clocks, status, termination, the king square); `_unmake` restores it exactly; `_is_legal` = make, is the mover's king attacked (`_attacked`, direct scans, no lists), unmake. **No copying anywhere**: that `deepcopy` per candidate was 97% of 0.14.4's runtime. `_kings[color]` caches the king squares (`None` in a kingless test position, which skips the check test).
  - **Legality comes from pins, not trial, when not in check** (0.15.1; the trial test was 85% of generation time). `_legal_iter()` (behind `_legal()` and `_has_legal_move()`): if the king is in check or missing, every ply goes through `_is_legal`; otherwise `_pins(color, king)` scans the 8 lines from the king once (first own piece, then an enemy rook/queen on a rank or file or bishop/queen on a diagonal: pinned, allowed squares = the line up to and including the pinner), and then unpinned non-king plies are legal, pinned ones only along their line, normal king moves only to `not _attacked(to)` (sound because, not being in check, no attack runs through the king's own square). **Castling and en passant still use `_is_legal`**: rare, and en passant can uncover a rank check by removing two pawns. `_legal_by_trial()` is the reference; `tests/unit/test_legal_fast_path.py` asserts the two agree at every ply of 40 games and in hand-picked pin/check/e.p. positions.
  - **Hot paths index per-colour tuples** (`PAWNS`/`KNIGHTS`/.../`KINGS[color]`, `OPPONENT[color]`), never `PIECES[type, color]` or `color.opponent`: `Enum.__hash__` and the property are Python-level and were about a fifth of `_attacked`. Same reason `_pseudo` picks slider rays by `is` tests rather than the `SLIDER_RAYS` dict (which only the diagnosis still uses).
  - `_castle_ok(color, side)` is the one castling rule, used by generation and by the parser's diagnostics: the right, king and rook home, squares between empty, **king not in check, crossed square (f or d) not attacked**; the destination is caught by the legality test. 0.14.4 checked neither the king's own square nor d1/d8.
  - **Threefold repetition and the fifty-move rule end the game automatically** (Gabe's decision, 2026-11-13), as do checkmate, stalemate and insufficient material. FIDE makes those two a player's claim (with automatic draws only at fivefold and seventy-five moves); chesssnake deliberately does not, and python-chess's `outcome(claim_draw=True)` is the comparison the differential tests use for that reason. Do not "fix" this toward FIDE without asking.
  - `move(text)`: syntax → game over → `_parse.resolve` against the legal list → `_san.san` → `_make` → `_update_outcome` (mate, stalemate, insufficient material, fifty-move; threefold is `Game`'s, since it holds the history) → suffix → push `(ply, undo, Move)` for `undo()`.
  - `_position_key()` is the threefold identity: placement, side, castling, and the ep square **only when a legal en-passant capture exists** (FIDE's rule, and python-chess's). These keys are stored in the `moves` table.
  - `Board._from_grid(grid, turn, castling, en_passant)` skips FEN validation; it exists for `tests/unit/conftest.py`'s `make_board`, which builds kingless positions.
- `_parse.py` — `resolve(board, text, legal)`: a move is chosen by **matching it against the legal plies** (`_match_san`/`_match_castle`/`_match_uci`), so notation can never make a legal move illegal or the reverse. One match is returned (after the strict capture-mark checks: `Ne5` onto a piece is `PieceOnSquareError`, `Nxe5` onto nothing `NothingToCaptureError`); several is `MultiplePiecesFoundError`. None runs a diagnosis (`_diagnose_san`/`_diagnose_castle`/`_diagnose_uci`, the old `find_one` reasoning kept **only to explain**) through **`_explain()`, the guard: a diagnosis must raise its specific error; if it returns (no reason found) or raises anything that is not a `ChessError` (a bug, logged with its traceback), the move gets the plain `IllegalMoveError`**. Gabe's rule (2026-11-13): a misleading error is worse than none, so never guess. That is why **`MoveIntoCheckError` is raised only when confirmed**: the move must fit a pseudo-legal ply (a possible piece movement) that the legality test removed. Before this guard, check was the fall-through answer, and e.g. `dxe6` with an en-passant square but no pawn to take was blamed on check; `tests/unit/test_diagnosis_fallback.py` pins the guard on all three paths. The error classes are the wire contract (the client rebuilds them by name), which is why Gabe kept them rather than collapsing to illegal/ambiguous/malformed. `IllegalMoveError` was added in 0.15.0.
- `_san.py` — writes chesssnake notation (`e8Q`, `0-0`: what the history stores, `legal_moves` lists, and the parser reads back). **Disambiguation looks only at legal moves** (a pinned knight does not make `Nd2` into `Nbd2`). `Game.pgn()` converts to standard PGN (`e8=Q`, `O-O`).
- `image.py` — `render_board(board, white_name, black_name, move=None, perspective=None) -> PIL.Image`; composites cached piece PNGs, 68px tiles, last-move highlight. The blank board and template are decoded once (`_decoded`, about 12 ms per wide render before 0.15.1) and **every render draws on a `.copy()`, never the cached image** (`test_image.py` renders with a highlight and checks it does not leak). Fonts are deliberately not cached: 0.1 ms to load, and a FreeType face is not documented as safe across the server's threads. `Game.save` writes PNG at `compress_level=1` (40 → 28 ms to encode the wide image, +11% bytes) and still lets Pillow choose the format from the file name. `perspective=None` → the wide both-orientations image (the bottom name strip is dropped when *both* names are empty); `perspective=Color.WHITE`/`BLACK` (or `"white"`/`"black"`) → a single board from that side (board only, via the shared `_render_side`).
- `text.py` — `render_text(board, perspective=None, *, figurines=True, coordinates=True, color=False, move=None) -> str`; the **sibling of `image.py`**, same job in text. Has **no dependencies at all**, not even Pillow, which is what lets `chesssnake play --local` work from a core install. `perspective=None` means white's view (there is no sensible side-by-side text form, unlike `render_board`). `color=False` emits **no escape sequence at all**, so output pipes and diffs cleanly — keep it that way, the tests compare plain strings. The last-move highlight only applies when `color` is on. Both renderers find the highlighted squares through `_notation.move_squares(move)`, which takes an engine `Move`, a `dto.MoveResult` (both have `from_square`/`to_square`) or a `{"from", "to"}` dict, and highlights nothing for anything else.
- `errors.py` — gameplay exception hierarchy rooted at `ChessError`. Constructors take square **names**; their argument shapes are not wire (the client rebuilds by class name and message).
- `game.py` — the base `Game` controller that `remote/game.py`'s `Game` subclasses. `turn` is a **property over `board.turn`** (the board owns the side to move, as FEN does); the constructor's `turn=None` keeps the board's. Holds `draw`, `move_history` (each `Move.san`, so UCI input is stored canonically) and `position_history` (`Board._position_key()`s, for threefold). Methods: `move`, `resign`, `draw_*`, `legal_moves`, `pgn`, `fen`, `from_fen`.

**Verification** (`tests/unit/`, all through the one adapter `engine_adapter.py`): `test_perft.py` (CPW perft positions; deep depths `-m slow`), `test_differential.py` (seeded random games against **python-chess, a dev-only GPL test oracle that `src/` must never import**: identical legal-move sets, FEN, endings, and no missed threefold/fifty-move), `test_roundtrip.py` (every listed SAN plays; `pgn()` reparses in both engines), `test_regressions_015.py`, `test_legal_fast_path.py` (pins vs trial), `test_diagnosis_fallback.py` (the `_explain` guard). `addopts = -m 'not slow'`; CI's `engine-deep` job runs `-m slow`. `scripts/bench_engine.py` measures speed using only the `Game` API, so it also runs against an old release (`docs/benchmarks.md`).

### `remote/` — the client (tier 1)

- `game.py` — `Game(BaseGame)` (built via `Game.local()`/`Game.remote()`/`Game.from_state()`) and `connect()`, which resolves a token from: `username`+`password` (logs in), `token=`, `$CHESSSNAKE__CLIENT__TOKEN`, then `credentials.load(url)`; as a library it raises `AuthError` rather than prompting. The low-level `Game.__init__(*args, client=None, player_id=None, version=None, generation=None, game_id=None, **kwargs)` is internal. For remote games, `move`/`resign`/`draw_*` call the client by game id (sending `player_id` + the tracked `version`) and pass the returned state to `_apply_state` (rebuilds the mirror board via `serialize.board_and_turn` from the FEN, updates `version`); `last_move` is the server's `MoveResult`, whose `from_square`/`to_square` drive the render highlight. `legal_moves`/`pgn`/`history` proxy to the server when remote, or run the local engine otherwise.
  - The 0.11 module helpers (`create_user`, `challenge`, `record`, ...) are gone: every call needs the same authenticated client, so they are `ApiClient` methods now. Methods that take a player accept an id or a username (`ApiClient.resolve`).
- `realtime.py` — `EventStream(client, games=())`, returned by `ApiClient.events()`; `websockets` (in the `client` extra) is imported **lazily**, only when a stream is made. The first connection either works or raises `RealtimeUnavailable` with the reason (HTTP 403 means websockets are off; a 4401 raises `AuthError`). After that a **daemon thread** reads the socket and only queues, writing one byte to a non-blocking self-pipe per event (`fileno()` for `select`; `drain()` empties the pipe *before* the queue so no wakeup is lost). On a drop it emits `disconnected`, reconnects with backoff (1 s doubling to 30 s), re-sends the whole wanted-games set (kept under a lock, so a `subscribe` racing a reconnect is not lost), then emits `reconnected`; 4400/4403, or an HTTP status on reconnect, emit `ended`; 4401 emits `auth_error`.
- `client.py` — `ApiClient(base_url, session=None, token=None)`. Prefixes `/v1`, adds `Authorization: Bearer` when it has a token (`login()` sets it). `session` defaults to `requests.Session()` but can be **injected** (tests pass a FastAPI `TestClient`). `move()` → `dto.MoveResult`; `get_game`/`accept_challenge`/`create_game`/`resign`/draw → `dto.GameState`; `legal_moves`/`history` → lists; `pgn`/`fen` → text; `image()` → PNG bytes. **Error mapping** covers both `engine.errors` and `db.errors`: `_build_error_registry` maps class name→class, and `_raise` reconstructs via `cls.__new__(cls); exc.args=(detail,)` so `except PromotionError`/`except VersionConflictError` work.

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
- **`actor()` decides whose action it is.** With a `player_id` it is always that player:
  for a remote game `cli.py` passes the **logged-in user's id** when they are playing (so
  draws and resignations are sent as them, and the server enforces turn order), and
  `None` only for an admin watching someone else's game. With `None` the default is
  *whoever is to move* — one person at one keyboard playing both sides, or that admin —
  except for `accept`/`decline`, which default to the **opponent of the offerer**.
- **Turn-order enforcement is asymmetric, on purpose.** For a **remote** game the
  server checks it and is the authority, so the session must not duplicate the rule. For
  a **local** game (`--me 0|1`) there is no server to ask, so `dispatch()` checks
  `is_players_turn` itself and raises `NotYourTurnError`.
- **`sync()` runs before every informational command** (`board`, `fen`, `moves`, `pgn`),
  and this is load-bearing rather than belt-and-braces: `legal_moves`/`pgn`/`history` are
  **proxied to the server** while the board and `fen` come from the local mirror, so
  without it the two disagree the moment the opponent moves — `moves` would list the
  legal moves of a position not on screen. It returns whether the version actually moved
  on, so the caller can redraw and say so instead of silently changing the board.
- **The session follows one game id**, so an action can never land in a rematch (before
  0.11 one could, and did). Once the game is over, `sync()` also looks for a **newer
  game between the same two players** (by id, which only increases; *not* by
  generation, which is per colour arrangement and restarts when a rematch swaps
  colours) and sets `newer_game`; `allow_action()` then refuses with a sentence naming
  `new`. `new` joins that game, else accepts the opponent's pending rematch challenge,
  else sends one with colours swapped: a rematch takes both players' say-so, because
  games are only created by an accepted challenge.
- **An `AuthError` ends the session** (exit 1, "run `chesssnake login`"), from a command or
  from an idle poll. It is a `GameError`, so without this special case it would be
  printed and repeated on every line and every poll.
- **Live updates (0.13) arrive through `events`**, an optional stream with `fileno()`,
  `drain()`, `subscribe()`, `unsubscribe()` (`remote.realtime.EventStream`; the unit tests
  pass a fake over a real `os.pipe`). `cli.py` tries `client.events([game.id])` first and
  falls back to polling with a note on `RealtimeUnavailable`; `--no-live` skips it.
  While **connected**, `_wait_live` `select`s on stdin and the stream fd with **no
  timeout**: nothing is polled. While **disconnected** (a `disconnected` event) it uses
  the `--refresh` timeout and `sync()`s until `reconnected`. `handle_events()` runs on
  the session's thread (the stream's reader thread only queues), version-checks every
  state against the mirror, and is also called before each prompt, which is how
  events reach a stdin that cannot be selected on (Windows, a `StringIO`). `auth_error`
  raises `AuthError` (ends the session); `ended` drops to polling; `game_started` for
  the same two players and group sets `newer_game`; `_switch_to` moves the
  subscription to the rematch.
- **Without a live stream, `wait_for_line()` is the one thing the session does unasked**, polling every
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
- `cli.py`'s client commands (`login`, `logout`, `whoami`, `games`, `challenge`,
  `challenges`, `accept`, `decline`, `play`) deliberately **never import `config`**: they
  need only the `client` install. They hardcode `CHESSSNAKE__CLIENT__API_URL` and
  `CHESSSNAKE__CLIENT__TOKEN` (argparse needs them at parser-build time), with tests in
  `test_play.py` keeping the copies honest — the same pattern as `remote/game.py`,
  `remote/credentials.py` (`CHESSSNAKE_HOME`) and `db/errors.py`.
- **The credentials file is never in the working directory**, unlike config discovery:
  `$CHESSSNAKE_HOME`, else `$XDG_CONFIG_HOME/chesssnake`, else `~/.config/chesssnake`;
  directory 0700, file 0600, replaced atomically. A token dropped into a git checkout is
  one `git add -A` from published.
- **Passwords are never command-line arguments** (`ps` and shell history): prompted with
  `getpass`, or `--password-stdin`.

### `api/` — the server (tier 2, **owns the engine**)

**Every `/v1` route is a plain `def`, deliberately.** The bodies are blocking:
synchronous SQLAlchemy, engine computation, PIL rendering. FastAPI only dispatches a
route to its worker threadpool when it is `def`; an `async def` route runs on the event
loop and blocks every other request for its whole duration. They were all `async def`
with no `await` anywhere until 0.10.0, so the server handled one request at a time.
`tests/integration/test_threadpool.py` fails if one goes back.

**`/health` and `/v1/ws` are the only `async def` routes, also deliberately** (the
websocket is I/O-bound and offloads its blocking calls; see `realtime.py` below).
**`/health`** It touches nothing, so
leaving it on the loop means it answers immediately while every worker thread is busy,
which is what keeps the container's two-second healthcheck honest under load. Note the
asymmetry this buys: `/health` is a *liveness* probe and after this change it cannot
report a wedged threadpool. That is the intended trade; a readiness probe would be a
separate feature. The exception handlers and `lifespan` stay async, since they do no
blocking work. The auth dependency `current_principal` is a plain `def`, deliberately:
it does a database lookup, so it runs in the threadpool with the route.

**Argon2 is the other expensive thing, and it has two rules** (`api/auth.py`): it never
runs inside a transaction (on SQLite a `locked_transaction` holds the whole database's
write lock), and it **only ever runs on `_hash_pool`, a dedicated pool of
`MAX_CONCURRENT_HASHES` (4) threads**, admitted by a semaphore whose timeout is a 503.
A cap on concurrency alone is not enough, and 0.12.0 shipped with only that: each hash
allocates 19 MiB, glibc keeps a block that size in the allocating thread's arena after
it is freed, and anyio runs routes on up to 40 threads, so every thread that ever
hashed kept its own 19 MiB. Measured on the deployed server: one burst of 40 logins
pinned the 512 MiB container at its limit (throttled 2,234 times, anon memory 479 MiB);
in-process, 777 MiB with the semaphore alone against a flat 93 MiB with a 4-thread
pool. `tests/config/test_password_hashing.py` fails if a hash runs on any other thread. Because
the verify happens outside the transaction, the write that follows (minting the token,
changing the password) passes `expected_hash=` so the operations layer re-checks, under
the lock, that the password was not reset in between.

Anything that runs in a worker thread must not assume request-scoped context survives a
further thread hop: `WRITE_TRANSACTION` (`db/engine.py`) is a `ContextVar`, and anyio
copies the context into the worker, so it is correct today precisely because nothing
inside `apply_game_change` offloads to another thread. If anything ever does, SQLite
silently falls back to a deferred `BEGIN` with no error, which is the bug class above.

- `auth.py` — `authenticate(raw_token) -> Principal` (transport-agnostic: the HTTP dependency `current_principal` wraps it, and the websocket calls it with the token from its first message, through the broker's own thread limiter); `acting_as(principal, player_id, participants=, require_actor=)` decides who an action is performed as (non-admins: always themselves; admins: the named `player_id`, else themselves if playing, else "side to move" for a move only; never a disabled user); `login()`; Argon2 hashing behind the semaphore. Database errors inside `authenticate` are **not** turned into 401: a saturated pool stays a 503.
- `server.py` — `create_app(settings)` builds the FastAPI app (settings on `app.state.settings`); a module-level PEP 562 `__getattr__` still resolves `chesssnake.api.server:app` lazily for ASGI import strings. **The public router (`login`, `register`, `info`) is built per app by `_public_router(settings)` and included on the app, not into `v1`**: a router included into `v1` inherits its auth dependency. **43 HTTP routes in all** (including `/` from `api/web.py`; plus `/v1/ws` when websockets are on, pinned separately), pinned by `test_threadpool.py`, which walks them with `fastapi.routing.iter_route_contexts` (FastAPI 0.139 keeps included routers as wrappers, so `app.routes` alone misses them). Every route also has a row in `tests/integration/test_permissions.py`'s table (expected status for anonymous / outsider / player / admin), and a route without a row fails the suite. Game routes are by id; literal routes (`/games/between`, `/games/live`, `/games/finished`, `/games/record`, `/users/search`) are registered before the `{id}` routes. The listing routes (`/games/live`, `/games/finished`, `/users/search`) exist for the web UI and cap `limit` at `ops.LIST_LIMIT_MAX` (200). The image route serves `_board_png(fen, white_name, black_name, perspective)`, an `lru_cache(maxsize=64)` of finished PNG bytes (~100 KB each): those four values are everything a server image shows (no last-move highlight), so a move or a rename is a new key and the cache can be module-level and shared by every app in a process. Mutating game routes resolve the actor **before** the transaction (it may read users), then `apply_game_change(game_id, mutate, expected_version)`; `mutate` checks the turn only for a game in progress, so a finished game answers `GameOverError`, not "not your turn". `_load_game` prepends the starting position's key; `_change` builds the `GameChange` and clears `draw` on a finished game. Handlers: `AuthError`→401 (with `WWW-Authenticate: Bearer`), `ForbiddenError`/`NotYourTurnError`→403, `*NotFoundError`→404, `ChallengeError`/`VersionConflictError`/`UserExistsError`→409, `SQLIdError`/`UserValidationError`→422, `SQLBusyError`→503, `SQLError`→500, `ChessError`/`GameError`→400. `lifespan` inits the pool and **refuses to start on a database whose existing tables differ from the schema** (`schema.stale_tables`), since `create_all` never alters a table and there are no migrations; its `current_engine() is None` guard lets a second app share an existing pool, which is how the tests build an open-registration app alongside the default one.
- `realtime.py` — live updates at `/v1/ws` (protocol: `docs/realtime-websockets.md`), registered by `create_app` **only when `websocket.enabled`**; off, the upgrade gets HTTP 403 and `app.state.broker` is the no-op base `Broker`, so publishing costs a REST request nothing. Load-bearing details:
  - **One broker per app** on `app.state.broker`, reached by routes through `request` (`server._broker`). The `v1` router object is shared by every app in a process (the tests build several), so a module-level broker would cross their events.
  - **Routes publish after `ops.*` returns**, i.e. after commit: moves/draws/resign → `game_changed` (a move's event also carries `legal_moves`, the next player's options, computed in the route's `mutate` and identical to the `MoveResult`'s; draw/resign events carry none); accept and admin create → `game_started` (to both players' user topics); challenge create/delete → `challenge` (delete publishes from the challenge read *before* deleting); admin delete → `game_removed`; logout/revoke → `recheck_token`, password change/reset and disable → `recheck_user`, which close those sockets at once (the periodic `reauth_interval` check is the backstop, e.g. for `chesssnake user` run on the server's machine).
  - **`_publish` runs in a worker thread and never raises**: the change is already committed, so an exception would turn a saved move into a 500. It serializes once and hands over with `loop.call_soon_threadsafe`; everything touching sockets, queues and topic tables runs on the loop thread. The loop (and the dedicated `CapacityLimiter`, `worker_threads`) is captured lazily in `admit()`, the first code sure to run on the loop.
  - **Every refusal closes after `accept()`** (4401/4403/4408/4429/4400/1009/1013): a close before accepting reaches a real client as a bare HTTP 403, losing the code and reading as "websockets off".
  - **Versions never go backwards per connection**: `Connection.seen` is a high-water mark per game, and `pending` holds events that arrive while a `subscribe` snapshot is being read (subscribe-before-read, then send the newer of snapshot and held state). Two worker threads can publish moves out of order; this is what hides it.
  - One sender task is the only writer; `request_close()` is the only way to close (idempotent; cancels the connection's task group; the handler's `finally` unregisters and sends the close once). uvicorn's websocket implementation never applies send backpressure (its `writable` flag is never cleared), so a client that stops reading is bounded by the ping timeout, and `send_queue_size` only bounds the server's own buffering (overflow → 1013). uvicorn closes every socket with 1012 on shutdown, before the app's shutdown code runs.
  - Blocking work (`authenticate`, snapshot reads) goes through `anyio.to_thread.run_sync` on the broker's **own** limiter, so a reconnect storm cannot take REST's threads. A `GameError` during reauth keeps the socket (only `AuthError` closes it).
  - **In-process only**: several workers/replicas would each have their own broker. `Broker` is the seam for a PostgreSQL LISTEN/NOTIFY implementation (not built).
  - Measured (0.13.0, local): ~56 KiB RSS per authenticated idle socket (500 sockets: 70 → 97 MiB); SIGTERM to exit with 500 open: 0.14 s; REST move to the other player's `play` screen: ~10 ms.

### The web UI (`api/web.py` + `data/web/`)

A static site served by the api-endpoint when `web.enabled` (**on by default**, unlike websockets). `api/web.py` adds `GET /` (a `def` route returning `index.html`) and two `StaticFiles` mounts, `/assets/pieces` (the `data/img` sprites the renderer uses) **before** `/assets` (`data/web`): Starlette tries mounts in order. Nothing is mounted at `/`, so an unknown `/v1/...` path keeps the JSON 404. Every response carries a strict CSP (`script-src 'self'`, no inline script or eval, `connect-src 'self'` covering the same-host websocket), `nosniff`, `no-referrer` and `Cache-Control: no-cache` (ETag revalidation, so an upgrade is picked up at once).

- **Vanilla ES modules, no build step and no Node**: `index.html`, `style.css`, `js/{app,router,api,live,fen,board,cards,ui}.js` and one module per page in `js/views/`. Registered under `[tool.setuptools.package-data]` (`data/web/js/views/*.js` too); the release workflow checks every file of `data/web` is in the wheel, and `tests/integration/test_web.py` walks `index.html` and every module's relative imports and fetches each, failing on a module nothing imports.
- **It is only a client of `/v1`.** The session token from `/v1/auth/login` lives in `localStorage` and is sent as a bearer token, so there is no cookie auth and no CSRF surface; the CSP is what protects the token, so **text goes on the page only through `textContent`** (`ui.h()`), never as HTML. `test_web.py` fails on `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write`/`eval(`/`new Function` anywhere in the scripts, comments included.
- **Per-user settings live on the server** (`GET`/`PATCH /v1/auth/settings`, `ops.USER_SETTING_DEFAULTS`, one JSON document per user in `user_settings`), so they follow the user to every browser; `js/settings.js` loads them at login. The server only stores them; the web UI acts on them (`auto_queen` makes `board.js` send the `Q` promotion without the picker). Adding a setting is one line in `USER_SETTING_DEFAULTS` (its default's type is its type, checked exactly; a name ending `_color` must also be `#rrggbb`, stored lowercase, by `_setting_value`) plus the client code; it is deliberately **not** a schema change. The five `mark_*_color` settings (0.14.2) colour the board marks: `draw.js` reads them at the moment a mark is made (`colorFor`) and passes every colour through `safeColor` before it reaches the SVG; `views/marks.js` is the Account page card (presets, an rrggbb field, a preview `Board({mini: true, marks: true})`, a debounced save).
- **Identities: admins link, users may unlink their own** (`DELETE /v1/users/{id}/identities/...`). Linking asserts the external account is this user, which a self-claim cannot prove, so it stays with admins and trusted bots (a Discord `/link` command).
- **Board marks** (`js/draw.js` + `board.js`, 0.14.1), chess.com style: right-click highlights a square (drawn in `svg.drawing.under`, z-index 0, which sits above the squares and below the pieces' z-index 1), right-drag draws an arrow and middle-click a ring (both in `svg.drawing.over`). Colours from Ctrl (green) and Alt (blue); **never Shift**, because Firefox always opens its context menu on Shift + right-click and a page cannot stop it. The marking state machine is deliberately less eager than piece dragging: 8 px before a right press counts as a drag, a drag back to its own square makes nothing, a press within 150 ms of the last release is ignored (bouncing buttons), and a `pointermove` with the button no longer in `ev.buttons` ends the mark (a swallowed pointerup must not leave an arrow stuck to the cursor; `lostpointercapture` and window `blur` cancel). The arrow's target comes from `squareNearest()`, computed from the board's box and clamped to the edge, so dragging off the board keeps the arrow (and releasing there finishes it) instead of losing it. `markStarted()`/`markEnded()` in `draw.js` block the context menu document-wide for the whole gesture, however it ends, and 400 ms after, for systems that fire it on the mouse-up wherever the pointer is. Every full-size board listens (spectators mark too); a left click clears; nothing is sent.
- **It never decides legality.** Since 0.15.1 `views/game.js` takes the legal moves that arrive with the opponent's move on the websocket (`live.js` passes `msg.legal_moves` through as `legalMoves`) and uses them only when their version is the one on screen; page load, polling, a snapshot replacing a held event, and a draw offer still ask the route (verified in headless Chromium: no request across six clicked moves with websockets on, one per turn with them off). `board.js` offers exactly `GET /games/{id}/legal-moves` (`{from, to, san, promotion}`; castling comes back with `to: null`, mapped to the king's destination, and dropping the king on its rook also castles) and posts the chosen SAN with `expected_version`. It draws the move at once and the server's answer replaces it.
- **`live.js` is one socket for the whole page** (one `EventTarget`, `live`): views `subscribe` with a refcount and listen for `game`/`game_started`/`challenge`/`game_removed`/`resync`. It connects only when `GET /v1/info` says `websocket: true` (a browser cannot see the HTTP 403). `router.Scope` undoes a page's listeners, timers and subscriptions on navigation; `scope.poll(fn, ms)` is the polling fallback and is skipped while `live.isLive` unless `whenLive`.
- **Verified in headless Chromium, not by unit tests** (there is no JS runner): a Playwright script drove two players, a spectator and an admin through challenge, click and drag moves, promotion, castling, draw, resign, rematch, disable/reset/delete, polling with websockets off, and phone width, with no console errors or CSP violations. That run found the two engine bugs fixed in 0.14.0 (a pawn's double step from any rank; `Bb4+` with its suffix a 500).

### `db/` — the database layer (tier 3, **engine-free**)

Backend-agnostic SQLAlchemy Core. The `database.url` scheme picks the backend; there is no separate "which database" setting to drift.

- `__init__.py` — the common interface. Everything is lazy except `errors`, which `remote/client.py` imports for error mapping: the `client` extra installs neither SQLAlchemy nor psycopg, so an eager import would break `pip install chesssnake[client]`.
- `schema.py` — the `MetaData` and eight tables, in dependency order in `TABLES` (tests delete in reverse): `user_settings` (PK `user_id`, one JSON `settings` text; no row = all defaults; added in 0.14.0, and `missing_tables()` makes a server without `init_schema` refuse to start on a database that lacks a newer table rather than 500 on its routes), `users` (server-assigned id, `username` unique on `lower(username)`, `role` 0/1, Argon2id `password_hash` or NULL for token-only accounts, `disabled_at`), `auth_tokens` (`kind` 0 session / 1 api, **only `sha256(token)` stored**, unique; `expires_at` NULL only for api tokens), `user_identities` (PK `(provider, external_id)` → `user_id`: external ids such as Discord ids map onto users here, never by choosing user ids), `games` (in progress only; unique `(group_id, white_id, black_id)`; FEN, `draw`, `version`, `generation`), `moves` (`(game_id, ply)`, no ply-0 row), `finished_games` (the archive: same `id`, `status`/`termination`, `movetext`, final `fen`), `challenges` (assigned id, `color` 0 white / 1 black / 2 random for the challenger, unique per `(group_id, challenger_id, challenged_id)`). **Every identifier is lowercase**: SQLAlchemy quotes anything else, and lowercase is the one spelling that is unquoted on both backends and gives identical result-row keys. Load-bearing details, each pinned by `tests/config/test_schema.py`:
  - **Assigned ids must render as exactly `INTEGER PRIMARY KEY AUTOINCREMENT` on SQLite** (`BigInteger().with_variant(Integer, "sqlite")` + `sqlite_autoincrement=True`; `Identity()` on PostgreSQL). BIGINT is not a rowid alias, and without AUTOINCREMENT SQLite reuses the highest id once that row is deleted, which archiving does, so a new game would collide with an archived one.
  - **No server-side timestamp defaults.** The ops layer writes every timestamp as UTC (`_utcnow`) and normalises reads (`_as_utc`): SQLite strips the offset rather than converting, so binding a non-UTC aware datetime would store the wrong instant silently.
  - `create_all(checkfirst=True)` never alters existing tables. Pre-1.0 a schema change is applied with `chesssnake init-db --drop` (`schema.drop_all`), not a migration.
- `engine.py` — `parse_url` (validates the scheme, rejects libpq keyword strings with the URL equivalent), `create_engine`/`initialize_engine`/`dispose_engine`, `transaction()`, and `locked_transaction()`. The process-wide engine handle lives here. `_engine_kwargs` is per-dialect: an in-memory SQLite database needs `StaticPool` and rejects pool sizing, a file one takes `QueuePool`, and PostgreSQL gets `pool_pre_ping`.
- `operations.py` — the query functions as Core expressions: users (`user_create`, `user_get`, `user_get_by_name`, `user_credentials` (**the only function that returns a password hash**), `user_rename`, `user_set_role`, `user_set_disabled`, `user_set_password`), tokens (`token_create`, `token_resolve`, `tokens_list`, `token_delete`), identities, challenges (`challenge_create`/`_get`/`challenges_for`/`_delete`/`_accept`), and id-keyed games. Public functions open their own transaction; the `_`-prefixed variants take a connection. **Revocation lives here, not in routes**, so the database-direct CLI gets it too: disabling deletes every token; `user_set_password(revoke="sessions"|"all", keep_token_id=)` (self-service keeps api tokens, an admin reset does not). The last enabled admin cannot be demoted or disabled. `token_resolve` is a plain read (it runs on every request and must never take the write lock); there is no `last_used_at` for the same reason.
  - **`challenge_accept` deletes the challenge first** and proceeds only if that delete removed it: on PostgreSQL a second accept (or a withdrawal) waits on the row lock, then finds nothing. Create-then-delete let two accepts of a `random` challenge make two games with opposite colours.
  - **`lock_pair(conn, group_id, a, b)`** (backend hook: `pg_advisory_xact_lock` on a hash of the unordered pair on PostgreSQL, a no-op on SQLite where `BEGIN IMMEDIATE` already serialises) is taken first by challenge create, accept and admin game create, because their "is there already a game / a pending challenge" checks are plain reads. Not `FOR UPDATE` on `users`, which conflicts with the key-share locks foreign-key checks take. `test_challenges.py`'s crossing-challenges race fails without it (measured: 2 runs in 6 with the lock disabled, 0 in 15 with it). Still **no `engine` import** — the chess logic arrives as `apply_game_change`'s `mutate(row, history, now)` callback, which returns a `GameChange`. Every game read returns the **same dict for an active and an archived game** (`_game_dict`; names joined from `users` twice), which is what lets the routes ignore where a game lives. An action on a triple with no game in progress hands the *finished* game to `mutate` read-only, so the engine itself raises `GameOverError` rather than this layer inventing an error.
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
`challenge_create`, `challenge_accept`, `game_get_or_create`, `user_create`,
`user_rename`, `user_set_role`, `user_set_disabled`, `user_set_password`,
`token_create`, `identity_link`, `user_get_or_create_by_identity` and `user_settings_update` are the
read-modify-writes; every other public function in `operations.py` is a plain read or a
write-first statement and may use `transaction()`.

**Locking is the thing to be careful about.** `apply_game_change` is a read-modify-write with the engine running in the middle. PostgreSQL serializes it with `SELECT … FOR UPDATE`; SQLite has no row locks, and **SQLAlchemy compiles `FOR UPDATE` away on SQLite silently rather than raising** — so a naive port looks correct and loses moves. SQLite instead takes the write lock as the transaction opens, via `BEGIN IMMEDIATE`, which is why write paths must use `locked_transaction()` and not `transaction()`. `require_write_transaction()` enforces that; `tests/integration/test_concurrency.py` proves it on both backends (and fails if the lock is removed).

## Conventions

- Docstrings are reStructuredText (`:param:`/`:type:`/`:raises:`) and thorough — match that style, and keep the `:raises:` lists accurate since they're the closest thing to a spec for `move()`.
- Piece movement is data-driven: the precomputed target and ray tables in `engine/board.py`. Tweak movement by editing a table, not by unrolling per-direction blocks.
- Enums are the source of truth for color/piece-type/status; convert to primitives (`int(color)`, `piecetype.value`) only at the serialization and rendering boundaries — never rely on `str()` of an enum member.