"""Unit tests for board rendering, including single-perspective images."""

from chesssnake.engine import Color, Game


def test_wide_view_with_names_keeps_the_name_strip():
    g = Game(white_name="A", black_name="B")
    g.move("e4")
    assert g.render().size == (1190, 644)  # both POVs + the bottom name strip
    # a single name is enough to keep the strip
    assert Game(white_name="A").render().size == (1190, 644)
    assert Game(black_name="B").render().size == (1190, 644)


def test_nameless_wide_view_drops_the_name_strip():
    g = Game()  # no names
    g.move("e4")
    assert g.render().size == (1190, 544)  # both POVs, no blank bottom strip


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
