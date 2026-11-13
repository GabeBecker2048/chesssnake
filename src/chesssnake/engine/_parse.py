"""Reading a move string against a position (internal).

A move is chosen by matching it against the position's **legal** moves, so the
engine can never accept an illegal move or refuse a legal one because of how it
was written. Only when nothing matches does the parser look for *why*, so the
error can say something useful ("there is not a piece to capture on e5") rather
than just "illegal". Those explanations, and their error classes, are part of the
wire protocol: the client rebuilds errors by class name.

An explanation is only given when it has been established, never guessed. Each
diagnosis must raise its specific error; if it finds no reason, or fails with an
unexpected exception, the move is refused with the plain :class:`IllegalMoveError`
(see :func:`_explain`). In particular "that would put you in check" is only said
once the move is confirmed to be a possible piece movement that fails solely the
check test. A wrong reason is worse than none.
"""

import logging
from typing import NoReturn

from . import errors
from ._notation import FILES, NAMES, SAN_RE, UCI_RE, index
from .enums import Color, PieceType

# imported lazily from board.py at call time would be circular; these mirror it
_NORMAL, _DOUBLE_STEP, _EN_PASSANT, _CASTLE_K, _CASTLE_Q = range(5)

_log = logging.getLogger(__name__)


def resolve(board, text: str, legal: list) -> tuple:
    """
    The legal ply ``text`` names, for the side to move.

    :param board: The position (a :class:`Board`).
    :param text: The move, already known to be syntactically valid SAN or UCI.
    :param legal: The position's legal plies.
    :raises errors.ChessError: the specific reason when ``text`` names no legal move,
        or :class:`errors.IllegalMoveError` when no reason can be established.
    """
    m = UCI_RE.match(text)
    if m:
        ply = _match_uci(m, legal)
        if ply is None:
            _explain(text, _diagnose_uci, board, text, m)
        return ply
    m = SAN_RE.match(text)
    if m is None:  # pragma: no cover - the caller validated the syntax
        raise errors.InvalidNotationError(text)
    if m["castle"]:
        queenside = m["castle"].count("-") == 2
        ply = _match_castle(queenside, legal)
        if ply is None:
            _explain(text, _diagnose_castle, board, queenside)
        return ply
    spec = _san_spec(m)
    ply = _match_san(board, spec, legal)
    if ply is None:
        _explain(text, _diagnose_san, board, spec)
    return ply


def _explain(text: str, diagnose, *args) -> NoReturn:
    """
    Run ``diagnose(*args)``, which raises the specific :class:`errors.ChessError`
    explaining why ``text`` is illegal. If it returns instead (no reason found) or
    raises anything else (a bug in the diagnosis), refuse the move with the plain
    :class:`errors.IllegalMoveError` rather than risk a misleading reason. A crash is
    logged with its traceback, so the bug is still visible.

    :raises errors.ChessError: always.
    """
    try:
        diagnose(*args)
    except errors.ChessError:
        raise
    except Exception:
        _log.exception("could not explain why %r is illegal; reporting IllegalMoveError", text)
    raise errors.IllegalMoveError(text)


def _match_castle(queenside: bool, legal) -> "tuple | None":
    flag = _CASTLE_Q if queenside else _CASTLE_K
    for ply in legal:
        if ply[3] == flag:
            return ply
    return None


def _diagnose_castle(board, queenside: bool) -> None:
    side = "Q" if queenside else "K"
    if not board._castle_ok(board.turn, side):
        raise errors.InvalidCastleError(side)
    # castling is possible as a movement, so only its destination can be the problem
    flag = _CASTLE_Q if queenside else _CASTLE_K
    if any(ply[3] == flag for ply in board._pseudo(board.turn)):
        raise errors.MoveIntoCheckError()


def _last_row(color) -> int:
    return 0 if color is Color.WHITE else 7


def _san_spec(m) -> tuple:
    """``(kind, file_hint, rank_hint, capture, to, promotion)`` from a SAN match."""
    if m["piece"]:
        return PieceType(m["piece"]), m["from_file"], m["from_rank"], bool(m["capture"]), index(m["to"]), None
    promo = PieceType(m["promotion"]) if m["promotion"] else None
    return PieceType.PAWN, m["pawn_file"], None, bool(m["pawn_capture"]), index(m["pawn_to"]), promo


def _fits(grid, ply, spec) -> bool:
    """Whether ``ply`` is a move the SAN ``spec`` could describe."""
    kind, file_hint, rank_hint, capture, to, promo = spec
    frm, dest, ply_promo, flag = ply
    if dest != to or flag >= _CASTLE_K or grid[frm].type is not kind or ply_promo is not promo:
        return False
    if file_hint and FILES[frm % 8] != file_hint:
        return False
    if rank_hint and str(8 - frm // 8) != rank_hint:
        return False
    # "exd5" must be a capture and "d5" a push
    return not (kind is PieceType.PAWN and (frm % 8 != to % 8) != capture)


def _match_san(board, spec, legal) -> "tuple | None":
    """The one legal ply ``spec`` describes, or ``None`` when there is none.

    :raises errors.MultiplePiecesFoundError: if several legal plies fit.
    :raises errors.NothingToCaptureError: for a capture mark onto an empty square.
    :raises errors.PieceOnSquareError: for a missing capture mark onto a piece.
    """
    kind, _file, _rank, capture, to, _promo = spec
    grid = board._grid
    matches = [ply for ply in legal if _fits(grid, ply, spec)]
    if len(matches) > 1:
        raise errors.MultiplePiecesFoundError(NAMES[to], [NAMES[ply[0]] for ply in matches], kind)
    if not matches:
        return None
    if kind is not PieceType.PAWN:
        target = grid[to]
        if capture and target is None:
            raise errors.NothingToCaptureError(NAMES[to])
        if not capture and target is not None:
            raise errors.PieceOnSquareError(NAMES[to], False)
    return matches[0]


def _reachers(board, kind, color, to, capture) -> list[int]:
    """Squares holding a ``kind`` of ``color`` that could geometrically reach ``to``,
    ignoring check (and, for pieces, what stands on ``to``)."""
    from .board import KING_TARGETS, KNIGHT_TARGETS, PAWN_ATTACKS, SLIDER_RAYS
    from .piece import PIECES

    grid = board._grid
    want = PIECES[kind, color]
    if kind is PieceType.PAWN:
        if capture:
            return [s for s in PAWN_ATTACKS[color.opponent][to] if grid[s] is want]
        behind = 8 if color is Color.WHITE else -8
        one = to + behind
        if not 0 <= one < 64:
            return []
        if grid[one] is not None:
            return [one] if grid[one] is want else []
        two = one + behind
        start_row = 6 if color is Color.WHITE else 1
        if 0 <= two < 64 and two // 8 == start_row and grid[two] is want:
            return [two]
        return []
    if kind is PieceType.KNIGHT:
        return [s for s in KNIGHT_TARGETS[to] if grid[s] is want]
    if kind is PieceType.KING:
        return [s for s in KING_TARGETS[to] if grid[s] is want]
    found = []
    for ray in SLIDER_RAYS[kind][to]:
        for s in ray:
            if grid[s] is not None:
                if grid[s] is want:
                    found.append(s)
                break
    return found


def _diagnose_san(board, spec) -> None:
    """Raise the specific reason a SAN move matched no legal move. Returns only
    when no reason is established; :func:`_explain` then reports IllegalMoveError."""
    kind, file_hint, rank_hint, capture, to, promo = spec
    color = board.turn
    if promo is not None and to // 8 != _last_row(color):
        raise errors.PromotionError(invalid_promotion=True)
    grid = board._grid
    square = NAMES[to]
    found = [
        s
        for s in _reachers(board, kind, color, to, capture)
        if (not file_hint or FILES[s % 8] == file_hint) and (not rank_hint or str(8 - s // 8) == rank_hint)
    ]
    if not found:
        raise errors.PieceNotFoundError(square, kind)
    if len(found) > 1:
        raise errors.MultiplePiecesFoundError(square, [NAMES[s] for s in found], kind)

    target = grid[to]
    if capture:
        if target is None:
            ep_ok = kind is PieceType.PAWN and board.en_passant == square
            if not ep_ok:
                raise errors.NothingToCaptureError(square)
        elif target.color is color:
            raise errors.CaptureOwnPieceError(square)
    elif target is not None:
        raise errors.PieceOnSquareError(square, target.color is color)

    if kind is PieceType.PAWN and to // 8 == _last_row(color) and promo is None:
        raise errors.PromotionError(need_promotion=True)

    # Only now is check the explanation, and only if confirmed: the move must be a
    # possible piece movement that the legality test (king left in check) removed.
    if any(_fits(grid, ply, spec) for ply in board._pseudo(color)):
        raise errors.MoveIntoCheckError()


def _match_uci(m, legal) -> "tuple | None":
    frm, to = index(m["from"]), index(m["to"])
    promo = PieceType(m["promotion"].upper()) if m["promotion"] else None
    for ply in legal:
        if ply[0] == frm and ply[1] == to and ply[2] is promo:
            return ply
    return None


def _diagnose_uci(board, text, m) -> None:
    """Raise the specific reason a UCI move matched no legal move. Returns only
    when no reason is established; :func:`_explain` then reports IllegalMoveError."""
    frm, to = index(m["from"]), index(m["to"])
    promo = PieceType(m["promotion"].upper()) if m["promotion"] else None
    color = board.turn
    piece = board._grid[frm]
    if piece is None or piece.color is not color:
        raise errors.IllegalMoveError(text, f"there is no {color.name.lower()} piece on {m['from']}")
    last_row = to // 8 == _last_row(color)
    if promo is not None and (piece.type is not PieceType.PAWN or not last_row):
        raise errors.PromotionError(invalid_promotion=True)
    if piece.type is PieceType.KING and frm // 8 == to // 8 and abs(to - frm) == 2:
        side = "K" if to > frm else "Q"
        if not board._castle_ok(color, side):
            raise errors.InvalidCastleError(side)
    pseudo = [ply for ply in board._pseudo(color) if ply[0] == frm and ply[1] == to]
    if not pseudo:
        raise errors.IllegalMoveError(text, f"the {piece.type.full_name} on {m['from']} cannot move to {m['to']}")
    if piece.type is PieceType.PAWN and last_row and promo is None:
        raise errors.PromotionError(need_promotion=True)
    if any(ply[2] is promo for ply in pseudo):
        raise errors.MoveIntoCheckError()
