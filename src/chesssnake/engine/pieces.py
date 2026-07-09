"""Chess pieces: the `Piece` base class and the six concrete piece types.

Movement is expressed as ``(di, dj)`` direction vectors driven through two shared
scan helpers (:func:`_slide` for the long-range Rook/Bishop/Queen, :func:`_step`
for the single-step Knight/King/Pawn). Each piece exposes:

- ``threatens(square, board)`` — squares it attacks from ``square`` (ignores pins).
- ``can_move(square, board)`` — whether it has at least one legal move (pin-aware).
- ``find_all(board, square, color, ...)`` — squares holding such a piece that could
  reach ``square`` (never raises; used for threat detection).
- ``find_one(board, square, color, capture, ...)`` — resolve algebraic notation to the
  single piece that made the move, validating the target and raising on 0/ambiguous.
"""

from .enums import Color, PieceType
from .errors import (
    CaptureOwnPieceError,
    MultiplePiecesFoundError,
    NothingToCaptureError,
    PieceNotFoundError,
    PieceOnSquareError,
)
from .notation import get_c_notation, matches_disambiguation

# Direction vectors (di, dj). i grows downward (toward rank 1), j grows toward file 'h'.
ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))
ALL_DIRECTIONS = ORTHOGONAL + DIAGONAL
KNIGHT_JUMPS = ((2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2))


def _slide(board, i, j, directions):
    """Yield squares outward from ``(i, j)`` along each direction until blocked.

    The first occupied square encountered in a direction is yielded (so callers
    can inspect the blocker) and then the scan of that direction stops.
    """
    for di, dj in directions:
        step = 1
        while True:
            sq = board[i + di * step, j + dj * step]
            if sq is None:
                break
            yield sq
            if sq.piece is not None:
                break
            step += 1


def _step(board, i, j, directions):
    """Yield the single on-board square one step from ``(i, j)`` in each direction."""
    for di, dj in directions:
        sq = board[i + di, j + dj]
        if sq is not None:
            yield sq


def _reachable(squares, color):
    """Filter ``squares`` to those a piece of ``color`` may move onto (empty or enemy)."""
    return [sq for sq in squares if sq.piece is None or sq.piece.color != color]


def _find(candidate_squares, piecetype, color, file_limit, rank_limit):
    """Squares among ``candidate_squares`` holding ``piecetype``/``color`` matching disambiguation."""
    return [
        sq
        for sq in candidate_squares
        if sq is not None
        and sq.piece is not None
        and sq.piece.piecetype == piecetype
        and sq.piece.color == color
        and matches_disambiguation(sq, file_limit, rank_limit)
    ]


def _validate_target(square, color, capture):
    """Validate the destination ``square`` for a (non-pawn) move by ``color``.

    :raises NothingToCaptureError: capture indicated but the square is empty.
    :raises CaptureOwnPieceError: capture indicated but the square holds a friendly piece.
    :raises PieceOnSquareError: non-capture move onto an occupied square.
    """
    if capture:
        if square.piece is None:
            raise NothingToCaptureError(square)
        if square.piece.color == color:
            raise CaptureOwnPieceError(square)
    elif square.piece is not None:
        raise PieceOnSquareError(square, square.piece.color == color)


class Piece:
    """
    Base class representing a chess piece.

    :ivar piecetype: The :class:`~chesssnake.engine.enums.PieceType` of the piece.
    :ivar color: The piece's :class:`~chesssnake.engine.enums.Color`.
    """

    _TYPE: "PieceType | None" = None  # the PieceType of concrete subclasses

    def __init__(self, piecetype, color):
        """
        :param piecetype: The piece type (a :class:`PieceType` or its letter code).
        :param color: The piece color (a :class:`Color`, or 0/1, or '0'/'1').
        """
        self.piecetype = PieceType(piecetype)
        self.color = Color(int(color))

    def fullname(self):
        """The lowercase english name of the piece (e.g. ``"knight"``)."""
        return self.piecetype.full_name

    # dev note:
    # if the king is already in check, then this will *always* return true
    # only use this function if we know the king is not in check already
    def is_pinned(self, square, board):
        """
        Whether removing this piece from ``square`` would expose its king to check.

        Kings themselves are never pinned.
        """
        if self.piecetype == PieceType.KING:
            return False

        with board.lifted(square):
            return board.check_for_check(self.color)

    def _pinned_move_allowed(self, square, board):
        """For a pinned sliding piece: whether it can still capture the lone pinner.

        Shared by Rook/Bishop/Queen. The pinning attacker is the threat on the king
        that appears only once removing this piece is accounted for; the piece may
        move iff it is that attacker's square and it threatens it.
        """
        king_threats1 = board.threats_on(board.find_king(self.color), self.color)
        with board.lifted(square):
            king_threats2 = board.threats_on(board.find_king(self.color), self.color)

        # the threat present in exactly one of the two scans is the one being blocked
        king_threats = [t for t in king_threats1 + king_threats2 if t not in king_threats1 or t not in king_threats2]

        if len(king_threats) != 1:
            return False
        return king_threats[0] in self.threatens(square, board)

    @classmethod
    def find_one(cls, board, square, color, capture, file_limit=None, rank_limit=None):
        """
        Resolve algebraic notation to the single piece of this type that made the move.

        :param capture: Whether the move captures on ``square``.
        :param file_limit: Optional file disambiguation ('a'-'h').
        :param rank_limit: Optional rank disambiguation ('1'-'8').
        :return: The :class:`Square` the moving piece started on.
        :rtype: Square
        :raises PieceNotFoundError: If no eligible piece is found.
        :raises MultiplePiecesFoundError: If more than one matching piece is found.
        :raises NothingToCaptureError: If a capture has no target piece.
        :raises CaptureOwnPieceError: If a capture would take a friendly piece.
        :raises PieceOnSquareError: If a non-capture lands on an occupied square.
        """
        color = Color(color)
        candidates = cls.find_all(board, square, color, file_limit, rank_limit)

        if len(candidates) == 0:
            raise PieceNotFoundError(square, cls._TYPE)
        if len(candidates) > 1:
            raise MultiplePiecesFoundError(square, candidates)

        _validate_target(square, color, capture)
        return candidates[0]


class Rook(Piece):
    """A Rook: moves any distance along ranks and files."""

    _TYPE = PieceType.ROOK

    def __init__(self, color):
        super().__init__(PieceType.ROOK, color)

    def threatens(self, square, board):
        """Squares this rook attacks from ``square`` (ignoring pins)."""
        return _reachable(_slide(board, square.i, square.j, ORTHOGONAL), self.color)

    def can_move(self, square, board):
        """Whether this rook has at least one legal move (pin-aware)."""
        if self.is_pinned(square, board):
            return self._pinned_move_allowed(square, board)
        return len(self.threatens(square, board)) > 0

    @classmethod
    def find_all(cls, board, square, color, file_limit=None, rank_limit=None):
        """Rook squares of ``color`` that could reach ``square`` (never raises)."""
        color = Color(color)
        return _find(_slide(board, square.i, square.j, ORTHOGONAL), PieceType.ROOK, color, file_limit, rank_limit)


class Knight(Piece):
    """A Knight: jumps in an L-shape, over intervening pieces."""

    _TYPE = PieceType.KNIGHT

    def __init__(self, color):
        super().__init__(PieceType.KNIGHT, color)

    def threatens(self, square, board):
        """Squares this knight attacks from ``square`` (ignoring pins)."""
        return _reachable(_step(board, square.i, square.j, KNIGHT_JUMPS), self.color)

    def can_move(self, square, board):
        """Whether this knight has a legal move. A pinned knight can never move."""
        if self.is_pinned(square, board):
            return False
        return len(self.threatens(square, board)) > 0

    @classmethod
    def find_all(cls, board, square, color, file_limit=None, rank_limit=None):
        """Knight squares of ``color`` that could reach ``square`` (never raises)."""
        color = Color(color)
        return _find(_step(board, square.i, square.j, KNIGHT_JUMPS), PieceType.KNIGHT, color, file_limit, rank_limit)


class Bishop(Piece):
    """A Bishop: moves any distance along diagonals."""

    _TYPE = PieceType.BISHOP

    def __init__(self, color):
        super().__init__(PieceType.BISHOP, color)

    def threatens(self, square, board):
        """Squares this bishop attacks from ``square`` (ignoring pins)."""
        return _reachable(_slide(board, square.i, square.j, DIAGONAL), self.color)

    def can_move(self, square, board):
        """Whether this bishop has at least one legal move (pin-aware)."""
        if self.is_pinned(square, board):
            return self._pinned_move_allowed(square, board)
        return len(self.threatens(square, board)) > 0

    @classmethod
    def find_all(cls, board, square, color, file_limit=None, rank_limit=None):
        """Bishop squares of ``color`` that could reach ``square`` (never raises)."""
        color = Color(color)
        return _find(_slide(board, square.i, square.j, DIAGONAL), PieceType.BISHOP, color, file_limit, rank_limit)


class Queen(Piece):
    """A Queen: moves any distance along ranks, files, and diagonals."""

    _TYPE = PieceType.QUEEN

    def __init__(self, color):
        super().__init__(PieceType.QUEEN, color)

    def threatens(self, square, board):
        """Squares this queen attacks from ``square`` (ignoring pins)."""
        return _reachable(_slide(board, square.i, square.j, ALL_DIRECTIONS), self.color)

    def can_move(self, square, board):
        """Whether this queen has at least one legal move (pin-aware)."""
        if self.is_pinned(square, board):
            return self._pinned_move_allowed(square, board)
        return len(self.threatens(square, board)) > 0

    @classmethod
    def find_all(cls, board, square, color, file_limit=None, rank_limit=None):
        """Queen squares of ``color`` that could reach ``square`` (never raises)."""
        color = Color(color)
        return _find(_slide(board, square.i, square.j, ALL_DIRECTIONS), PieceType.QUEEN, color, file_limit, rank_limit)


class King(Piece):
    """A King: moves one square in any direction; may castle."""

    _TYPE = PieceType.KING

    def __init__(self, color):
        super().__init__(PieceType.KING, color)

    def threatens(self, square, board):
        """Adjacent squares this king attacks from ``square`` (ignoring pins)."""
        return _reachable(_step(board, square.i, square.j, ALL_DIRECTIONS), self.color)

    def can_move(self, square, board):
        """Whether this king can legally step to any unattacked adjacent square."""
        for threat in self.threatens(square, board):
            if len(board.threats_on(threat, self.color)) == 0:
                return True
        return False

    def can_castle(self, board, direction):
        """
        Whether the king may castle to the given side.

        Castling availability (king and the relevant rook never having moved, and the
        rook not having been captured) is read straight from the board's FEN castling
        rights; this method additionally verifies the squares between are empty and the
        king's path square is not attacked.

        :param direction: ``'K'`` (kingside) or ``'Q'`` (queenside).
        :rtype: bool
        """
        x = 7 if self.color == Color.WHITE else 0

        # the FEN right for this side/direction must still be available
        right = direction if self.color == Color.WHITE else direction.lower()
        if right not in board.castling:
            return False

        # king side: rook on the h-file (j=7); king crosses f (j=5) to g (j=6)
        if direction == "K":
            rook_square = board[x, 7]
            empties = (board[x, 5], board[x, 6])
            king_path = board[x, 5]
        # queen side: rook on the a-file (j=0); king crosses d (j=3) to c (j=2)
        else:
            rook_square = board[x, 0]
            empties = (board[x, 1], board[x, 2], board[x, 3])
            king_path = board[x, 2]

        return (
            rook_square.piece is not None
            and rook_square.piece.piecetype == PieceType.ROOK
            and rook_square.piece.color == self.color
            and all(sq.piece is None for sq in empties)
            and len(board.threats_on(king_path, self.color)) == 0
        )

    @classmethod
    def find_all(cls, board, square, color, file_limit=None, rank_limit=None):
        """King squares of ``color`` adjacent to ``square`` (never raises)."""
        color = Color(color)
        return _find(_step(board, square.i, square.j, ALL_DIRECTIONS), PieceType.KING, color, file_limit, rank_limit)


class Pawn(Piece):
    """A Pawn: advances forward, captures diagonally, and may capture en passant."""

    _TYPE = PieceType.PAWN

    def __init__(self, color):
        super().__init__(PieceType.PAWN, color)

    def threatens(self, square, board):
        """The two diagonally-forward squares this pawn attacks (ignoring pins)."""
        forward = -1 if self.color == Color.WHITE else 1
        squares = (
            sq
            for sq in (board[square.i + forward, square.j + 1], board[square.i + forward, square.j - 1])
            if sq is not None
        )
        return _reachable(squares, self.color)

    def can_move(self, square, board):
        """Whether this pawn has a legal move (forward push, capture, or en passant)."""
        # if the pawn is pinned, it may only move if it can capture its lone pinner
        if self.is_pinned(square, board):
            king_threats1 = board.threats_on(board.find_king(self.color), self.color)
            with board.lifted(square):
                king_threats2 = board.threats_on(board.find_king(self.color), self.color)
            king_threats = [
                t for t in king_threats1 + king_threats2 if t not in king_threats1 or t not in king_threats2
            ]
            return len(king_threats) > 1 and king_threats[0] in self.threatens(square, board)

        forward = -1 if self.color == Color.WHITE else 1

        # can advance one square if the square ahead is empty
        ahead = board[square.i + forward, square.j]
        if ahead is not None and ahead.piece is None:
            return True

        # can capture an adjacent enemy piece
        for threat in self.threatens(square, board):
            if threat.piece is not None and threat.piece.color != self.color:
                return True

        return False

    @classmethod
    def find_all(cls, board, square, color, capture, file_limit=None, rank_limit=None):
        """
        Pawn squares of ``color`` that could move to ``square`` (never raises, no side effects).

        :param capture: Whether the move is a diagonal capture (``True``) or a forward push.
        """
        color = Color(color)
        # a pawn sits "behind" its destination: below it for white (i increases downward)
        behind = 1 if color == Color.WHITE else -1

        if capture:
            candidates = (board[square.i + behind, square.j + 1], board[square.i + behind, square.j - 1])
            return _find(candidates, PieceType.PAWN, color, file_limit, rank_limit)

        # forward push: the pawn is one square behind, or two if the square between is empty
        one_back = board[square.i + behind, square.j]
        if one_back is not None and one_back.piece is not None:
            return _find([one_back], PieceType.PAWN, color, file_limit, rank_limit)

        two_back = board[square.i + behind * 2, square.j]
        if one_back is not None and one_back.piece is None and two_back is not None:
            return _find([two_back], PieceType.PAWN, color, file_limit, rank_limit)

        return []

    @classmethod
    def find_one(cls, board, square, color, capture, file_limit=None, rank_limit=None, en=False):
        """
        Resolve a pawn move to the single pawn that made it.

        A two-square advance records the en-passant target on the board. An ``en``
        capture onto an empty square is validated against the last double-step.

        :return: The :class:`Square` the pawn started on.
        :rtype: Square
        :raises PieceNotFoundError: If no eligible pawn is found.
        :raises MultiplePiecesFoundError: If the move is ambiguous.
        :raises NothingToCaptureError: If a capture has no (regular or en-passant) target.
        :raises CaptureOwnPieceError: If a capture would take a friendly piece.
        :raises PieceOnSquareError: If a forward push lands on an occupied square.
        """
        color = Color(color)
        candidates = cls.find_all(board, square, color, capture, file_limit, rank_limit)

        if len(candidates) == 0:
            raise PieceNotFoundError(square, PieceType.PAWN)
        if len(candidates) > 1:
            raise MultiplePiecesFoundError(square, candidates)

        pawn_square = candidates[0]

        if not capture:
            if square.piece is not None:
                raise PieceOnSquareError(square, square.piece.color == color)
            # a two-square advance leaves an en-passant target on the crossed square
            # (the FEN en-passant field: the square the pawn skipped over)
            if abs(pawn_square.i - square.i) == 2:
                skipped_i = (pawn_square.i + square.i) // 2
                board.en_passant = get_c_notation(skipped_i, square.j)
        else:
            if square.piece is None:
                if not (en and cls._valid_en_passant(board, square, color)):
                    raise NothingToCaptureError(square)
            elif square.piece.color == color:
                raise CaptureOwnPieceError(square)

        return pawn_square

    @staticmethod
    def _valid_en_passant(board, square, color):
        """Whether an en-passant capture onto empty ``square`` is legal for ``color``."""
        # the capturing pawn's destination must be the FEN en-passant target square
        if board.en_passant != square.c_notation:
            return False
        behind = 1 if color == Color.WHITE else -1
        captured = board[square.i + behind, square.j]
        return (
            captured is not None
            and captured.piece is not None
            and captured.piece.piecetype == PieceType.PAWN
            and captured.piece.color != color
        )
