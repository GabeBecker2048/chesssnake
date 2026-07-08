"""Unit tests for algebraic-notation syntax validation (Move.is_valid_c_notation)."""

import pytest
from chesssnake.chesslib.Chess import Move

valid = Move.is_valid_c_notation


@pytest.mark.parametrize("move", [
    "e4", "d5", "a3", "h6",          # simple pawn pushes
    "Nf3", "Nc6", "Bb5", "Qh4", "Ke2", "Ra1",  # piece moves
    "exd5", "Nxe5", "Qxf7", "Bxc6",  # captures
    "Rad1", "R1a3", "Nbd2",          # disambiguation (file / rank)
    "e8Q", "b8N", "exd8Q",           # promotions (concatenated piece letter)
    "0-0", "0-0-0",                  # castling
    "Nf3+", "Qh4#",                  # check / checkmate annotations
])
def test_valid_notation_accepted(move):
    assert valid(move) is True


@pytest.mark.parametrize("move", [
    "",             # empty
    "e",            # too short
    "e9",           # rank out of range
    "i4",           # file out of range
    "Xf3",          # bogus piece letter
    "O-O",          # castling must use zeros, not letter O
    "Zz9",          # nonsense
    "e4e5",         # two squares glued together
    "Nf9",          # invalid rank on a piece move
])
def test_invalid_notation_rejected(move):
    assert valid(move) is False


def test_checkmate_annotation_is_valid():
    # Regression: stripping '#' must keep the move, not collapse it to "#".
    assert valid("Qh4#") is True
    assert valid("Qxf7#") is True
