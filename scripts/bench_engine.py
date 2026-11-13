#!/usr/bin/env python3
"""Benchmark the chess engine.

    uv run python scripts/bench_engine.py

Measures the operations that cost a server CPU time: listing legal moves, playing
a move (which includes detecting checkmate, stalemate and the other endings), and
rendering a PNG. It uses only the ``Game`` API that every release since 0.9 has,
so the same script measures an older version for comparison:

    uv run --no-project --python 3.12 --with chesssnake==0.14.4 python scripts/bench_engine.py

Results are recorded in docs/benchmarks.md. Numbers depend on the machine: compare
two versions on the same one.
"""

import platform
import random
import statistics
import sys
import time
from importlib.metadata import version

from chesssnake.engine import Game
from chesssnake.engine.errors import ChessError

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"


def per_call_ms(fn, min_seconds=1.0):
    """Median milliseconds per call over at least ``min_seconds`` of 5 rounds."""
    fn()  # warm up
    calls = 1
    while True:
        t = time.perf_counter()
        for _ in range(calls):
            fn()
        if time.perf_counter() - t >= min_seconds / 5:
            break
        calls *= 2
    rounds = []
    for _ in range(5):
        t = time.perf_counter()
        for _ in range(calls):
            fn()
        rounds.append((time.perf_counter() - t) / calls * 1000)
    return statistics.median(rounds)


def move_timings(games=20, plies=120, seed=0):
    """Milliseconds for each Game.move() over seeded random games."""
    rng = random.Random(seed)
    times = []
    for _ in range(games):
        game = Game.from_fen(START)
        for _ in range(plies):
            if game.is_over:
                break
            san = rng.choice(game.legal_moves())["san"]
            t = time.perf_counter()
            try:
                game.move(san)
            except ChessError:
                # 0.14.4 and earlier list some moves their own parser refuses
                # (e.g. "Rhxh7"); skip them so old versions can be measured too
                continue
            times.append((time.perf_counter() - t) * 1000)
    return times


def main():
    print(f"chesssnake {version('chesssnake')}, Python {platform.python_version()}, {platform.machine()}")
    start, kiwipete = Game.from_fen(START), Game.from_fen(KIWIPETE)
    rows = [
        ("legal_moves(), start position", per_call_ms(start.legal_moves)),
        ("legal_moves(), Kiwipete", per_call_ms(kiwipete.legal_moves)),
    ]
    times = sorted(move_timings())
    rows.append(("Game.move(), random games: mean", statistics.fmean(times)))
    rows.append(("Game.move(), random games: median", statistics.median(times)))
    rows.append(("Game.move(), random games: p95", times[int(len(times) * 0.95)]))
    try:
        game = Game.from_fen(KIWIPETE)
        rows.append(("render() PNG, wide view", per_call_ms(game.render)))
    except ImportError:  # pragma: no cover - Pillow is a core dependency
        pass
    width = max(len(name) for name, _ in rows)
    for name, ms in rows:
        print(f"  {name:<{width}}  {ms:8.3f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
