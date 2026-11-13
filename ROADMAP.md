# Roadmap

What is planned, newest first. Dates are intentions, not commitments, and the
contents of a version may change before it ships. Shipped versions are in
[CHANGELOG.md](CHANGELOG.md).

## 2.0.0 - planned

- Engine opponents: Stockfish and built-in AI play.

## 1.x - planned

- Move responses include the next position's legal moves, saving the web UI a
  second request every turn.
- An in-process cache keyed by position for legal moves and board images, with
  SVG rendering alongside PNG.
- Live updates across several processes on PostgreSQL (`LISTEN`/`NOTIFY`),
  removing the one-process limit.
- A published load test with players-per-core numbers, and a scaling guide
  explaining where the project deliberately stops.
- Real PGN import: multi-game files, with comments and variations skipped.

## 1.0.0 - planned

- First stable, recommended, non-alpha release.
- Minimal code changes, bug fixes at most.
- The real work is documentation, a wiki, and an official release.

## 0.16.0 - planned

- A bitboard engine behind the public API frozen in 0.15.0, for speed close to
  python-chess.
- Released only once it passes the full perft suite and the differential tests.
- Soaks as 0.16.x before 1.0.0; nothing above the engine changes.

## 0.15.0 - planned

- Rules fixes: no castling out of check or through an attacked square.
- Move input accepts `Nexg4`-style disambiguated captures, `e8=Q`, and UCI
  strings such as `e2e4`, so exported PGN reads back in.
- Verification: a perft suite, differential tests against python-chess (test
  only), round-trip tests, and a benchmark script.
- Legal-move generation about 20 to 50 times faster, without the board copy per
  candidate move.
- A smaller, stable public engine API: a standalone `Board` with query methods
  and immutable pieces, with squares and piece classes made private.
- Last chance for large API changes. After this, a refactor that breaks
  backwards compatibility needs a major version bump.

## Not planned

- Redis as a required service, Kubernetes, or sharding: the wrong scale for a
  self-hosted, one-container server.
- Chess variants, tablebases, opening books and EPD.
