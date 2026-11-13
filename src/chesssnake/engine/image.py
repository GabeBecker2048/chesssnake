"""Board rendering: composite piece PNGs into a two-sided board image."""

from functools import cache

from PIL import Image, ImageDraw, ImageFont

from ..assets import asset_path
from ._notation import FILES, index, move_squares
from .board import Board
from .enums import Color

# The rendered board uses 68x68 pixel tiles; a full board is 8 tiles square.
TILE = 68
BOARD_PX = TILE * 8  # 544 — the height of a board (the wide template adds a name strip below)


def _as_color(perspective) -> Color:
    """Normalize a perspective argument (``Color`` / ``"white"`` / ``"black"`` / 0 / 1)."""
    if isinstance(perspective, str):
        key = perspective.lower()
        if key in ("white", "black"):
            return Color.WHITE if key == "white" else Color.BLACK
        raise ValueError(f"perspective must be 'white' or 'black', got {perspective!r}")
    return Color(perspective)


@cache
def _piece_image(piecetype_value, color):
    """Load (and cache) the RGBA sprite for a piece, e.g. ``('Q', 0)`` -> Q0.png."""
    return Image.open(asset_path(f"img/{piecetype_value}{color}.png")).convert("RGBA")


@cache
def _decoded(name):
    """
    Decode (once) a background image, e.g. ``"img/blankboard.png"``.

    Callers must draw on a :meth:`~PIL.Image.Image.copy`, never on this shared
    image. Decoding the board and template PNGs on every render was about 12 ms of
    a 27 ms wide render; a copy of the decoded image costs 0.2 ms. (Fonts are not
    cached: loading one takes 0.1 ms, and a FreeType face is not documented as safe
    to share between the server's worker threads.)
    """
    image = Image.open(asset_path(name))
    image.load()
    return image


@cache
def _orange_square():
    """Load (and cache) the RGBA last-move highlight tile."""
    return Image.open(asset_path("img/orange.png")).convert("RGBA")


def _render_side(grid, small_font, flip, highlights):
    """
    Render a single 8x8 board image from an already-oriented ``grid`` of squares.

    :param grid: 8 rows of 8 :class:`Piece` (or ``None``) in display order (top row first).
    :param flip: ``True`` for the black-oriented board (mirrored rank/file labels).
    :param highlights: ``(row, col)`` grid positions to shade for the last move.
    """
    board_img = _decoded("img/blankboard.png").copy()

    for row, col in highlights:
        board_img.alpha_composite(_orange_square(), (TILE * col, TILE * row))

    draw = ImageDraw.Draw(board_img)
    for x in range(8):
        for y in range(8):
            piece = grid[x][y]
            if piece is not None:
                board_img.alpha_composite(_piece_image(piece.type.value, int(piece.color)), (TILE * y, TILE * x))

            # rank number down the left edge
            if y == 0:
                number = x + 1 if flip else 8 - x
                draw.text((0, TILE * x), str(number), (255, 255, 255), font=small_font)

            # file letter along the bottom edge
            if x == 7:
                file = FILES[7 - y] if flip else FILES[y]
                draw.text((TILE * y + 57, TILE * 7 + 50), file, (255, 255, 255), font=small_font)

    return board_img


def render_board(board: Board, white_name: str = "", black_name: str = "", move=None, perspective=None):
    """
    Render the board to a :class:`PIL.Image.Image`.

    - ``perspective=None`` (default): the wide image with **both** the white- and
      black-oriented boards side by side and the player names overlaid.
    - ``perspective`` = ``Color.WHITE``/``Color.BLACK`` (or ``"white"``/``"black"``):
      a single board from that side's point of view — **board only**, no names.

    The source and destination of ``move`` are highlighted in orange when supplied.

    :param board: The board to render (after the move has been applied).
    :param white_name: White's name (truncated to 10 chars; wide view only).
    :param black_name: Black's name (truncated to 10 chars; wide view only).
    :param move: The most recent move, whose squares are highlighted, or ``None``: a
        :class:`Move`, a :class:`~chesssnake.dto.MoveResult`, or a ``{"from", "to"}`` dict.
    :param perspective: ``None`` for the wide both-sides view, or a color/``"white"``/
        ``"black"`` for a single-perspective board.
    :rtype: PIL.Image.Image
    """
    small_font = ImageFont.truetype(asset_path("Roboto-Black.ttf"), 15)

    rows = [board._grid[i * 8 : i * 8 + 8] for i in range(8)]
    white_grid = rows
    black_grid = [list(reversed(row)) for row in reversed(rows)]
    touched = [divmod(index(sq), 8) for sq in move_squares(move)]
    white_highlights = touched
    black_highlights = [(7 - i, 7 - j) for i, j in touched]

    # single-perspective: one board, no names
    if perspective is not None:
        if _as_color(perspective) == Color.WHITE:
            return _render_side(white_grid, small_font, False, white_highlights)
        return _render_side(black_grid, small_font, True, black_highlights)

    # wide view: both perspectives + names
    template = _decoded("img/template.png").copy()
    template.alpha_composite(_render_side(white_grid, small_font, False, white_highlights), (0, 0))
    template.alpha_composite(_render_side(black_grid, small_font, True, black_highlights), (646, 0))

    # If neither player is named, drop the bottom name strip (no blank row).
    if not white_name and not black_name:
        return template.crop((0, 0, template.width, BOARD_PX))

    big_font = ImageFont.truetype(asset_path("Roboto-Black.ttf"), 60)
    draw = ImageDraw.Draw(template)
    draw.text((0, BOARD_PX), white_name[:10], (255, 255, 255), font=big_font)
    draw.text((646, BOARD_PX), black_name[:10], (255, 255, 255), font=big_font)

    return template
