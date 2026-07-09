"""Build the algebraic string for a concrete move.

Produces the same notation the engine *accepts* (chesssnake move strings: ``e4``,
``Nf3``, ``exd5``, ``Nbd2``, ``e8Q``, ``0-0``), so a client can take a move listed
by :meth:`Board.legal_moves` and POST it straight back. PGN-style formatting
(``O-O``, ``=Q``, ``+``/``#``) is applied separately at export time.
"""

from .enums import PieceType
from .notation import FILES


def to_san(board, prev, to, piece, promotion=None, castle=None) -> str:
    """
    The postable move string for moving ``piece`` from ``prev`` to ``to``.

    :param board: the position **before** the move (for capture/disambiguation).
    :param prev: origin :class:`Square`.
    :param to: destination :class:`Square`.
    :param piece: the moving :class:`Piece`.
    :param promotion: promotion piece letter (``"Q"``/``"R"``/``"B"``/``"N"``) or ``None``.
    :param castle: ``"K"``/``"Q"`` for a castling move, else ``None``.
    :rtype: str
    """
    if castle is not None:
        return "0-0" if castle == "K" else "0-0-0"

    if piece.piecetype == PieceType.PAWN:
        if prev.j != to.j:  # diagonal => capture (incl. en passant)
            move = f"{FILES[prev.j]}x{to.c_notation}"
        else:
            move = to.c_notation
        return move + (promotion or "")

    letter = piece.piecetype.value
    capture = "x" if board[to.i, to.j].piece is not None else ""
    return f"{letter}{_disambiguation(board, prev, to, piece)}{capture}{to.c_notation}"


def _disambiguation(board, prev, to, piece) -> str:
    """The minimal file/rank hint needed to distinguish this piece's move (SAN rules)."""
    candidates = [s for s in piece.__class__.find_all(board, to, piece.color) if s != prev]
    if not candidates:
        return ""
    if all(s.j != prev.j for s in candidates):  # file alone is unambiguous
        return FILES[prev.j]
    if all(s.i != prev.i for s in candidates):  # rank alone is unambiguous
        return str(8 - prev.i)
    return FILES[prev.j] + str(8 - prev.i)  # need both
