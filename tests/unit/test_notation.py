"""Unit tests for move-string syntax validation (SAN and UCI)."""

import pytest

from chesssnake.engine._notation import is_valid_notation as valid


@pytest.mark.parametrize(
    "move",
    [
        "e4",
        "d5",
        "a3",
        "h6",  # simple pawn pushes
        "Nf3",
        "Nc6",
        "Bb5",
        "Qh4",
        "Ke2",
        "Ra1",  # piece moves
        "exd5",
        "Nxe5",
        "Qxf7",
        "Bxc6",  # captures
        "Rad1",
        "R1a3",
        "Nbd2",  # disambiguation (file / rank)
        "e8Q",
        "b8N",
        "exd8Q",  # promotions (concatenated piece letter)
        "0-0",
        "0-0-0",  # castling (zeros)
        "O-O",
        "O-O-O",  # castling (letter O — equivalent to zeros)
        "Nf3+",
        "Qh4#",  # check / checkmate annotations
        "e8=Q",
        "exd8=N+",  # promotions written with "=" (as PGN does)
        "Nexg4",
        "Qh4xe1",  # disambiguation together with a capture
        "e2e4",
        "e7e8q",
        "e1g1",  # UCI
        " e4 ",  # surrounding whitespace
    ],
)
def test_valid_notation_accepted(move):
    assert valid(move) is True


@pytest.mark.parametrize(
    "move",
    [
        "",  # empty
        "e",  # too short
        "e9",  # rank out of range
        "i4",  # file out of range
        "Xf3",  # bogus piece letter
        "Zz9",  # nonsense
        "e2e4e5",  # three squares glued together
        "e8=",  # "=" with no piece
        "e8=K",  # cannot promote to a king
        "e7e8k",  # nor in UCI
        "Nf3++",  # one suffix at most
        "Nf9",  # invalid rank on a piece move
    ],
)
def test_invalid_notation_rejected(move):
    assert valid(move) is False


def test_checkmate_annotation_is_valid():
    # Regression: stripping '#' must keep the move, not collapse it to "#".
    assert valid("Qh4#") is True
    assert valid("Qxf7#") is True
