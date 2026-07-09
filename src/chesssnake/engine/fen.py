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
from .enums import Color, PieceType
from .notation import get_c_notation, get_coords
from .pieces import Bishop, King, Knight, Pawn, Queen, Rook
from .square import Square

# The standard starting position.
INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# letter -> piece factory (color-only pieces); Rook/King take a `moved` flag too.
_SIMPLE = {"N": Knight, "B": Bishop, "Q": Queen, "P": Pawn}


def _castling_field(board: Board) -> str:
    """The FEN castling-availability field (e.g. ``"KQkq"`` or ``"-"``)."""
    rights = ""
    for color, rank, upper in ((Color.WHITE, 7, True), (Color.BLACK, 0, False)):
        king = board[rank, 4].piece
        if king is None or king.piecetype != PieceType.KING or king.color != color or king.moved:
            continue
        h_rook = board[rank, 7].piece  # king-side
        if h_rook is not None and h_rook.piecetype == PieceType.ROOK and h_rook.color == color and not h_rook.moved:
            rights += "K" if upper else "k"
        a_rook = board[rank, 0].piece  # queen-side
        if a_rook is not None and a_rook.piecetype == PieceType.ROOK and a_rook.color == color and not a_rook.moved:
            rights += "Q" if upper else "q"
    return rights or "-"


def _ep_field(board: Board, turn: Color) -> str:
    """The FEN en-passant target square (the square a pawn *skipped*), or ``"-"``."""
    tm = board.two_moveP
    if tm is None:
        return "-"
    # two_moveP stores the pawn's landing square; FEN wants the skipped square.
    # If it's white to move, black just double-moved (skipped = landing - 1 in i);
    # if black to move, white just moved (skipped = landing + 1 in i).
    skipped_i = tm.i - 1 if turn == Color.WHITE else tm.i + 1
    return get_c_notation(skipped_i, tm.j)


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
        f"{placement} {active} {_castling_field(board)} {_ep_field(board, turn)} "
        f"{board.halfmove_clock} {board.fullmove_number}"
    )


def position_key(board: Board, turn) -> str:
    """The first four FEN fields — the identity of a position for repetition checks.

    Two positions are "the same" (for threefold) when placement, side to move,
    castling rights, and en-passant availability all match — i.e. the halfmove and
    fullmove counters are excluded.
    """
    return " ".join(to_fen(board, turn).split()[:4])


def _make_piece(letter: str, color: Color, i: int, j: int, castling: str):
    """Build a piece for FEN placement, deriving Rook/King ``moved`` from castling rights."""
    if letter == "R":
        home = {(7, 0): "Q", (7, 7): "K", (0, 0): "q", (0, 7): "k"}.get((i, j))
        return Rook(color, moved=not (home is not None and home in castling))
    if letter == "K":
        rights = "KQ" if color == Color.WHITE else "kq"
        on_home = (i, j) == (7, 4) if color == Color.WHITE else (i, j) == (0, 4)
        return King(color, moved=not (on_home and any(r in castling for r in rights)))
    return _SIMPLE[letter](color)


def from_fen(fen: str):
    """Parse a FEN into ``(board, turn)``.

    :return: a tuple of the reconstructed :class:`Board` (with clocks and en-passant
        set) and the :class:`Color` to move.
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
                squares.append(Square(i, j, piece=_make_piece(ch.upper(), color, i, j, castling)))
                j += 1
        grid.append(squares)

    turn = Color.WHITE if active == "w" else Color.BLACK

    two_moveP = None
    if ep != "-":
        ti, tj = get_coords(ep)  # the skipped square
        landing_i = ti + 1 if turn == Color.WHITE else ti - 1
        two_moveP = Square(landing_i, tj)

    board = Board(board=grid, two_moveP=two_moveP)
    board.halfmove_clock = int(halfmove)
    board.fullmove_number = int(fullmove)
    return board, turn
