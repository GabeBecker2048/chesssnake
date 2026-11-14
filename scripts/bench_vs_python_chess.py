#!/usr/bin/env python3
"""Compare the engine's speed with python-chess.

    uv run python scripts/bench_vs_python_chess.py

python-chess is a dev dependency (GPL-3.0), used here and in the differential
tests only as a reference; nothing under src/ imports it. This script reaches into
the engine's private ``Board._legal``/``_make``/``_unmake`` to time raw move
generation the way python-chess's own move generator is timed: that is a dev-only
measurement, not something callers should do.

Four measurements, each run on both engines:

- listing the legal moves, raw (moves only) and with notation, which is what
  chesssnake's ``legal_moves()`` and its REST route return;
- perft (counting every position a few moves deep), in positions per second;
- playing a move, including working out whether the game ended.

Results are recorded in scripts/benchmarks.md.
"""

import platform
import random
import statistics
import sys
import time
from importlib.metadata import version

try:
    import chess
except ImportError:  # pragma: no cover - dev-only script
    sys.exit("python-chess is not installed: run `uv sync` (it is in the dev group)")

from chesssnake.engine import Board, Game

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
POSITIONS = [("start", chess.STARTING_FEN), ("Kiwipete", KIWIPETE)]


def per_call_ms(fn, calls=2000, rounds=7):
    """Median milliseconds per call."""
    for _ in range(calls // 10):
        fn()
    times = []
    for _ in range(rounds):
        t = time.perf_counter()
        for _ in range(calls):
            fn()
        times.append((time.perf_counter() - t) / calls * 1000)
    return statistics.median(times)


def ours_perft(board, depth):
    plies = board._legal()
    if depth == 1:
        return len(plies)
    nodes = 0
    for ply in plies:
        undo = board._make(ply)
        nodes += ours_perft(board, depth - 1)
        board._unmake(ply, undo)
    return nodes


def ref_perft(board, depth):
    if depth == 1:
        return board.legal_moves.count()
    nodes = 0
    for move in board.legal_moves:
        board.push(move)
        nodes += ref_perft(board, depth - 1)
        board.pop()
    return nodes


def main():
    print(
        f"chesssnake {version('chesssnake')} vs python-chess {version('chess')}, "
        f"Python {platform.python_version()}, {platform.machine()}"
    )
    print("\nLegal moves, ms per call:")
    print(
        f"  {'position':10s} {'chesssnake raw':>15s} {'python-chess raw':>17s} {'chesssnake+SAN':>15s} {'python-chess+SAN':>17s}"
    )
    for name, fen in POSITIONS:
        ours, ref = Board(fen), chess.Board(fen)
        raw_ours = per_call_ms(ours._legal)
        raw_ref = per_call_ms(lambda: list(ref.legal_moves))
        san_ours = per_call_ms(ours.legal_moves)
        san_ref = per_call_ms(lambda: [ref.san(m) for m in ref.legal_moves], calls=500)
        print(f"  {name:10s} {raw_ours:15.3f} {raw_ref:17.3f} {san_ours:15.3f} {san_ref:17.3f}")

    print("\nPerft (raw move generation), positions per second:")
    for name, fen, depth in [("start, depth 4", chess.STARTING_FEN, 4), ("Kiwipete, depth 3", KIWIPETE, 3)]:
        t = time.perf_counter()
        n_ours = ours_perft(Board(fen), depth)
        t_ours = time.perf_counter() - t
        t = time.perf_counter()
        n_ref = ref_perft(chess.Board(fen), depth)
        t_ref = time.perf_counter() - t
        assert n_ours == n_ref, (n_ours, n_ref)
        print(
            f"  {name:18s} {n_ours:>7} positions: chesssnake {n_ours / t_ours / 1000:5.0f}k/s, "
            f"python-chess {n_ref / t_ref / 1000:5.0f}k/s"
        )

    print("\nPlay a move, including detecting the end of the game (ms, mean over random games):")
    rng = random.Random(1)
    ours_t, ref_t = [], []
    for _ in range(20):
        game, ref = Game(), chess.Board()
        for _ in range(120):
            if game.is_over:
                break
            move = rng.choice(list(ref.legal_moves))
            san = ref.san(move)
            t = time.perf_counter()
            game.move(san)
            ours_t.append(time.perf_counter() - t)
            t = time.perf_counter()
            ref.push_san(san)
            ref.outcome(claim_draw=True)
            ref_t.append(time.perf_counter() - t)
    print(f"  chesssnake {statistics.fmean(ours_t) * 1000:.3f}, python-chess {statistics.fmean(ref_t) * 1000:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
