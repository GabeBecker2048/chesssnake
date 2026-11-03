# Roadmap

What is planned, newest first. Dates are intentions, not commitments, and the
contents of a version may change before it ships. Shipped versions are in
[CHANGELOG.md](CHANGELOG.md).

## 2.1.0 - planned

Engine opponents: Stockfish and built-in AI play.

## 1.1.0 - planned

First stable release. The public API stops changing without a major version.

## 0.11.0 - planned

Release staging and the full documentation set.

## 0.10.0 - planned

Performance work, and finishing the documentation.

The main item: move the database-touching API routes off `async def` so they
run in the threadpool. They currently block the event loop, so the server
handles one database operation at a time.
