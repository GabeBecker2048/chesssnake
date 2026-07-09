"""Forsyth-Edwards Notation (FEN) — the board serialization format.

FEN is the standard single-line encoding of a chess position, used everywhere in
the chess ecosystem. It replaces chesssnake's former bespoke board string. A FEN
has six space-separated fields:

    <placement> <active-color> <castling> <en-passant> <halfmove> <fullmove>

e.g. the starting position: ``rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1``

This module is the single source of truth for turning a :class:`Board` (+ whose
turn it is) into a FEN and back.
"""

from .board import Board
from .enums import Color
from .pieces import Bishop, King, Knight, Pawn, Queen, Rook
from .square import Square

# The standard starting position.
INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# letter -> piece factory for FEN placement.
_PIECES = {"R": Rook, "N": Knight, "B": Bishop, "Q": Queen, "K": King, "P": Pawn}


def _castling_field(board: Board) -> str:
    """The FEN castling-availability field (e.g. ``"KQkq"`` or ``"-"``)."""
    return board.castling or "-"


def _ep_field(board: Board) -> str:
    """The FEN en-passant target square (the square a pawn *skipped*), or ``"-"``."""
    return board.en_passant or "-"


def to_fen(board: Board, turn) -> str:
    """Serialize ``board`` (with ``turn`` to move) to a full FEN string."""
    turn = Color(turn)
    ranks = []
    for i in range(8):
        row = ""
        empty = 0
        for j in range(8):
            piece = board[i, j].piece
            if piece is None:
                empty += 1
                continue
            if empty:
                row += str(empty)
                empty = 0
            letter = piece.piecetype.value
            row += letter if piece.color == Color.WHITE else letter.lower()
        if empty:
            row += str(empty)
        ranks.append(row)
    placement = "/".join(ranks)
    active = "w" if turn == Color.WHITE else "b"
    return (
        f"{placement} {active} {_castling_field(board)} {_ep_field(board)} "
        f"{board.halfmove_clock} {board.fullmove_number}"
    )


def position_key(board: Board, turn) -> str:
    """The first four FEN fields — the identity of a position for repetition checks.

    Two positions are "the same" (for threefold) when placement, side to move,
    castling rights, and en-passant availability all match — i.e. the halfmove and
    fullmove counters are excluded.
    """
    return " ".join(to_fen(board, turn).split()[:4])


def from_fen(fen: str):
    """Parse a FEN into ``(board, turn)``.

    :return: a tuple of the reconstructed :class:`Board` (with clocks, castling rights
        and en-passant set) and the :class:`Color` to move.
    :rtype: tuple[Board, Color]
    """
    placement, active, castling, ep, halfmove, fullmove = fen.split()

    grid = []
    for i, rank in enumerate(placement.split("/")):
        squares = []
        j = 0
        for ch in rank:
            if ch.isdigit():
                for _ in range(int(ch)):
                    squares.append(Square(i, j))
                    j += 1
            else:
                color = Color.WHITE if ch.isupper() else Color.BLACK
                squares.append(Square(i, j, piece=_PIECES[ch.upper()](color)))
                j += 1
        grid.append(squares)

    turn = Color.WHITE if active == "w" else Color.BLACK

    board = Board(board=grid, en_passant=(None if ep == "-" else ep), castling=castling)
    board.halfmove_clock = int(halfmove)
    board.fullmove_number = int(fullmove)
    return board, turn
