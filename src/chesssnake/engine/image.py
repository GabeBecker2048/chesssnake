"""Board rendering: composite piece PNGs into a two-sided board image."""

from functools import cache

from PIL import Image, ImageDraw, ImageFont

from ..assets import asset_path
from .board import Board
from .enums import Color
from .move import Move
from .notation import FILES

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
def _orange_square():
    """Load (and cache) the RGBA last-move highlight tile."""
    return Image.open(asset_path("img/orange.png")).convert("RGBA")


def _render_side(grid, small_font, flip, highlights):
    """
    Render a single 8x8 board image from an already-oriented ``grid`` of squares.

    :param grid: 8x8 list of :class:`Square` rows in display order (top row first).
    :param flip: ``True`` for the black-oriented board (mirrored rank/file labels).
    :param highlights: ``(row, col)`` grid positions to shade for the last move.
    """
    board_img = Image.open(asset_path("img/blankboard.png"))

    for row, col in highlights:
        board_img.alpha_composite(_orange_square(), (TILE * col, TILE * row))

    draw = ImageDraw.Draw(board_img)
    for x in range(8):
        for y in range(8):
            piece = grid[x][y].piece
            if piece is not None:
                board_img.alpha_composite(_piece_image(piece.piecetype.value, int(piece.color)), (TILE * y, TILE * x))

            # rank number down the left edge
            if y == 0:
                number = x + 1 if flip else 8 - x
                draw.text((0, TILE * x), str(number), (255, 255, 255), font=small_font)

            # file letter along the bottom edge
            if x == 7:
                file = FILES[7 - y] if flip else FILES[y]
                draw.text((TILE * y + 57, TILE * 7 + 50), file, (255, 255, 255), font=small_font)

    return board_img


def render_board(
    board: Board, white_name: str = "", black_name: str = "", move: "Move | None" = None, perspective=None
):
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
    :param move: The most recent move, whose squares are highlighted, or ``None``.
    :param perspective: ``None`` for the wide both-sides view, or a color/``"white"``/
        ``"black"`` for a single-perspective board.
    :rtype: PIL.Image.Image
    """
    small_font = ImageFont.truetype(asset_path("Roboto-Black.ttf"), 15)

    # single-perspective: one board, no names
    if perspective is not None:
        color = _as_color(perspective)
        if color == Color.WHITE:
            grid, flip = board.board, False
            highlights = [(sq.i, sq.j) for sq in (move.prev, move.to)] if move is not None else []
        else:
            grid = [list(reversed(row)) for row in reversed(board.board)]
            flip = True
            highlights = [(7 - sq.i, 7 - sq.j) for sq in (move.prev, move.to)] if move is not None else []
        return _render_side(grid, small_font, flip, highlights)

    # wide view: both perspectives + names
    template = Image.open(asset_path("img/template.png"))

    # the last move's squares, expressed in each board's own (row, col) coordinates
    white_highlights, black_highlights = [], []
    if move is not None:
        for square in (move.prev, move.to):
            white_highlights.append((square.i, square.j))
            black_highlights.append((7 - square.i, 7 - square.j))

    white_grid = board.board
    black_grid = [list(reversed(row)) for row in reversed(board.board)]

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
