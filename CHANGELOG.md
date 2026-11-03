# Changelog

All notable changes, newest first. Versions follow [semantic versioning](https://semver.org/).

Pre-1.0 minor versions may break compatibility; those changes appear under
**Changed** and **Removed**. Some early patch versions are missing: they were
documentation or small fixes. What is planned next is in [ROADMAP.md](ROADMAP.md).

## 0.13.0 - 2026-11-03

### Added
- Live updates over a websocket at `/v1/ws`. A client follows any games it
  likes and is sent each move, draw offer and result the moment it is saved,
  plus its own challenges and new games, instead of polling. Off by default
  (`websocket.enabled`), so REST-only deployments are unaffected.
- A `[websocket]` configuration section to control the load and exposure:
  connection limits overall, per user and before login, subscriptions per
  connection, timeouts, pings and allowed browser origins.
- `chesssnake play` shows the opponent's move as it happens when the server
  offers live updates, and falls back to polling with a note when it does not.
  `--no-live` polls regardless.
- `ApiClient.events()`, a self-reconnecting stream of live updates for Python
  programs.

### Changed
- Logging out, revoking a token, resetting a password or disabling an account
  also closes that login's live connections at once.


### Fixed
- A burst of logins could push the server to its memory limit and keep it
  there. Password checks now run on a small dedicated set of threads, so memory
  stays flat however many people log in at once. Measured after a burst of 40
  logins: about 700 MiB before, 134 MiB after.

## 0.12.0 - 2026-11-03

### Added
- Logins. Users log in with a username and password for a token, and every
  route except logging in now needs one. `chesssnake login` stores the token
  for the terminal client and for `chesssnake.connect()`.
- Two roles, user and administrator. Users play as themselves; administrators
  also manage accounts, create games directly, and can act for any player,
  which is how a bot plays for the people it represents.
- Named api tokens for scripts and bots, and `chesssnake user` commands to set
  passwords, disable accounts and mint a bot's token on the server.
- Open registration, off by default (`api.registration`).

### Changed
- Games start when a challenge is accepted. Challenges now have ids and let the
  challenger pick a colour, and `chesssnake challenge`, `challenges`, `accept`
  and `decline` drive them from the terminal.
- Games are addressed by id everywhere (`/v1/games/{id}/...`); `chesssnake play`
  takes `--game` or `--vs`, and `new` after a game sends or accepts a rematch
  challenge.
- The server refuses to start on a database from an older version instead of
  failing part way through a request. Existing databases must be recreated
  with `chesssnake init-db --drop`.

### Removed
- The shared API key (`api.require_auth`, `api.api_key`, `X-API-Key`).
- The routes that addressed a game by its players, and `generation` in request
  bodies; `GET /v1/games/between` lists the games two players have played.

## 0.11.0 - 2026-11-03

### Added
- User accounts with server-assigned ids and an admin role, managed over the API
  or with the new `chesssnake user` command.
- External ids: a user can be linked to ids from other systems (a Discord id,
  say), and an integration can get or create the user for one of its ids in a
  single call.
- Every game has an id that it keeps after it finishes, readable at
  `GET /v1/games/{id}`.

### Changed
- Players are users. Games are created between user ids, `Game.remote` and
  `chesssnake play` take ids or usernames, and boards and PGN show the
  account's username.
- Game states carry the game's id, players, usernames and timestamps
  (`wname`/`bname` are now `white_name`/`black_name`), and the current-games,
  exists and archive routes return full game states.
- Finished games move to a compact archive, and every action names the game it
  is for, so a client still showing a finished game can no longer play a move
  into the rematch.
- New database schema. Existing databases must be recreated with the new
  `chesssnake init-db --drop`, which deletes their games.

### Removed
- Display names on remote games: `white_name`/`black_name` are gone from
  `POST /v1/games`, `Game.remote` and remote `chesssnake play`. Local games
  keep them.

## 0.10.0 - 2026-11-03

### Changed
- The server now handles requests in parallel. Database and rendering routes
  run in a worker threadpool instead of on the event loop, where each one
  blocked every other request for its whole duration. Measured locally: eight
  concurrent board renders went from 376 ms to 122 ms.
- `/health` still answers on the event loop, so it stays fast when every worker
  is busy. It went from 325 ms under load to 10 ms, which matters because the
  container healthcheck gives it a two second timeout.

### Added
- A `503` response when every database connection is in use, instead of waiting
  thirty seconds and then reporting a generic server error. Nothing is wrong in
  that case, the server is only saturated, and retrying shortly is the right
  answer.

### Fixed
- Creating or reopening a game no longer fails with `database is locked` on
  SQLite while a move is being applied. It read the latest generation and then
  inserted under a deferred transaction, which SQLite refuses to upgrade to a
  writer while another writer holds the lock.
- The PostgreSQL driver is now imported when the engine is built rather than on
  the first write, so a missing or broken driver fails at startup instead of
  part way through serving traffic.

### Removed
- Serving an in-memory SQLite database (`sqlite://`) is refused at startup. It
  cannot be used safely from more than one thread, and it is discarded when the
  process exits. Use a file path.

## 0.9.2 - 2026-11-03

### Added
- Container images on `ghcr.io/gabebecker2048/chesssnake` for linux/amd64 and
  linux/arm64, tagged `X.Y.Z`, `X.Y`, `X` and `latest`.
- `docs/guide.md`: the Python API, running an api-endpoint, the terminal
  client, and Docker deployment.
- `ROADMAP.md`, for planned versions.

### Changed
- Releases are cut by pushing a tag. One workflow builds, publishes to PyPI and
  the registry, then creates the GitHub release from this file's entry.
- Shorter README, with the usage material moved to the guide.
- This changelog replaces `VersionHistory.md`.
- The test suite runs against SQLAlchemy 2.1.

### Removed
- Support for Python 3.11. 3.12 or newer is required.

### Fixed
- PostgreSQL connections on fresh installs. A bare `postgresql://` URL now
  names whichever driver is installed, rather than relying on a SQLAlchemy
  default that changed in 2.1.
- The container failing to start under a `user:` override. Its working
  directory and `HOME` are now `/data`, not an unreadable home directory.

## 0.9.1 - 2026-11-03

### Added
- `chesssnake play`, an interactive terminal client for both local and remote
  games, built on the existing client.
- A text board renderer with no dependencies (`engine/text.py`).

### Changed
- The terminal client polls for the opponent's move while idle, re-reads the
  server before every command, and refuses to act from a game that a rematch
  has superseded.

## 0.9.0 - 2026-08-05

### Added
- SQLite support. The backend is chosen by the `database.url` scheme, and
  SQLite is configured for concurrent use with WAL and immediate transactions.

### Changed
- The database layer moved to SQLAlchemy Core: backend-agnostic queries over
  one schema definition, with only genuine dialect differences per backend.
- `chesssnake[api]` no longer installs psycopg2; PostgreSQL needs
  `chesssnake[api,postgres]`.
- Only URL connection strings are accepted.
- Existing PostgreSQL databases need no migration; the schema is unchanged.

### Removed
- `db/sql.py`, replaced by the Core query layer.

### Fixed
- Checkmate detection, which mis-reported scholar's mate as check.
- Pinned pieces are now excluded from checkmate and stalemate detection.

## 0.8.0 - 2026-08-04

### Added
- Centralised configuration: one schema resolved through four layers (CLI flag,
  environment variable, TOML file, default).
- `chesssnake config show`, reporting each value and the layer it came from.

### Changed
- Authentication is explicit (`api.require_auth`), and enabling it without a
  key fails at startup instead of running open.
- The server is an app factory, `create_app(settings)`.
- Every environment variable is renamed; the `CHESSDB_*` family collapses into
  `CHESSSNAKE__DATABASE__URL`.

### Removed
- Support for Python 3.10.

## 0.7.1 - 2026-07-09

### Added
- All six FEN fields as `Game` accessors.
- `O-O` and `O-O-O` accepted alongside `0-0` and `0-0-0`.

### Changed
- Engine state matches FEN exactly: en passant is an algebraic target square
  and castling rights are a rights string.

### Fixed
- Castling checked the wrong rook.

## 0.7.0 - 2026-07-09

### Added
- The REST api-endpoint, which runs the engine server-side so clients cannot
  cheat and a frontend in any language needs no chess logic.
- Resignation, automatic draw detection, PGN export, legal-move listing,
  head-to-head records, and single-perspective board images.
- Per-game generations, giving rematches and an archive of finished games.
- Optimistic concurrency and per-player move authorisation.

### Changed
- Standard FEN replaces the previous bespoke board format.

## 0.6.7 - 2026-07-09

### Added
- Unit and integration test suites.

### Changed
- Packaging moved to uv and `pyproject.toml`.

### Removed
- Support for Python 3.9.

### Fixed
- The PostgreSQL layer, and engine bugs in en passant, back-rank mate and
  checkmate notation.

## 0.6.6 - 2025-02-16

### Fixed
- The PostgreSQL layer brought in line with the 0.6.0 schema overhaul,
  including the new status column and player id checks.

## 0.6.0 - 2025-02-08

### Changed
- PostgreSQL schema overhaul, with a reworked SQL utility layer.

## 0.5.0 - 2025-01-05

### Added
- Documentation for the PostgreSQL `Game` API.

### Changed
- Reworked the PostgreSQL persistence layer.

## 0.4.0 - 2025-01-05

### Added
- API documentation for the chess library, `Game` and the image renderer.

## 0.3.1 - 2024-12-21

### Added
- First release on PyPI.

### Fixed
- Assorted bug fixes.

## 0.3.0 - 2024-12-21

### Fixed
- Bug fixes and refactoring in the PostgreSQL layer.

## 0.2.0 - 2024-12-21

### Fixed
- Bug fixes and refactoring in the chess library.

## 0.1.0 - 2024-12-18

### Added
- Initial pre-release.
