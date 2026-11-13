"""Square names and move-string syntax (internal).

Squares are numbered 0-63 as ``i * 8 + j``: ``i`` is the row from the top (0 is
rank 8, 7 is rank 1) and ``j`` the file (0 is ``a``). So ``a8`` is 0, ``h8`` 7,
``a1`` 56 and ``h1`` 63. The public API speaks in square names (``"e4"``); only
the engine uses the numbers.
"""

import re

FILES = "abcdefgh"
RANKS = "12345678"

# Every square's name, by index.
NAMES = tuple(FILES[idx % 8] + str(8 - idx // 8) for idx in range(64))
_INDEX = {name: idx for idx, name in enumerate(NAMES)}


def index(name: str) -> int:
    """
    The index of a square name (``"e4"`` -> 36).

    :raises ValueError: if ``name`` is not a square.
    """
    try:
        return _INDEX[name]
    except (KeyError, TypeError):
        raise ValueError(f"not a square: {name!r}") from None


def name(idx: int) -> str:
    """The name of a square index (36 -> ``"e4"``)."""
    return NAMES[idx]


# SAN as chesssnake reads it. Pieces: an optional file and/or rank to disambiguate,
# an optional capture mark. Pawns: an optional "P", a "file x" for a capture, and a
# promotion with or without "=". Castling with zeros or the letter O. Any of them may
# end in "+" or "#", which describe the move rather than choose it.
SAN_RE = re.compile(
    r"""
    ^(?:
        (?P<castle>0-0(?:-0)?|O-O(?:-O)?)
      | (?P<piece>[KQRBN])(?P<from_file>[a-h])?(?P<from_rank>[1-8])?(?P<capture>x)?(?P<to>[a-h][1-8])
      | P?(?:(?P<pawn_file>[a-h])(?P<pawn_capture>x))?(?P<pawn_to>[a-h][1-8])(?:=?(?P<promotion>[QRBN]))?
    )[+#]?$
    """,
    re.VERBOSE,
)

# UCI, as engines and bots send moves: origin, destination, optional promotion.
# It cannot be mistaken for SAN, which never puts a rank right after a pawn's file.
UCI_RE = re.compile(r"^(?P<from>[a-h][1-8])(?P<to>[a-h][1-8])(?P<promotion>[qrbnQRBN])?$")


def is_valid_notation(move: str) -> bool:
    """
    Whether ``move`` is syntactically a move: SAN (``Nf3``, ``exd8=Q``, ``O-O``) or
    UCI (``g1f3``, ``e7e8q``). Says nothing about whether it is legal.

    :param move: The move string, surrounding whitespace allowed.
    :rtype: bool
    """
    if not isinstance(move, str):
        return False
    move = move.strip()
    return bool(SAN_RE.match(move) or UCI_RE.match(move))


def move_squares(move) -> set[str]:
    """
    The squares a move touched, for the renderers' last-move highlight.

    Accepts the shapes that exist: anything with ``from_square``/``to_square``
    names (an engine :class:`Move`, a :class:`~chesssnake.dto.MoveResult`), or a
    ``{"from": "e2", "to": "e4"}`` mapping as REST and websocket payloads carry
    (``"to"`` is ``None`` for castling). Anything else highlights nothing rather
    than raising: a decoration must never break the board.

    :param move: The move, or ``None``.
    :rtype: set[str]
    """
    if move is None:
        return set()
    if isinstance(move, dict):
        values = (move.get("from"), move.get("to"))
    else:
        values = (getattr(move, "from_square", None), getattr(move, "to_square", None))
    return {v for v in values if isinstance(v, str) and v in _INDEX}
