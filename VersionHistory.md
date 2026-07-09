# Project Version History

_Note: Some minor versions are missing (e.g., documentation only updates, minor bug fixes). These "missing" updates were deemed too inconsequential to include_

| Version | Release Date | Changes/Notes                                      | Author        | Status   |
|---------|--------------|----------------------------------------------------|---------------|----------|
| 0.1.0   | 2024-12-18   | Initial pre-release                                | Gabe Becker   | Released |
| 0.2.0   | 2024-12-21   | bug fixes and refactoring (chesslib)               | Gabe Becker   | Released |
| 0.3.0   | 2024-12-21   | bug fixes and refactoring (postgres)               | Gabe Becker   | Released |
| 0.3.1   | 2024-12-21   | Initial release to pypi; bug fixes                 | Gabe Becker   | Released |
| 0.4.0   | 2025-01-05   | Initial documentation release                      | Gabe Becker   | Released |
| 0.5.0   | 2025-01-05   | Major PostgreSql changes                           | Gabe Becker   | Released |
| 0.6.0   | 2025-02-08   | PostgreSql SQL_Utils and schema overhall           | Gabe Becker   | Released |
| 0.6.6   | 2025-02-16   | PostgreSql Major fixes to adjust to schema overall | Gabe Becker   | Released |
| 0.6.7   | 2026-07-07   | Migrated packaging to uv/pyproject (dropped EOL Python 3.9), repaired the PostgreSQL layer, and fixed chesslib bugs (en passant, back-rank mate, checkmate notation); added unit and integration test suites | Gabe Becker | Released |
| 0.7.0   | 2026-07-08   | Add REST API / api-endpoint — server-authoritative: the api-endpoint runs the chess engine (validates/applies moves, stores state), clients just send moves over REST (any-language frontends, anti-cheat). Adopt standard FEN as the board format; add resignation, automatic draw-by-rule detection (threefold / fifty-move / insufficient material / stalemate), move history + PGN export, legal-move listing, per-player move authorization, optimistic-concurrency versioning, per-game generations (rematches + a readable archive of finished games), head-to-head records, and single-perspective board images | Gabe Becker | Released |
| 0.7.1   | 2026-07-08   | Align the engine's in-memory state with FEN: en passant and castling rights are now stored in FEN's own form (an algebraic target square and a rights string) as the single source of truth; accept `O-O`/`O-O-O` as well as `0-0`/`0-0-0`; expose all six FEN fields as first-class `Game` accessors (`fen`, `to_move`, `castling_rights`, `en_passant`, `halfmove_clock`, `fullmove_number`); fix a castling bug that checked the wrong rook | Gabe Becker | Latest   |

# Planned Releases

| Version | Planned Release Date | Changes/Notes                                                    | Author      | Status      |
|---------|----------------------|------------------------------------------------------------------|-------------|-------------|
| 0.8.0   | TBD                  | Add SQL Lite support                                            | Gabe Becker | Planned     |
| 0.9.0   | TBD                  | Performance improvements and optimizations, finish documentation | Gabe Becker | Planned     |
| 0.10.0  | TBD                  | Staging for full release, documentation full release             | Gabe Becker | Planned     |
| 1.1.0   | TBD                  | First major stable release with full features                    | Gabe Becker | Planned     |
| 2.1.0   | TBD                  | AI/Stockfish support                                             | Gabe Becker | Planned     |