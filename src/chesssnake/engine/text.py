"""
Render a board as text, for terminals.

The sibling of :mod:`chesssnake.engine.image`: same job, different output. This
one has **no dependencies at all** — not even Pillow — which is what lets
``chesssnake play`` work from a core install, and what keeps it usable over SSH
and in CI logs.

Two glyph sets are offered because neither is right everywhere. Figurine
(``♞``) reads like a chessboard but needs a font with the Miscellaneous Symbols
block and a terminal that gets the widths right; letters (``N``) work on
anything, including a pipe into a file.
"""

from .enums import Color
from .square import Square

# Figurine glyphs, keyed by FEN letter (uppercase = white). Deliberately NOT a
# PieceType lookup: FEN case is already the colour, so one flat table covers
# both sides without branching.
FIGURINES = {
    "K": "♔",
    "Q": "♕",
    "R": "♖",
    "B": "♗",
    "N": "♘",
    "P": "♙",
    "k": "♚",
    "q": "♛",
    "r": "♜",
    "b": "♝",
    "n": "♞",
    "p": "♟",
}

# Shown for an empty square when not painting backgrounds. A middle dot rather
# than a space so the grid stays legible when the squares have no colour.
EMPTY = "·"

_FILES = "abcdefgh"

# 256-colour background pairs. Chosen over the 8 basic colours because those are
# themed per terminal, so "white square" could come out any colour at all.
_LIGHT_BG = "\033[48;5;180m"
_DARK_BG = "\033[48;5;137m"
_INK = "\033[38;5;232m"
_HIGHLIGHT_BG = "\033[48;5;179m"
_RESET = "\033[0m"


def _perspective_color(perspective):
    """
    Normalize a perspective argument to a :class:`Color`.

    :param perspective: ``None`` (white's view), a :class:`Color`, or the
        strings ``"white"``/``"black"``.
    :raises ValueError: if the value names neither colour.
    """
    if perspective is None:
        return Color.WHITE
    if isinstance(perspective, str):
        try:
            return Color[perspective.strip().upper()]
        except KeyError:
            raise ValueError(f"perspective must be 'white' or 'black', not {perspective!r}")
    return Color(perspective)


def _letter(piece) -> str:
    """The FEN letter for ``piece`` — uppercase for white, lowercase for black."""
    letter = piece.piecetype.value
    return letter if piece.color == Color.WHITE else letter.lower()


def _squares(move):
    """
    The pair of algebraic squares a move touched, for highlighting.

    Two shapes are accepted because two exist: ``prev``/``to`` attributes holding
    :class:`~chesssnake.engine.square.Square` objects (an engine
    :class:`~chesssnake.engine.move.Move`, and the marker the remote client keeps
    after a move), or a ``{"from": "e2", "to": "e4"}`` mapping as the REST
    payloads carry. Anything else highlights nothing rather than raising —
    a decoration must never break the board.

    :param move: the move to locate, or ``None``.
    :return: a set of algebraic square names, empty when there are none to find.
    """
    if move is None:
        return set()
    if isinstance(move, dict):
        return {value for key in ("from", "to") if isinstance(value := move.get(key), str)}
    out = set()
    for attr in ("prev", "to"):
        value = getattr(move, attr, None)
        if isinstance(value, Square):
            out.add(f"{_FILES[value.j]}{8 - value.i}")
    return out


def render_text(
    board,
    perspective=None,
    *,
    figurines: bool = True,
    coordinates: bool = True,
    color: bool = False,
    move=None,
) -> str:
    """
    Render ``board`` as a multi-line string.

    :param board: the :class:`~chesssnake.engine.board.Board` to draw.
    :param perspective: whose side faces the reader — ``None``/``Color.WHITE``
        (default) puts rank 1 at the bottom, ``Color.BLACK`` flips both axes.
        Unlike :func:`~chesssnake.engine.image.render_board`, ``None`` means
        white's view rather than a two-board image: there is no sensible
        side-by-side form in text.
    :param figurines: draw pieces as ``♞`` rather than the FEN letter ``N``.
    :param coordinates: include the file letters and rank numbers.
    :param color: wrap squares in ANSI background colours. Off by default so the
        output is safe to pipe, log, or compare in a test.
    :param move: a move whose source and destination squares are highlighted;
        only has an effect when ``color`` is true.
    :return: the board as text, without a trailing newline.
    :raises ValueError: if ``perspective`` names neither colour.
    """
    side = _perspective_color(perspective)
    rows = range(8) if side == Color.WHITE else range(7, -1, -1)
    cols = range(8) if side == Color.WHITE else range(7, -1, -1)
    touched = _squares(move) if color else set()

    lines = []
    for i in rows:
        cells = []
        for j in cols:
            square = board[i, j]
            piece = None if square is None else square.piece
            if piece is None:
                glyph = " " if color else EMPTY
            else:
                letter = _letter(piece)
                glyph = FIGURINES[letter] if figurines else letter
            if color:
                name = f"{_FILES[j]}{8 - i}"
                if name in touched:
                    background = _HIGHLIGHT_BG
                else:
                    background = _LIGHT_BG if (i + j) % 2 == 0 else _DARK_BG
                cells.append(f"{background}{_INK} {glyph} {_RESET}")
            else:
                cells.append(f" {glyph} ")
        rank = f"{8 - i} " if coordinates else ""
        lines.append(f"{rank}{''.join(cells)}")

    if coordinates:
        labels = _FILES if side == Color.WHITE else _FILES[::-1]
        lines.append("  " + "".join(f" {c} " for c in labels))
    return "\n".join(lines)
