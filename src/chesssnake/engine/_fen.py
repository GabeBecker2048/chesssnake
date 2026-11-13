"""Forsyth-Edwards Notation (FEN): reading and writing positions (internal).

A FEN has six space-separated fields:

    <placement> <active-color> <castling> <en-passant> <halfmove> <fullmove>

e.g. the starting position: ``rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1``

The public way in and out is :meth:`Board.from_fen` and :attr:`Board.fen`.
"""

import re

from ._notation import NAMES
from .enums import Color
from .piece import Piece

# The standard starting position.
INITIAL_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

_CASTLING_RE = re.compile(r"^(?:-|K?Q?k?q?)$")
_EP_RE = re.compile(r"^(?:-|[a-h][36])$")


def parse(fen: str):
    """
    Split a FEN into its parts, validating each.

    :return: ``(grid, turn, castling, en_passant, halfmove, fullmove)``: a 64-entry
        list of :class:`Piece` or ``None`` (index ``i * 8 + j``, a8 first), the
        :class:`Color` to move, the castling letters (``""`` for none), the en-passant
        target square name or ``None``, and the two clocks.
    :raises ValueError: with the reason, if ``fen`` is not a valid FEN.
    """
    if not isinstance(fen, str):
        raise ValueError("a FEN must be a string")
    fields = fen.split()
    if len(fields) != 6:
        raise ValueError(f"a FEN has 6 fields, this has {len(fields)}: {fen!r}")
    placement, active, castling, ep, halfmove, fullmove = fields

    ranks = placement.split("/")
    if len(ranks) != 8:
        raise ValueError(f"FEN placement needs 8 ranks, has {len(ranks)}")
    grid: list[Piece | None] = []
    for rank in ranks:
        row: list[Piece | None] = []
        for ch in rank:
            if ch in "12345678":
                row.extend([None] * int(ch))
            else:
                row.append(Piece.from_symbol(ch))  # ValueError for a bad letter
        if len(row) != 8:
            raise ValueError(f"FEN rank {rank!r} does not cover 8 squares")
        grid.extend(row)

    for color, letter in ((Color.WHITE, "K"), (Color.BLACK, "k")):
        kings = sum(1 for p in grid if p is not None and p.symbol == letter)
        if kings != 1:
            raise ValueError(f"FEN needs exactly one {color.name.lower()} king, has {kings}")

    if active not in ("w", "b"):
        raise ValueError(f"FEN side to move must be 'w' or 'b', not {active!r}")
    if not _CASTLING_RE.match(castling):
        raise ValueError(f"bad FEN castling field {castling!r}")
    if not _EP_RE.match(ep):
        raise ValueError(f"bad FEN en-passant field {ep!r}")
    if not (halfmove.isdigit() and fullmove.isdigit()) or int(fullmove) < 1:
        raise ValueError(f"bad FEN clocks {halfmove!r} {fullmove!r}")

    turn = Color.WHITE if active == "w" else Color.BLACK
    return grid, turn, ("" if castling == "-" else castling), (None if ep == "-" else ep), int(halfmove), int(fullmove)


def placement(grid) -> str:
    """The FEN placement field for a 64-entry grid."""
    ranks = []
    for i in range(8):
        row = ""
        empty = 0
        for piece in grid[i * 8 : i * 8 + 8]:
            if piece is None:
                empty += 1
                continue
            if empty:
                row += str(empty)
                empty = 0
            row += piece.symbol
        if empty:
            row += str(empty)
        ranks.append(row)
    return "/".join(ranks)


def write(board) -> str:
    """The full FEN of ``board``."""
    return (
        f"{placement(board._grid)} {'w' if board.turn is Color.WHITE else 'b'} "
        f"{board.castling or '-'} {board.en_passant or '-'} {board.halfmove_clock} {board.fullmove_number}"
    )


__all__ = ["INITIAL_FEN", "NAMES", "parse", "placement", "write"]
