"""Square names (internal numbering) and the public `Piece` value."""

import pytest

from chesssnake.engine import Color, Piece, PieceType
from chesssnake.engine._notation import index, name


def test_index_known_squares():
    assert index("a8") == 0
    assert index("h8") == 7
    assert index("a1") == 56
    assert index("h1") == 63
    assert index("e4") == 36


def test_name_index_round_trip_all_squares():
    for idx in range(64):
        assert index(name(idx)) == idx


@pytest.mark.parametrize("bad", ["", "e9", "i4", "E4", "e44", None])
def test_index_rejects_non_squares(bad):
    with pytest.raises(ValueError):
        index(bad)


def test_piece_is_a_value():
    assert Piece(PieceType.KNIGHT, Color.WHITE) == Piece(PieceType.KNIGHT, Color.WHITE)
    assert Piece(PieceType.KNIGHT, Color.WHITE) != Piece(PieceType.KNIGHT, Color.BLACK)
    assert len({Piece(PieceType.KNIGHT, Color.WHITE), Piece(PieceType.KNIGHT, Color.WHITE)}) == 1
    with pytest.raises(AttributeError):
        Piece(PieceType.KNIGHT, Color.WHITE).color = Color.BLACK  # type: ignore[misc]


def test_piece_symbols():
    assert Piece(PieceType.QUEEN, Color.WHITE).symbol == "Q"
    assert Piece(PieceType.QUEEN, Color.BLACK).symbol == "q"
    assert Piece.from_symbol("n") == Piece(PieceType.KNIGHT, Color.BLACK)
    assert str(Piece.from_symbol("K")) == "K"
    with pytest.raises(ValueError):
        Piece.from_symbol("x")
