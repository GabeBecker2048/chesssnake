# Roadmap

What is planned, newest first. Dates are intentions, not commitments, and the
contents of a version may change before it ships. Shipped versions are in
[CHANGELOG.md](CHANGELOG.md).

## 2.0.0 - planned

Engine opponents: Stockfish and built-in AI play.

## 1.0.0 - planned

- First stable, recommended, non-alpha release. 
- This release will have minimal code changes, bug fixes at most
- The major change will be a lot of documentation, addition of a wiki, and an official release

## 0.12.0 - likely

- tagged as "likely": this version will only be released if fixed before release are required.
- Intermediate version to fix any last bugs or add any last optimizations before the v1 release.
- Last possible chance for large API changes. 
  The next time a large API refactor needs to happen that breaks backwards compatibility, it will require a major version bump.

## 0.11.0 - planned

- Major database refactor (e.g., adding `users` and `finished_games` tables), API auth replanning, websocket support
- possible web UI frontend addition (vibe coded as h*ll)

## 0.10.0 - planned

- Move the database-touching API routes off `async def` so they
  run in the threadpool. They currently block the event loop, so the server
  handles one database operation at a time.
