"""Shared helpers for engine unit tests."""

import pytest

from chesssnake.engine import Board, Square
from chesssnake.engine.pieces import Bishop, King, Knight, Pawn, Queen, Rook

_PIECE_CLASSES = {"R": Rook, "N": Knight, "B": Bishop, "Q": Queen, "K": King, "P": Pawn}


def _make_board(pieces, two_moveP=None, castling=False):
    """
    Build a ``Board`` from a sparse piece layout.

    :param pieces: dict mapping ``(i, j)`` board coordinates to a 2-char token such
        as ``"K0"`` (white king) or ``"Q1"`` (black queen). ``i`` is the row
        (0 = rank 8, 7 = rank 1), ``j`` is the file (0 = 'a', 7 = 'h').
    :param two_moveP: optional ``Square`` for a pending en-passant target.
    :param castling: if ``True``, home-square kings/rooks are left un-moved (so
        castling is possible). Defaults to ``False`` — all kings/rooks are marked
        moved, which avoids accidental castling in constructed positions.
    """
    grid = [[Square(i, j) for j in range(8)] for i in range(8)]
    for (i, j), token in pieces.items():
        cls = _PIECE_CLASSES[token[0]]
        color = int(token[1])
        if cls in (Rook, King):
            piece = cls(color, moved=not castling)
        else:
            piece = cls(color)
        grid[i][j] = Square(i, j, piece=piece)
    return Board(board=grid, two_moveP=two_moveP)


@pytest.fixture
def make_board():
    """Fixture exposing the board-construction helper to tests."""
    return _make_board
