"""Unit tests for board rendering, including single-perspective images."""

from chesssnake.engine import Color, Game


def test_wide_view_is_both_sides_with_names():
    g = Game(white_name="A", black_name="B")
    g.move("e4")
    assert g.render().size == (1190, 644)  # unchanged default (both POVs + names)


def test_single_perspective_is_one_board():
    g = Game(white_name="A", black_name="B")
    g.move("e4")
    white = g.render(perspective="white")
    black = g.render(perspective=Color.BLACK)
    # a single 8x8 board (68px tiles), smaller than the wide view
    assert white.size == (544, 544) == black.size
    # the two orientations are genuinely different images
    assert white.tobytes() != black.tobytes()


def test_perspective_accepts_color_or_string():
    g = Game()
    assert g.render(perspective="white").size == g.render(perspective=Color.WHITE).size
