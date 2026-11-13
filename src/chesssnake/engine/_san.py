"""Writing moves in chesssnake notation (internal).

The notation is SAN without the ``=`` before a promotion and with castling in
zeros: ``e4``, ``Nf3``, ``exd5``, ``Nbd2``, ``e8Q``, ``0-0``. It is what the
history stores and what ``legal_moves()`` lists, and the engine reads it back;
:meth:`Game.pgn` converts it to standard PGN (``O-O``, ``e8=Q``).

Disambiguation follows the SAN rule and looks only at **legal** moves: when two
knights could reach a square but one is pinned, the move is ``Nd2``, not ``Nbd2``.
"""

from ._notation import FILES, NAMES
from .enums import PieceType

_CASTLE_K, _CASTLE_Q = 3, 4  # the board's ply flags (see board.py)


def _groups(board, legal):
    """For non-pawn moves: (piece type, destination) -> origins among the legal plies."""
    grid = board._grid
    groups: dict = {}
    for frm, to, _promo, flag in legal:
        piece = grid[frm]
        if piece.type is not PieceType.PAWN and flag < _CASTLE_K:
            groups.setdefault((piece.type, to), []).append(frm)
    return groups


def _one(grid, ply, groups) -> str:
    frm, to, promo, flag = ply
    if flag == _CASTLE_K:
        return "0-0"
    if flag == _CASTLE_Q:
        return "0-0-0"
    piece = grid[frm]
    if piece.type is PieceType.PAWN:
        text = f"{FILES[frm % 8]}x{NAMES[to]}" if frm % 8 != to % 8 else NAMES[to]
        return text + (promo.value if promo is not None else "")

    others = [s for s in groups.get((piece.type, to), ()) if s != frm]
    hint = ""
    if others:
        if all(s % 8 != frm % 8 for s in others):
            hint = FILES[frm % 8]
        elif all(s // 8 != frm // 8 for s in others):
            hint = str(8 - frm // 8)
        else:
            hint = NAMES[frm]
    capture = "x" if grid[to] is not None else ""
    return f"{piece.type.value}{hint}{capture}{NAMES[to]}"


def sans(board, legal) -> list[str]:
    """The notation for every ply in ``legal`` (the position's full legal list)."""
    groups = _groups(board, legal)
    return [_one(board._grid, ply, groups) for ply in legal]


def san(board, ply, legal) -> str:
    """The notation for one ply, disambiguated against the full legal list."""
    return _one(board._grid, ply, _groups(board, legal))
