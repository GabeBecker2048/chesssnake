# Roadmap

What is planned, newest first. Dates are intentions, not commitments, and the
contents of a version may change before it ships. Shipped versions are in
[CHANGELOG.md](CHANGELOG.md).

## 2.0.0 - planned

- Engine opponents: Stockfish and built-in AI play.

## 1.0.0 - planned

- First stable, recommended, non-alpha release.
- Minimal code changes, bug fixes at most.
- The real work is documentation, a wiki, and an official release.

## 0.15.0 - likely

- Tagged "likely": only released if fixes turn out to be needed before 1.0.0.
- Last bugs and optimizations before the stable release.
- Last chance for large API changes. After this, a refactor that breaks
  backwards compatibility needs a major version bump.

## 0.14.0 - possible

- Web UI frontend (vibe coded as h*ll).
- Depends on auth and websockets being settled, so it comes after both.

## 0.13.0 - planned

- WebSocket support, so a client learns of the opponent's move without polling.
- Opt-in and disabled by default; the REST contract does not change.
- Designed in `docs/realtime-websockets.md`.

## 0.12.0 - planned

- Auth rework, built on the `users` table from 0.11.0.
- Replaces the single shared API key with real per-user identity.

## 0.11.0 - planned

- Database refactor: add `users` and `finished_games` tables.

## 0.10.0 - planned

- Move the database-touching API routes off `async def` so they run in the
  threadpool. They currently block the event loop, so the server handles one
  database operation at a time.
