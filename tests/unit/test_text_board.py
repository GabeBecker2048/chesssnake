"""
Tests for the text board renderer (:mod:`chesssnake.engine.text`).

Pure rendering: no game, no server, no terminal. ``color=False`` is the default
throughout so the expected output is plain text that a failure can actually
show you.
"""

import pytest

from chesssnake.engine import Board, Color, render_text
from chesssnake.engine.text import EMPTY, FIGURINES


def ranks(rendered):
    """The board rows of a rendering, without the file-label line."""
    return [line for line in rendered.splitlines() if line and not line.startswith("  ")]


def test_initial_position_from_white():
    lines = ranks(render_text(Board(), figurines=False))
    assert lines[0].startswith("8 ")
    assert lines[0].split()[1:] == list("rnbqkbnr")
    assert lines[-1].startswith("1 ")
    assert lines[-1].split()[1:] == list("RNBQKBNR")


def test_black_perspective_flips_both_axes():
    lines = ranks(render_text(Board(), Color.BLACK, figurines=False))
    # Rank 1 is now at the top, and files run h..a, so white's queenside rook
    # (a1) lands on the right.
    assert lines[0].startswith("1 ")
    assert lines[0].split()[1:] == list("RNBKQBNR")
    assert render_text(Board(), Color.BLACK).splitlines()[-1].split() == list("hgfedcba")


def test_perspective_accepts_strings_and_enum():
    assert render_text(Board(), "black") == render_text(Board(), Color.BLACK)
    assert render_text(Board(), "white") == render_text(Board(), Color.WHITE)
    assert render_text(Board(), None) == render_text(Board(), Color.WHITE)


def test_perspective_rejects_nonsense():
    with pytest.raises(ValueError, match="perspective"):
        render_text(Board(), "sideways")


def test_figurines_and_letters_are_both_available():
    figurine = render_text(Board(), figurines=True)
    letters = render_text(Board(), figurines=False)
    assert FIGURINES["k"] in figurine
    assert FIGURINES["K"] in figurine
    assert "k" not in figurine
    assert "k" in letters and "K" in letters


def test_empty_squares_are_marked_when_uncoloured():
    assert EMPTY in render_text(Board())


def test_coordinates_can_be_dropped():
    bare = render_text(Board(), coordinates=False)
    assert "a" not in bare
    assert not any(line.startswith("8") for line in bare.splitlines())


def test_no_escape_codes_unless_colour_is_asked_for():
    assert "\033" not in render_text(Board())
    assert "\033" in render_text(Board(), color=True)


def test_colour_highlights_the_squares_a_move_touched():
    """The highlight differs from both normal square colours, so it is visible."""
    board = Board()
    plain = render_text(board, color=True)
    highlighted = render_text(board, color=True, move={"from": "e2", "to": "e4"})
    assert highlighted != plain
    assert "\033[48;5;179m" in highlighted


def test_move_highlight_is_ignored_without_colour():
    """There is nowhere to put a highlight in plain text, so it must not corrupt it."""
    board = Board()
    assert render_text(board, move={"from": "e2", "to": "e4"}) == render_text(board)


def test_renders_a_position_after_a_move():
    """The pawn leaves e2 and appears on e4 — exactly, not just somewhere."""
    board = Board()
    board.move("e4", Color.WHITE)
    lines = ranks(render_text(board, figurines=False))
    rank4 = lines[4].split()[1:]
    rank2 = lines[6].split()[1:]
    assert lines[4].startswith("4 ") and lines[6].startswith("2 ")
    assert rank4 == [EMPTY, EMPTY, EMPTY, EMPTY, "P", EMPTY, EMPTY, EMPTY]
    assert rank2 == ["P", "P", "P", "P", EMPTY, "P", "P", "P"]


def test_highlight_accepts_an_engine_move_object():
    """`Game.last_move` holds Square objects, which is the shape used in practice."""
    board = Board()
    move = board.move("e4", Color.WHITE)
    highlighted = render_text(board, color=True, move=move)
    assert "\033[48;5;179m" in highlighted
    assert highlighted != render_text(board, color=True)


def test_highlight_ignores_an_unrecognised_move_shape():
    """A decoration must never break the board."""
    board = Board()
    assert render_text(board, color=True, move=object()) == render_text(board, color=True)
    assert render_text(board, color=True, move={"nothing": "useful"}) == render_text(board, color=True)
