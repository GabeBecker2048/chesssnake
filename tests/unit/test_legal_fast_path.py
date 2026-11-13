"""The pin-based legality test must agree with the trial-by-move reference everywhere.

``Board._legal()`` decides legality from pins computed once per position;
``Board._legal_by_trial()`` plays every candidate and looks. They must list the same
moves in every position: the random games walk through ordinary play, checks and
pins, and the fixed positions aim at the cases a pin-based test can get wrong.
"""

import random

import pytest

from chesssnake.engine import Board

from .test_perft import KIWIPETE, POS3, POS4, POS5, POS6, START

TRICKY = [
    START,
    KIWIPETE,
    POS3,
    POS4,
    POS5,
    POS6,
    # a bishop pinned on a diagonal may slide along it and capture the pinner, nothing else
    "4k3/8/8/1b6/8/3B4/8/5K2 w - - 0 1",
    # a rook pinned on a file may move along the file only
    "4r1k1/8/8/8/8/8/4R3/4K3 w - - 0 1",
    # a pawn pinned on a file may still push, not capture
    "4r1k1/8/8/8/3n4/4P3/8/4K3 w - - 0 1",
    # a pawn pinned on a diagonal may capture the pinner only
    "4k3/8/8/8/8/2b5/3P4/4K3 w - - 0 1",
    # en passant that would uncover a check along the rank (two pawns leave it)
    "8/8/8/K2pP2r/8/8/8/4k3 w - d6 0 1",
    # en passant that removes the checking pawn
    "8/8/8/3pP3/4K3/8/8/7k w - d6 0 1",
    # double check: only the king may move
    "4k3/8/8/8/1b6/8/4r3/4K3 w - - 0 1",
    # the king may not step back along the line of the rook checking it
    "4k3/8/8/8/8/8/8/r3K3 w - - 0 1",
    # castling with the crossed square attacked, and with the destination attacked
    "4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1",
    "4kr2/8/8/8/8/8/8/R3K2R w KQ - 0 1",
    "4k1r1/8/8/8/8/8/8/R3K2R w KQ - 0 1",
    # two own pieces on the line: neither is pinned
    "4r1k1/8/8/8/4N3/8/4B3/4K3 w - - 0 1",
]


def _agree(board, where):
    fast, trial = board._legal(), board._legal_by_trial()
    assert len(fast) == len(set(fast)), f"{where}: a move listed twice"
    assert set(fast) == set(trial), f"{where}: {board.fen}"
    assert board._has_legal_move() == bool(trial), where


@pytest.mark.parametrize("fen", TRICKY)
def test_fixed_positions(fen):
    _agree(Board(fen), fen)


@pytest.mark.parametrize("seed", range(40))
def test_random_games(seed):
    rng = random.Random(seed)
    board = Board()
    for ply in range(250):
        _agree(board, f"seed {seed}, ply {ply}")
        moves = board.legal_moves()
        if not moves or board.status != 0:
            return
        board.move(rng.choice(moves)["san"])
