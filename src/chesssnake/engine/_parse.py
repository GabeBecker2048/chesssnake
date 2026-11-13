"""Reading a move string against a position (internal).

A move is chosen by matching it against the position's **legal** moves, so the
engine can never accept an illegal move or refuse a legal one because of how it
was written. Only when nothing matches does the parser look for *why*, so the
error can say something useful ("there is not a piece to capture on e5") rather
than just "illegal". Those explanations, and their error classes, are part of the
wire protocol: the client rebuilds errors by class name.
"""

from . import errors
from ._notation import FILES, NAMES, SAN_RE, UCI_RE, index
from .enums import Color, PieceType

# imported lazily from board.py at call time would be circular; these mirror it
_NORMAL, _DOUBLE_STEP, _EN_PASSANT, _CASTLE_K, _CASTLE_Q = range(5)


def resolve(board, text: str, legal: list) -> tuple:
    """
    The legal ply ``text`` names, for the side to move.

    :param board: The position (a :class:`Board`).
    :param text: The move, already known to be syntactically valid SAN or UCI.
    :param legal: The position's legal plies.
    :raises errors.ChessError: the specific reason when ``text`` names no legal move.
    """
    m = UCI_RE.match(text)
    if m:
        return _resolve_uci(board, text, m, legal)
    m = SAN_RE.match(text)
    if m is None:  # pragma: no cover - the caller validated the syntax
        raise errors.InvalidNotationError(text)
    if m["castle"]:
        return _resolve_castle(board, m["castle"].count("-") == 2, legal)
    return _resolve_san(board, m, legal)


def _resolve_castle(board, queenside: bool, legal) -> tuple:
    flag = _CASTLE_Q if queenside else _CASTLE_K
    for ply in legal:
        if ply[3] == flag:
            return ply
    side = "Q" if queenside else "K"
    if not board._castle_ok(board.turn, side):
        raise errors.InvalidCastleError(side)
    raise errors.MoveIntoCheckError()  # the king would land on an attacked square


def _last_row(color) -> int:
    return 0 if color is Color.WHITE else 7


def _resolve_san(board, m, legal) -> tuple:
    color = board.turn
    if m["piece"]:
        kind = PieceType(m["piece"])
        file_hint, rank_hint = m["from_file"], m["from_rank"]
        capture = bool(m["capture"])
        to = index(m["to"])
        promo = None
    else:
        kind = PieceType.PAWN
        file_hint, rank_hint = m["pawn_file"], None
        capture = bool(m["pawn_capture"])
        to = index(m["pawn_to"])
        promo = PieceType(m["promotion"]) if m["promotion"] else None

    if promo is not None and to // 8 != _last_row(color):
        raise errors.PromotionError(invalid_promotion=True)

    grid = board._grid
    matches = []
    for ply in legal:
        frm, dest, ply_promo, flag = ply
        if dest != to or flag >= _CASTLE_K or grid[frm].type is not kind or ply_promo is not promo:
            continue
        if file_hint and FILES[frm % 8] != file_hint:
            continue
        if rank_hint and str(8 - frm // 8) != rank_hint:
            continue
        if kind is PieceType.PAWN and (frm % 8 != to % 8) != capture:
            continue  # "exd5" must be a capture and "d5" a push
        matches.append(ply)

    if len(matches) == 1:
        if kind is not PieceType.PAWN:
            target = grid[to]
            if capture and target is None:
                raise errors.NothingToCaptureError(NAMES[to])
            if not capture and target is not None:
                raise errors.PieceOnSquareError(NAMES[to], False)
        return matches[0]
    if len(matches) > 1:
        raise errors.MultiplePiecesFoundError(NAMES[to], [NAMES[ply[0]] for ply in matches], kind)
    _diagnose(board, kind, file_hint, rank_hint, capture, to, promo)
    raise errors.MoveIntoCheckError()


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


def _diagnose(board, kind, file_hint, rank_hint, capture, to, promo) -> None:
    """Raise the specific reason a SAN move matched nothing; return if none applies
    (the caller then reports the move as leaving the king in check)."""
    color = board.turn
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


def _resolve_uci(board, text, m, legal) -> tuple:
    frm, to = index(m["from"]), index(m["to"])
    promo = PieceType(m["promotion"].upper()) if m["promotion"] else None
    for ply in legal:
        if ply[0] == frm and ply[1] == to and ply[2] is promo:
            return ply

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
        raise errors.MoveIntoCheckError()
    pseudo = [ply for ply in board._pseudo(color) if ply[0] == frm and ply[1] == to]
    if pseudo:
        if piece.type is PieceType.PAWN and last_row and promo is None:
            raise errors.PromotionError(need_promotion=True)
        raise errors.MoveIntoCheckError()
    raise errors.IllegalMoveError(text, f"the {piece.type.full_name} on {m['from']} cannot move to {m['to']}")
