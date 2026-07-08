"""Unit tests for coordinate <-> notation conversion and the Square class."""


from chesssnake.engine import Board, Square


def test_get_coords_known_squares():
    assert Board.get_coords("a8") == (0, 0)
    assert Board.get_coords("h1") == (7, 7)
    assert Board.get_coords("e4") == (4, 4)
    assert Board.get_coords("e1") == (7, 4)


def test_get_c_notation_known_squares():
    assert Board.get_c_notation(0, 0) == "a8"
    assert Board.get_c_notation(7, 7) == "h1"
    assert Board.get_c_notation(4, 4) == "e4"


def test_coords_notation_round_trip_all_squares():
    for i in range(8):
        for j in range(8):
            c = Board.get_c_notation(i, j)
            assert Board.get_coords(c) == (i, j)


def test_square_c_notation_and_color():
    # a8 is a light square in this library's convention (color 0); a1 is dark.
    assert Square(0, 0).c_notation == "a8"
    assert Square(7, 4).c_notation == "e1"
    assert Square(0, 0).color == 0
    assert Square(7, 0).color == 1


def test_square_equality_is_by_coordinates():
    assert Square(3, 5) == Square(3, 5)
    assert Square(3, 5) != Square(5, 3)
    assert (Square(0, 0) == None) is False  # noqa: E711 - exercises __eq__ with None
