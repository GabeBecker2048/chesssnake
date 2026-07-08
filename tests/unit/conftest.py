"""Shared helpers for chesslib unit tests."""

import pytest

from chesssnake.chesslib import Chess


def _make_board(pieces, two_moveP=None, moved="111111"):
    """
    Build a ``Chess.Board`` from a sparse piece layout.

    :param pieces: dict mapping ``(i, j)`` board coordinates to a 2-char token
        such as ``"K0"`` (white king) or ``"Q1"`` (black queen). ``i`` is the
        row (0 = rank 8, 7 = rank 1), ``j`` is the file (0 = 'a', 7 = 'h').
    :param two_moveP: optional ``Square`` for a pending en-passant target.
    :param moved: 6-char castling-rights string passed to ``assemble_board``.
        Defaults to "111111" so home-square kings/rooks are treated as moved
        (avoids accidental castling in constructed positions).
    """
    grid = [["--" for _ in range(8)] for _ in range(8)]
    for (i, j), token in pieces.items():
        grid[i][j] = token
    boardstring = ";".join(" ".join(row) for row in grid)
    arr = Chess.Board.assemble_board(boardstring, moved)
    return Chess.Board(board=arr, two_moveP=two_moveP)


@pytest.fixture
def make_board():
    """Fixture exposing the board-construction helper to tests."""
    return _make_board