"""Shared helpers for engine unit tests."""

import pytest

from chesssnake.engine import Board, Square
from chesssnake.engine.pieces import Bishop, King, Knight, Pawn, Queen, Rook

_PIECE_CLASSES = {"R": Rook, "N": Knight, "B": Bishop, "Q": Queen, "K": King, "P": Pawn}


def _make_board(pieces, en_passant=None, castling=False):
    """
    Build a ``Board`` from a sparse piece layout.

    :param pieces: dict mapping ``(i, j)`` board coordinates to a 2-char token such
        as ``"K0"`` (white king) or ``"Q1"`` (black queen). ``i`` is the row
        (0 = rank 8, 7 = rank 1), ``j`` is the file (0 = 'a', 7 = 'h').
    :param en_passant: optional FEN en-passant target square (algebraic string, e.g.
        ``"e3"``) for a pending en-passant capture.
    :param castling: if ``True``, the board is given full FEN castling rights (so
        castling is possible for correctly-placed home kings/rooks). Defaults to
        ``False`` — no castling rights, which avoids accidental castling in
        constructed positions.
    """
    grid = [[Square(i, j) for j in range(8)] for i in range(8)]
    for (i, j), token in pieces.items():
        cls = _PIECE_CLASSES[token[0]]
        color = int(token[1])
        grid[i][j] = Square(i, j, piece=cls(color))
    return Board(board=grid, en_passant=en_passant, castling="KQkq" if castling else "")


@pytest.fixture
def make_board():
    """Fixture exposing the board-construction helper to tests."""
    return _make_board
