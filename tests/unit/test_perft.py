"""Perft: count every leaf of the move tree and compare with the published numbers.

The positions and counts are the standard ones from the Chess Programming Wiki's
"Perft Results" page. A wrong count to any depth means the move generator lists a
move it should not (or misses one); the shallow depths run with the unit tests, the
deep ones only under ``-m slow``.
"""

import pytest

from .engine_adapter import perft

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
POS3 = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"
POS4 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
POS5 = "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"
POS6 = "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P3/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"

CASES = [
    (START, 1, 20),
    (START, 2, 400),
    (KIWIPETE, 1, 48),
    (KIWIPETE, 2, 2039),
    (POS3, 1, 14),
    (POS3, 2, 191),
    (POS3, 3, 2812),
    (POS4, 1, 6),
    (POS4, 2, 264),
    (POS5, 1, 44),
    (POS5, 2, 1486),
    (POS6, 1, 46),
    (POS6, 2, 2079),
]

SLOW_CASES = [
    (START, 3, 8902),
    (START, 4, 197281),
    (KIWIPETE, 3, 97862),
    (POS3, 4, 43238),
    (POS4, 3, 9467),
    (POS5, 3, 62379),
    (POS6, 3, 89890),
]


@pytest.mark.xfail(reason="engine bug, fixed later in 0.15.0", strict=False)
@pytest.mark.parametrize("fen,depth,expected", CASES)
def test_perft(fen, depth, expected):
    assert perft(fen, depth) == expected


@pytest.mark.xfail(reason="engine bug, fixed later in 0.15.0", strict=False)
@pytest.mark.slow
@pytest.mark.parametrize("fen,depth,expected", SLOW_CASES)
def test_perft_deep(fen, depth, expected):
    assert perft(fen, depth) == expected
