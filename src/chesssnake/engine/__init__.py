"""The chesssnake chess engine: positions, moves, rules, and rendering.

Pure Python with no dependencies beyond Pillow (used only by the image renderer).
This is the public engine API, and the names in ``__all__`` are the whole of it:

- :class:`Board`: a position. Query it with square names (``piece_at("e4")``,
  ``is_attacked("f7", by=Color.BLACK)``, ``legal_moves()``), change it with
  ``move()`` and ``undo()``.
- :class:`Piece` and :class:`Move`: small immutable values.
- :class:`Game`: a board plus players, draw offers, history, PGN and rendering.

Everything else in this package (modules starting with ``_``, and anything else
not listed here) is internal and may change in any release.
"""

from . import errors
from ._fen import INITIAL_FEN
from .board import Board
from .enums import Color, GameStatus, PieceType, Termination
from .game import Game
from .image import render_board
from .move import Move
from .piece import Piece
from .text import render_text

__all__ = [
    "Board",
    "Color",
    "Game",
    "GameStatus",
    "INITIAL_FEN",
    "Move",
    "Piece",
    "PieceType",
    "Termination",
    "errors",
    "render_board",
    "render_text",
]
