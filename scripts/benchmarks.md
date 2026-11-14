# Benchmarks

How long chesssnake takes for the operations that cost a server CPU time. Three
scripts, newest results first below:

- `scripts/bench_engine.py`: the engine alone. Uses only the `Game` API every
  release has, so any two versions can be compared on the same machine.
- `scripts/bench_vs_python_chess.py`: the engine against python-chess (a dev-only
  dependency, used as a reference and never imported by chesssnake itself).
- `scripts/bench_server.py`: a running api-endpoint over real HTTP, as a player or a
  bot uses it. Start a server with open registration on a throwaway database first
  (the script's help says how).

```commandline
uv run python scripts/bench_engine.py                     # this checkout
uv run --no-project --python 3.12 --with chesssnake==0.14.4 \
    python scripts/bench_engine.py                        # a published version
uv run python scripts/bench_vs_python_chess.py
uv run python scripts/bench_server.py http://127.0.0.1:8123
```

Absolute numbers depend on the machine. Compare versions on one machine, with the
same Python and the same dependencies: rendering speed in particular varies a lot
between Pillow releases. To compare against an older release with identical
dependencies, run it from a git worktree of its tag (`git worktree add ../old
v0.15.0`, then `uv run --project ../old ...`).

## 0.15.1

Intel Core i7-8550U (laptop, 1.8 GHz), Python 3.12.13, Pillow 12.3.0, FastAPI
0.139.0, SQLite, 2026-11-13. 0.15.0 was run from a worktree of its tag, so both
versions used the same locked dependencies. Times are milliseconds, the mean of two
runs each.

### The engine

| Operation | 0.15.0 | 0.15.1 | Change |
|---|---:|---:|---:|
| `legal_moves()`, start position | 0.085 | 0.027 | 3.2x faster |
| `legal_moves()`, Kiwipete | 0.222 | 0.081 | 2.7x faster |
| `Game.move()`, random games: mean | 0.173 | 0.082 | 2.1x faster |
| `Game.move()`, random games: p95 | 0.273 | 0.137 | 2.0x faster |
| `render()` PNG, wide view | 26.6 | 13.8 | 1.9x faster |
| Perft, positions per second | 270k | 1.35M | 5x more |

Legality is now decided from the pins, worked out once per position, instead of by
playing every candidate move and taking it back (that test was 85% of the time),
and lookups no longer hash enums. Rendering no longer decodes the board and
template images on every call.

### Against python-chess 1.11.2

| Operation | chesssnake 0.15.1 | python-chess | |
|---|---:|---:|---|
| Legal moves, raw, start position | 0.0135 | 0.027 | chesssnake 2.0x faster |
| Legal moves, raw, Kiwipete | 0.032 | 0.058 | chesssnake 1.8x faster |
| Legal moves with notation, start position | 0.026 | 0.207 | chesssnake 8x faster |
| Legal moves with notation, Kiwipete | 0.081 | 0.73 | chesssnake 9x faster |
| Perft, start position depth 4 | 1.24M/s | 0.53M/s | chesssnake 2.3x faster |
| Perft, Kiwipete depth 3 | 1.45M/s | 0.70M/s | chesssnake 2.1x faster |
| Play a move, including detecting the end of the game | 0.113 | 0.30 | chesssnake 2.7x faster |

On 0.15.0 the raw numbers ran the other way (python-chess 2.4x faster at perft).
Two things favour chesssnake in this comparison and are worth knowing: python-chess
builds a `Move` object per move and keeps a full move stack, where chesssnake uses
plain tuples; and python-chess's notation adds the `+`/`#` suffix to every move,
which means playing it, while chesssnake's listed notation has no suffix.

### The server, over HTTP

| Request | 0.15.0 | 0.15.1 | Change |
|---|---:|---:|---:|
| `POST /moves` | 4.32 | 4.16 | about the same |
| `GET /legal-moves` | 2.44 | 2.16 | 11% faster |
| `GET /image`, first view of a position | 67.4 | 43.6 | 35% faster |
| `GET /image`, repeat view | 66.6 | 2.1 | 31x faster |
| Server time per turn in the web UI, websockets on | 6.76 | 4.16 | 38% less, one request instead of two |

A move response now also computes the next player's legal moves, which the faster
engine pays for. The websocket `game` event carries those moves, so in the web UI
the player to move no longer asks for them: each turn costs one request instead of
two. Server images are cached by everything they show (position, names, side), so a
repeat view skips rendering and encoding; a first view saves the image decode and
encodes at PNG level 1 (about 10% larger files).

## 0.15.0

Intel Core i7-8550U (laptop, 1.8 GHz), Python 3.12.13, Pillow 12.3.0, 2026-11-12.
Times are per call, in milliseconds.

| Operation | 0.14.4 | 0.15.0 | Speedup |
|---|---:|---:|---:|
| `legal_moves()`, start position | 19.8 | 0.089 | 220x |
| `legal_moves()`, Kiwipete (48 moves) | 38.6 | 0.227 | 170x |
| `Game.move()`, random games: mean | 1.76 | 0.179 | 10x |
| `Game.move()`, random games: median | 0.83 | 0.172 | 5x |
| `Game.move()`, random games: p95 | 5.31 | 0.263 | 20x |
| `render()` PNG, wide view | 28.9 | 26.3 | unchanged |

`Game.move()` includes detecting checkmate, stalemate and the other endings after
the move. The speedup comes from generating moves from precomputed tables and
testing each one by playing it in place and taking it back, where 0.14.4 copied the
whole board for every candidate move and wrote and re-parsed its notation.

Rendering was not changed in 0.15.0 and is now the most expensive engine operation
by far; with Pillow 13.0.0 the same render took about 45 ms.
