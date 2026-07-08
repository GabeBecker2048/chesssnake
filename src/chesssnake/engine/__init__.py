"""The chesssnake chess engine: board model, move parsing, rules, and rendering.

Pure Python with no dependencies beyond Pillow (used only by the renderer). The
public names are re-exported here so consumers can do
``from chesssnake.engine import Board, Move, Game``.
"""

from . import errors, notation
from .board import Board
from .game import Game
from .image import img
from .move import Move
from .notation import FILES, get_c_notation, get_coords, is_valid_c_notation
from .pieces import Bishop, King, Knight, Pawn, Piece, Queen, Rook
from .square import Square

__all__ = [
    "errors",
    "notation",
    "Board",
    "Square",
    "Move",
    "Game",
    "img",
    "Piece",
    "Rook",
    "Knight",
    "Bishop",
    "Queen",
    "King",
    "Pawn",
    "FILES",
    "get_coords",
    "get_c_notation",
    "is_valid_c_notation",
]
