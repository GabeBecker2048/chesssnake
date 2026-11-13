# Engine benchmarks

How long the engine takes for the operations that cost a server CPU time. Measured
with `scripts/bench_engine.py`, which uses only the `Game` API every release has, so
any two versions can be compared on the same machine:

```commandline
uv run python scripts/bench_engine.py                     # this checkout
uv run --no-project --python 3.12 --with chesssnake==0.14.4 \
    python scripts/bench_engine.py                        # a published version
```

Absolute numbers depend on the machine. Compare versions on one machine, with the
same Python and the same Pillow (rendering speed varies a lot between Pillow
releases).

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
