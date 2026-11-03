# Changelog

All notable changes, newest first. Versions follow [semantic versioning](https://semver.org/).
Pre-1.0 minor versions may contain breaking changes; each one says so.

Some early patch versions are missing: they were documentation or small fixes.
What is planned next is in [ROADMAP.md](ROADMAP.md).

## 0.9.2 - 2026-11-03

Container images are now published to `ghcr.io/gabebecker2048/chesssnake` on
every release, for linux/amd64 and linux/arm64, so a deployment is a compose
file and nothing to build.

Releases are now cut by pushing a tag: one workflow builds, publishes to PyPI
and GHCR, then creates the GitHub release from this file's entry.

**Breaking:** Python 3.11 is no longer supported. 3.12 or newer is required.

Fixes a PostgreSQL connection failure on fresh installs. SQLAlchemy 2.1 changed
the default driver for a bare `postgresql://` URL from psycopg2 to psycopg v3,
so `chesssnake[api,postgres]`, which installs psycopg2, died at startup with
`No module named 'psycopg'` depending only on which SQLAlchemy was resolved.
The URL now names whichever driver is installed, and a URL that already names
one is left alone. The test suite runs against SQLAlchemy 2.1 so this cannot
drift again.

Fixes the container refusing to start under `user:`. Its working directory was
the image user's home, which is mode 700, and the config search reads the
working directory first, so any other uid crashed with a `PermissionError`.
Working directory and `HOME` are now `/data`, which the running user owns by
definition.

Documentation reorganised: a much shorter README, the usage material moved to
`docs/guide.md`, Docker deployment documented, and this changelog replaces
`VersionHistory.md`.

## 0.9.1 - 2026-11-03

Adds `chesssnake play`, an interactive terminal client. It is the third way to
drive the backend, alongside direct REST calls and the Python client, and is
built on the existing client so one loop plays both a local in-memory game
(`--local`, no server and no extra dependencies) and a game on an api-endpoint.

While idle it polls for the opponent's move every 10 seconds (`--refresh`), and
every command re-reads the server first, so the board is never stale. It
refuses to act from a game superseded by a rematch, because the server's
mutating routes act on whichever generation is current.

Also adds `engine/text.py`, a dependency-free text board renderer.

## 0.9.0 - 2026-08-05

**Breaking.** SQLite support, by moving the database layer to SQLAlchemy Core.
The backend is chosen by the `database.url` scheme. The query functions became
backend-agnostic Core expressions over a single schema definition, leaving only
genuine dialect differences per backend. SQLite is configured for concurrent
use: WAL, a busy timeout, and `BEGIN IMMEDIATE` for read-modify-writes, since
it has no row locks and SQLAlchemy silently drops `FOR UPDATE` there.

**Migration:** `chesssnake[api]` no longer installs psycopg2, so PostgreSQL
users need `chesssnake[api,postgres]`; only URL connection strings are accepted;
`db/sql.py` is gone. Existing PostgreSQL databases need no migration, which a
test proves by building both schemas and comparing reflections.

Engine fix: checkmate is now "in check with no legal move" rather than a
separate hand-rolled analysis, which had mis-reported scholar's mate as check.
Pinned pieces are excluded from checkmate and stalemate detection.

## 0.8.0 - 2026-08-04

**Breaking.** Centralised configuration. One schema is the single source of
truth for every setting, resolved through four layers (CLI flag, environment
variable, TOML file, default), with environment variable names derived from the
schema. `chesssnake config show` reports each value and the layer it came from.

Authentication is now explicit (`api.require_auth`) and fails at startup if
enabled without a key. The server became an app factory, `create_app(settings)`.

**Migration:** every environment variable is renamed. `CHESSDB_*` collapse into
`CHESSSNAKE__DATABASE__URL`, and an API key now also needs
`CHESSSNAKE__API__REQUIRE_AUTH=1` or auth stays off. Python 3.10 is dropped.

## 0.7.1 - 2026-07-09

The engine's in-memory state now matches FEN exactly: en passant is stored as
an algebraic target square and castling rights as a rights string, as the
single source of truth. All six FEN fields are exposed as `Game` accessors.
Accepts `O-O` as well as `0-0`. Fixes a castling bug that checked the wrong rook.

## 0.7.0 - 2026-07-09

Adds the REST api-endpoint, and makes it authoritative: the server runs the
chess engine, so clients send moves and cannot cheat, and a frontend in any
language needs no chess logic.

Adopts standard FEN as the board format, and adds resignation, automatic
draw detection (threefold, fifty-move, insufficient material, stalemate), PGN
export, legal-move listing, per-player move authorisation, optimistic
concurrency through a version counter, per-game generations for rematches with
a readable archive, head-to-head records, and single-perspective board images.

## 0.6.7 - 2026-07-09

Packaging moved to uv and `pyproject.toml`, dropping end-of-life Python 3.9.
Repairs the PostgreSQL layer, fixes engine bugs (en passant, back-rank mate,
checkmate notation), and adds the unit and integration test suites.

## 0.6.6 - 2025-02-16

PostgreSQL fixes for the 0.6.0 schema overhaul.

## 0.6.0 - 2025-02-08

PostgreSQL SQL utilities and a schema overhaul.

## 0.5.0 - 2025-01-05

Major PostgreSQL changes.

## 0.4.0 - 2025-01-05

First documentation release.

## 0.3.1 - 2024-12-21

First release to PyPI, plus bug fixes.

## 0.3.0 - 2024-12-21

Bug fixes and refactoring in the PostgreSQL layer.

## 0.2.0 - 2024-12-21

Bug fixes and refactoring in the chess library.

## 0.1.0 - 2024-12-18

Initial pre-release.
