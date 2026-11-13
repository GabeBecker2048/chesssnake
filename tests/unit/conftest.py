"""Shared helpers for engine unit tests."""

import pytest

from chesssnake.engine import Board, Color, Piece


def _make_board(pieces, en_passant=None, castling=False, turn=Color.WHITE):
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
    :param turn: the side to move (``Game(board=..., turn=...)`` can also set it).
    """
    grid = [None] * 64
    for (i, j), token in pieces.items():
        letter = token[0] if token[1] == "0" else token[0].lower()
        grid[i * 8 + j] = Piece.from_symbol(letter)
    return Board._from_grid(grid, turn=turn, en_passant=en_passant, castling="KQkq" if castling else "")


@pytest.fixture
def make_board():
    """Fixture exposing the board-construction helper to tests."""
    return _make_board
