"""Enumerations used throughout the engine.

- :class:`Color` is an :class:`~enum.IntEnum` (``WHITE == 0``, ``BLACK == 1``) so it
  compares and does arithmetic like the raw ints it replaces, while adding an
  ``.opponent`` property that retires the ``1 - player`` flip idiom.
- :class:`PieceType` is a plain :class:`~enum.Enum` whose values are the single-letter
  codes used in notation and serialization. It is *not* a ``str`` mix-in, so it never
  stringifies to its letter by accident — use ``.value`` when a letter is needed.
- :class:`GameStatus` is an :class:`~enum.IntEnum` mirroring ``Board.status``.
"""

from enum import Enum, IntEnum


class Color(IntEnum):
    """A player's color. ``WHITE`` is 0, ``BLACK`` is 1 (matching the engine's ints)."""

    WHITE = 0
    BLACK = 1

    @property
    def opponent(self):
        """The opposing color."""
        return Color.BLACK if self is Color.WHITE else Color.WHITE


class PieceType(Enum):
    """A kind of chess piece; ``.value`` is its single-letter notation code."""

    PAWN = "P"
    ROOK = "R"
    KNIGHT = "N"
    BISHOP = "B"
    QUEEN = "Q"
    KING = "K"

    @property
    def full_name(self):
        """The lowercase english name of the piece (e.g. ``"knight"``)."""
        return _FULL_NAMES[self]


_FULL_NAMES = {
    PieceType.PAWN: "pawn",
    PieceType.ROOK: "rook",
    PieceType.KNIGHT: "knight",
    PieceType.BISHOP: "bishop",
    PieceType.QUEEN: "queen",
    PieceType.KING: "king",
}


class GameStatus(IntEnum):
    """The outcome of a game, as stored in ``Board.status``.

    A win (by checkmate or resignation) is recorded as ``WHITE_WON``/``BLACK_WON``;
    the specific reason a finished game ended is a separate :class:`Termination`.
    """

    IN_PLAY = 0
    WHITE_WON = 1
    BLACK_WON = 2
    DRAW = 3

    @classmethod
    def won_by(cls, color):
        """The winning status for ``color`` (``WHITE_WON`` or ``BLACK_WON``)."""
        return cls.WHITE_WON if Color(color) is Color.WHITE else cls.BLACK_WON


class Termination(str, Enum):
    """Why a finished game ended. ``None`` while the game is in play."""

    CHECKMATE = "checkmate"
    RESIGNATION = "resignation"
    STALEMATE = "stalemate"
    THREEFOLD = "threefold_repetition"
    FIFTY_MOVE = "fifty_move_rule"
    INSUFFICIENT_MATERIAL = "insufficient_material"
    AGREEMENT = "agreement"
