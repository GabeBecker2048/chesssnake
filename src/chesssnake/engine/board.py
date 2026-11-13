"""The `Board`: a chess position, its legal moves, and the rules that end a game.

Inside, the board is a list of 64 squares (index ``i * 8 + j``, a8 first; see
:mod:`chesssnake.engine._notation`) holding :class:`Piece` values or ``None``.
Moves are generated straight from precomputed tables and tested for legality by
playing them in place and taking them back (make/unmake), never by copying the
board. None of that is public: the public surface is square names, :class:`Piece`
and :class:`Move` values, and the query methods below, so the inside can change
(a bitboard engine is planned for 0.16.0) without breaking callers.
"""

from . import _fen, _parse, _san, errors
from ._notation import NAMES, index, is_valid_notation
from .enums import Color, GameStatus, PieceType, Termination
from .move import Move
from .piece import PIECES, Piece

WHITE, BLACK = Color.WHITE, Color.BLACK
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = (
    PieceType.PAWN,
    PieceType.KNIGHT,
    PieceType.BISHOP,
    PieceType.ROOK,
    PieceType.QUEEN,
    PieceType.KING,
)

# --- precomputed tables ----------------------------------------------------------
# Row deltas grow toward rank 1 (i increases downward), column deltas toward file h.


def _on_board(i, j):
    return 0 <= i < 8 and 0 <= j < 8


def _ray(idx, di, dj):
    i, j = divmod(idx, 8)
    out = []
    i, j = i + di, j + dj
    while _on_board(i, j):
        out.append(i * 8 + j)
        i, j = i + di, j + dj
    return tuple(out)


def _steps(idx, deltas):
    i, j = divmod(idx, 8)
    return tuple((i + di) * 8 + (j + dj) for di, dj in deltas if _on_board(i + di, j + dj))


_ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
_DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))
_KNIGHT_JUMPS = ((2, 1), (2, -1), (-2, 1), (-2, -1), (1, 2), (1, -2), (-1, 2), (-1, -2))

# For each square, the non-empty rays outward (nearest square first).
ORTHOGONAL_RAYS = tuple(tuple(r for r in (_ray(s, *d) for d in _ORTHOGONAL) if r) for s in range(64))
DIAGONAL_RAYS = tuple(tuple(r for r in (_ray(s, *d) for d in _DIAGONAL) if r) for s in range(64))
QUEEN_RAYS = tuple(ORTHOGONAL_RAYS[s] + DIAGONAL_RAYS[s] for s in range(64))
KNIGHT_TARGETS = tuple(_steps(s, _KNIGHT_JUMPS) for s in range(64))
KING_TARGETS = tuple(_steps(s, _ORTHOGONAL + _DIAGONAL) for s in range(64))
# PAWN_ATTACKS[color][s]: the squares a pawn of ``color`` standing on ``s`` attacks.
PAWN_ATTACKS = (
    tuple(_steps(s, ((-1, -1), (-1, 1))) for s in range(64)),  # white moves up the board
    tuple(_steps(s, ((1, -1), (1, 1))) for s in range(64)),  # black moves down
)

SLIDER_RAYS = {ROOK: ORTHOGONAL_RAYS, BISHOP: DIAGONAL_RAYS, QUEEN: QUEEN_RAYS}

# The canonical pieces of each colour, indexed by Color (an int), and each colour's
# opponent. The hot paths use these rather than ``PIECES[type, color]`` and
# ``color.opponent``: hashing an Enum and reading a property both run Python code,
# which was about a fifth of the time spent testing whether a square is attacked.
PAWNS = (PIECES[PAWN, WHITE], PIECES[PAWN, BLACK])
KNIGHTS = (PIECES[KNIGHT, WHITE], PIECES[KNIGHT, BLACK])
BISHOPS = (PIECES[BISHOP, WHITE], PIECES[BISHOP, BLACK])
ROOKS = (PIECES[ROOK, WHITE], PIECES[ROOK, BLACK])
QUEENS = (PIECES[QUEEN, WHITE], PIECES[QUEEN, BLACK])
KINGS = (PIECES[KING, WHITE], PIECES[KING, BLACK])
OPPONENT = (BLACK, WHITE)

# What a pawn may promote to, in the order moves are listed.
PROMOTIONS = (QUEEN, ROOK, BISHOP, KNIGHT)

# Move flags (the fourth field of a ply).
NORMAL, DOUBLE_STEP, EN_PASSANT, CASTLE_K, CASTLE_Q = range(5)

# Castling rights lost when a piece leaves, or is captured on, one of these squares.
_CASTLE_MASK = {60: "KQ", 4: "kq", 63: "K", 56: "Q", 7: "k", 0: "q"}


class Board:
    """
    A chess position: the pieces, the side to move, castling and en-passant rights,
    the clocks, and whether the game has ended.

    Build one with ``Board()`` (the starting position) or :meth:`from_fen`. It changes
    only through :meth:`move` and :meth:`undo`. Squares are named in algebraic form
    (``"e4"``) everywhere.

    The six FEN fields are plain attributes, kept in FEN's own form:

    :ivar turn: The :class:`Color` to move.
    :ivar castling: The castling rights still available, a subset of ``"KQkq"``
        (``""`` when none).
    :ivar en_passant: The en-passant target square (the square a pawn skipped on its
        last double step, e.g. ``"e3"``), or ``None``.
    :ivar halfmove_clock: Plies since the last pawn move or capture (fifty-move rule).
    :ivar fullmove_number: The move number; starts at 1, increments after Black moves.

    And the outcome, set by :meth:`move` when a move ends the game by rule:

    :ivar status: The :class:`GameStatus`.
    :ivar termination: Why the game ended (:class:`Termination`), or ``None`` in play.
        Threefold repetition needs the game's history, so
        :class:`~chesssnake.engine.game.Game` applies that one.
    """

    def __init__(self, fen: "str | None" = None):
        """
        :param fen: A FEN position, or ``None`` for the standard starting position.
        :raises ValueError: if ``fen`` is not a valid FEN (the message says why).
        """
        self._load(*_fen.parse(_fen.INITIAL_FEN if fen is None else fen))

    @classmethod
    def from_fen(cls, fen: str) -> "Board":
        """
        The position described by a FEN string.

        :raises ValueError: if ``fen`` is not a valid FEN (the message says why).
        """
        return cls(fen)

    @classmethod
    def _from_grid(cls, grid, turn=WHITE, castling="", en_passant=None) -> "Board":
        """A board from a 64-entry grid, skipping FEN validation (internal and tests:
        it allows positions without kings)."""
        board = cls.__new__(cls)
        board._load(
            [PIECES[p.type, p.color] if p is not None else None for p in grid], Color(turn), castling, en_passant, 0, 1
        )
        return board

    def _load(self, grid, turn, castling, en_passant, halfmove, fullmove):
        self._grid: list[Piece | None] = grid
        self.turn: Color = turn
        self.castling: str = castling
        self.en_passant: str | None = en_passant
        self.halfmove_clock: int = halfmove
        self.fullmove_number: int = fullmove
        self.status: GameStatus = GameStatus.IN_PLAY
        self.termination: Termination | None = None
        # each side's king square (None in a kingless test position)
        self._kings: list[int | None] = [None, None]
        for idx, piece in enumerate(grid):
            if piece is not None and piece.type is KING:
                self._kings[piece.color] = idx
        # (ply, undo record, Move) for every move played, for undo()
        self._stack: list = []

    # --- reading the position -----------------------------------------------------

    @property
    def fen(self) -> str:
        """The position as a FEN string."""
        return _fen.write(self)

    def piece_at(self, square: str) -> "Piece | None":
        """
        The piece on ``square`` (e.g. ``"e4"``), or ``None`` if it is empty.

        :raises ValueError: if ``square`` is not a square name.
        """
        return self._grid[index(square)]

    def pieces(self, piece_type: PieceType, color: Color) -> list[str]:
        """
        The squares holding pieces of one type and color, a8 to h1 rank by rank.

        ``board.pieces(PieceType.KNIGHT, Color.WHITE)`` is ``["b1", "g1"]`` at the start.
        """
        wanted = PIECES[PieceType(piece_type), Color(color)]
        return [NAMES[idx] for idx, piece in enumerate(self._grid) if piece is wanted]

    def is_attacked(self, square: str, by: Color) -> bool:
        """
        Whether any piece of color ``by`` attacks ``square``, whatever stands on it.

        Pins do not matter here: a pinned piece still attacks.

        :raises ValueError: if ``square`` is not a square name.
        """
        return self._attacked(index(square), Color(by))

    def is_check(self) -> bool:
        """Whether the side to move is in check."""
        king = self._kings[self.turn]
        return king is not None and self._attacked(king, self.turn.opponent)

    def is_checkmate(self) -> bool:
        """Whether the side to move is checkmated."""
        return self.is_check() and not self._has_legal_move()

    def is_stalemate(self) -> bool:
        """Whether the side to move is stalemated (not in check, no legal move)."""
        return not self.is_check() and not self._has_legal_move()

    def is_insufficient_material(self) -> bool:
        """
        Whether neither side has enough material to checkmate.

        Covers the standard dead positions: king against king, king and one minor
        piece against king, and kings with bishops that all stand on one square color.
        Any pawn, rook or queen means mate is still possible.
        """
        minors = 0
        bishop_square_colors = set()
        bishops = 0
        for idx, piece in enumerate(self._grid):
            if piece is None or piece.type is KING:
                continue
            if piece.type in (PAWN, ROOK, QUEEN):
                return False
            minors += 1
            if piece.type is BISHOP:
                bishops += 1
                bishop_square_colors.add((idx // 8 + idx % 8) % 2)
        if minors <= 1:
            return True
        return minors == bishops and len(bishop_square_colors) == 1

    def legal_moves(self) -> list[dict]:
        """
        Every legal move for the side to move.

        Each entry is ``{"from", "to", "san", "promotion"}``: square names, the move
        in chesssnake notation (which :meth:`move` accepts back), and the promotion
        letter or ``None``. Castling has ``"to": None`` and ``"san"`` ``"0-0"`` or
        ``"0-0-0"``. This is also the shape of the REST ``legal-moves`` response.

        :rtype: list[dict]
        """
        legal = self._legal()
        out = []
        for ply, san in zip(legal, _san.sans(self, legal)):
            frm, to, promo, flag = ply
            castle = flag >= CASTLE_K
            out.append(
                {
                    "from": NAMES[frm],
                    "to": None if castle else NAMES[to],
                    "san": san,
                    "promotion": promo.value if promo is not None else None,
                }
            )
        return out

    # --- changing the position ----------------------------------------------------

    def move(self, move: str) -> Move:
        """
        Play a move for the side to move.

        Accepts SAN (``e4``, ``Nf3``, ``exd5``, ``Nbd2``, ``e8=Q`` or ``e8Q``, ``O-O`` or
        ``0-0``, with or without ``+``/``#``) and UCI (``e2e4``, ``e7e8q``, castling as
        the king's move ``e1g1``). Afterwards, :attr:`status` and :attr:`termination`
        record a checkmate, stalemate, insufficient material or the fifty-move rule.

        :param move: The move string.
        :return: The :class:`Move` played.
        :raises errors.InvalidNotationError: If the string is not a move at all.
        :raises errors.GameOverError: If the game has already ended.
        :raises errors.MoveIntoCheckError: If the move would leave the king in check.
        :raises errors.PromotionError: If a promotion is missing, or given where none is possible.
        :raises errors.InvalidCastleError: If castling that way is not allowed.
        :raises errors.PieceNotFoundError: If no piece of that kind can reach the square.
        :raises errors.MultiplePiecesFoundError: If more than one can and the move does not say which.
        :raises errors.NothingToCaptureError: If a capture names an empty square.
        :raises errors.CaptureOwnPieceError: If a capture names a square holding an own piece.
        :raises errors.PieceOnSquareError: If a non-capture names an occupied square.
        :raises errors.IllegalMoveError: If a UCI move is not legal for any other reason.
        """
        if not is_valid_notation(move):
            raise errors.InvalidNotationError(move)
        if self.status != GameStatus.IN_PLAY:
            raise errors.GameOverError()

        legal = self._legal()
        ply = _parse.resolve(self, move.strip(), legal)
        san = _san.san(self, ply, legal)
        frm, to, promo, flag = ply
        mover = self.turn
        piece = self._grid[frm]
        assert piece is not None
        captured = PIECES[PAWN, mover.opponent] if flag == EN_PASSANT else self._grid[to]

        undo = self._make(ply)
        self._update_outcome(mover)
        if self.termination is Termination.CHECKMATE:
            san += "#"
        elif self.is_check():
            san += "+"

        played = Move(
            from_square=NAMES[frm],
            to_square=NAMES[to],
            piece=piece,
            san=san,
            promotion=promo,
            captured=captured,
            castle="K" if flag == CASTLE_K else "Q" if flag == CASTLE_Q else None,
            en_passant=flag == EN_PASSANT,
        )
        self._stack.append((ply, undo, played))
        return played

    def undo(self) -> Move:
        """
        Take back the last move played on this board, restoring everything
        (pieces, rights, clocks, outcome).

        :return: The :class:`Move` taken back.
        :raises IndexError: if no move has been played on this board.
        """
        if not self._stack:
            raise IndexError("no move to undo")
        ply, undo, played = self._stack.pop()
        self._unmake(ply, undo)
        return played

    def copy(self) -> "Board":
        """An independent copy of this board, including its undo history."""
        other = Board.__new__(Board)
        other.__dict__.update(self.__dict__)
        other._grid = list(self._grid)
        other._kings = list(self._kings)
        other._stack = list(self._stack)
        return other

    def __str__(self) -> str:
        from .text import render_text

        return render_text(self, figurines=False)

    def __repr__(self) -> str:
        return f"Board({self.fen!r})"

    # --- the engine (internal) ----------------------------------------------------

    def _update_outcome(self, mover: Color) -> None:
        """Set status/termination after ``mover`` moved (threefold is Game's job)."""
        if not self._has_legal_move():
            if self.is_check():
                self.status = GameStatus.won_by(mover)
                self.termination = Termination.CHECKMATE
            else:
                self.status = GameStatus.DRAW
                self.termination = Termination.STALEMATE
        elif self.is_insufficient_material():
            self.status = GameStatus.DRAW
            self.termination = Termination.INSUFFICIENT_MATERIAL
        elif self.halfmove_clock >= 100:
            self.status = GameStatus.DRAW
            self.termination = Termination.FIFTY_MOVE

    def _attacked(self, idx: int, by: Color) -> bool:
        """Whether a piece of color ``by`` attacks square ``idx``."""
        grid = self._grid
        knight = KNIGHTS[by]
        for s in KNIGHT_TARGETS[idx]:
            if grid[s] is knight:
                return True
        pawn = PAWNS[by]
        # a pawn of ``by`` attacks idx from where an opposing pawn on idx would attack
        for s in PAWN_ATTACKS[OPPONENT[by]][idx]:
            if grid[s] is pawn:
                return True
        king = KINGS[by]
        for s in KING_TARGETS[idx]:
            if grid[s] is king:
                return True
        queen = QUEENS[by]
        rook = ROOKS[by]
        for ray in ORTHOGONAL_RAYS[idx]:
            for s in ray:
                piece = grid[s]
                if piece is not None:
                    if piece is rook or piece is queen:
                        return True
                    break
        bishop = BISHOPS[by]
        for ray in DIAGONAL_RAYS[idx]:
            for s in ray:
                piece = grid[s]
                if piece is not None:
                    if piece is bishop or piece is queen:
                        return True
                    break
        return False

    def _castle_ok(self, color: Color, side: str) -> bool:
        """
        Whether ``color`` may castle on ``side`` (``"K"`` or ``"Q"``), short of the
        king's destination being attacked, which the legality test catches.

        Needs the right, king and rook on their home squares, the squares between
        empty, the king not in check, and the square it crosses not attacked. (On the
        queenside, b1/b8 must be empty but may be attacked: the king never crosses it.)
        """
        right = side if color is WHITE else side.lower()
        if right not in self.castling:
            return False
        row = 56 if color is WHITE else 0
        grid = self._grid
        king_sq = row + 4
        if grid[king_sq] is not KINGS[color]:
            return False
        between: tuple[int, ...]
        if side == "K":
            rook_sq, between, crossed = row + 7, (row + 5, row + 6), row + 5
        else:
            rook_sq, between, crossed = row, (row + 1, row + 2, row + 3), row + 3
        if grid[rook_sq] is not ROOKS[color]:
            return False
        if any(grid[s] is not None for s in between):
            return False
        opponent = OPPONENT[color]
        return not self._attacked(king_sq, opponent) and not self._attacked(crossed, opponent)

    def _pseudo(self, color: Color) -> list[tuple]:
        """
        Every pseudo-legal ply for ``color``: moves the pieces can make, before asking
        whether the king is left in check. A ply is ``(from, to, promotion, flag)``.
        """
        grid = self._grid
        out: list[tuple] = []
        append = out.append
        opponent = OPPONENT[color]
        if color is WHITE:
            forward, start_row, last_row = -8, 6, 0
        else:
            forward, start_row, last_row = 8, 1, 7
        ep = index(self.en_passant) if self.en_passant is not None else -1
        enemy_pawn = PAWNS[opponent]

        for frm, piece in enumerate(grid):
            if piece is None or piece.color is not color:
                continue
            kind = piece.type
            if kind is PAWN:
                one = frm + forward
                if grid[one] is None:
                    if one // 8 == last_row:
                        for promo in PROMOTIONS:
                            append((frm, one, promo, NORMAL))
                    else:
                        append((frm, one, None, NORMAL))
                        if frm // 8 == start_row and grid[one + forward] is None:
                            append((frm, one + forward, None, DOUBLE_STEP))
                for to in PAWN_ATTACKS[color][frm]:
                    target = grid[to]
                    if target is not None:
                        if target.color is opponent:
                            if to // 8 == last_row:
                                for promo in PROMOTIONS:
                                    append((frm, to, promo, NORMAL))
                            else:
                                append((frm, to, None, NORMAL))
                    elif to == ep and grid[to - forward] is enemy_pawn:
                        append((frm, to, None, EN_PASSANT))
            elif kind is KNIGHT or kind is KING:
                for to in (KNIGHT_TARGETS if kind is KNIGHT else KING_TARGETS)[frm]:
                    target = grid[to]
                    if target is None or target.color is opponent:
                        append((frm, to, None, NORMAL))
            else:
                # identity tests, not a dict keyed by PieceType: no Enum hashing here
                rays = ORTHOGONAL_RAYS if kind is ROOK else DIAGONAL_RAYS if kind is BISHOP else QUEEN_RAYS
                for ray in rays[frm]:
                    for to in ray:
                        target = grid[to]
                        if target is None:
                            append((frm, to, None, NORMAL))
                        else:
                            if target.color is opponent:
                                append((frm, to, None, NORMAL))
                            break

        if self.castling:
            row = 56 if color is WHITE else 0
            if self._castle_ok(color, "K"):
                append((row + 4, row + 6, None, CASTLE_K))
            if self._castle_ok(color, "Q"):
                append((row + 4, row + 2, None, CASTLE_Q))
        return out

    def _make(self, ply: tuple) -> tuple:
        """Play ``ply`` in place for the side to move; return what :meth:`_unmake` needs."""
        frm, to, promo, flag = ply
        grid = self._grid
        color = self.turn
        piece = grid[frm]
        assert piece is not None
        captured = grid[to]
        undo = (
            captured,
            self.castling,
            self.en_passant,
            self.halfmove_clock,
            self.fullmove_number,
            self.status,
            self.termination,
            self._kings[color],
        )

        if flag == EN_PASSANT:
            grid[to + 8 if color is WHITE else to - 8] = None
        elif flag == CASTLE_K:
            grid[frm + 1], grid[frm + 3] = grid[frm + 3], None
        elif flag == CASTLE_Q:
            grid[frm - 1], grid[frm - 4] = grid[frm - 4], None

        grid[to] = PIECES[promo, color] if promo is not None else piece
        grid[frm] = None
        if piece.type is KING:
            self._kings[color] = to

        self.en_passant = NAMES[(frm + to) // 2] if flag == DOUBLE_STEP else None
        if self.castling:
            for s in (frm, to):
                lost = _CASTLE_MASK.get(s)
                if lost:
                    for letter in lost:
                        self.castling = self.castling.replace(letter, "")
        if piece.type is PAWN or captured is not None:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1
        if color is BLACK:
            self.fullmove_number += 1
        self.turn = OPPONENT[color]
        return undo

    def _unmake(self, ply: tuple, undo: tuple) -> None:
        """Take back ``ply``, the last move made, using the record :meth:`_make` returned."""
        frm, to, promo, flag = ply
        captured, castling, en_passant, halfmove, fullmove, status, termination, king = undo
        color = OPPONENT[self.turn]  # the side that made the move
        grid = self._grid

        grid[frm] = PAWNS[color] if promo is not None else grid[to]
        grid[to] = captured
        if flag == EN_PASSANT:
            grid[to + 8 if color is WHITE else to - 8] = PAWNS[OPPONENT[color]]
        elif flag == CASTLE_K:
            grid[frm + 3], grid[frm + 1] = grid[frm + 1], None
        elif flag == CASTLE_Q:
            grid[frm - 4], grid[frm - 1] = grid[frm - 1], None

        self._kings[color] = king
        self.turn = color
        self.castling = castling
        self.en_passant = en_passant
        self.halfmove_clock = halfmove
        self.fullmove_number = fullmove
        self.status = status
        self.termination = termination

    def _is_legal(self, ply: tuple) -> bool:
        """
        Whether pseudo-legal ``ply`` leaves the mover's king out of check, by trial:
        play it in place, look, take it back. Always right, and the reference the
        faster pin-based test in :meth:`_legal_iter` is checked against.
        """
        color = self.turn
        undo = self._make(ply)
        king = self._kings[color]
        legal = king is None or not self._attacked(king, OPPONENT[color])
        self._unmake(ply, undo)
        return legal

    def _pins(self, color: Color, king: int) -> dict:
        """
        ``color``'s pinned pieces: pinned square -> the squares it may still move to
        (the line from the king out to the pinner, the pinner's square included).

        A piece is pinned when it is the only piece between its king and an enemy
        slider that moves along that line (a rook or queen on a rank or file, a bishop
        or queen on a diagonal).
        """
        grid = self._grid
        opponent = OPPONENT[color]
        queen = QUEENS[opponent]
        pins = {}
        for rays, slider in ((ORTHOGONAL_RAYS[king], ROOKS[opponent]), (DIAGONAL_RAYS[king], BISHOPS[opponent])):
            for ray in rays:
                own = -1
                for n, s in enumerate(ray):
                    piece = grid[s]
                    if piece is None:
                        continue
                    if piece.color is color:
                        if own >= 0:
                            break  # two of our own pieces on the line: nothing is pinned
                        own = s
                        continue
                    if own >= 0 and (piece is slider or piece is queen):
                        pins[own] = ray[: n + 1]
                    break
        return pins

    def _legal_iter(self):
        """
        The legal plies for the side to move, in :meth:`_pseudo` order.

        When the king is not in check (most positions), legality is decided from the
        pins, computed once, instead of by trial for every ply: an unpinned piece
        other than the king can always move; a pinned one only along its pin line;
        the king only to a square not attacked (which is enough because it is not in
        check now, so no attack runs through its own square). Castling and en passant
        still use the trial test: they are rare, and en passant can uncover a check
        along a rank by removing two pawns at once. In check, or in a test position
        without a king, every ply is tested by trial.
        """
        color = self.turn
        pseudo = self._pseudo(color)
        king = self._kings[color]
        opponent = OPPONENT[color]
        if king is None or self._attacked(king, opponent):
            for ply in pseudo:
                if self._is_legal(ply):
                    yield ply
            return
        pins = self._pins(color, king)
        for ply in pseudo:
            frm, to, _promo, flag = ply
            if frm == king:
                legal = self._is_legal(ply) if flag >= CASTLE_K else not self._attacked(to, opponent)
            elif flag == EN_PASSANT:
                legal = self._is_legal(ply)
            else:
                line = pins.get(frm)
                legal = line is None or to in line
            if legal:
                yield ply

    def _legal(self) -> list[tuple]:
        """Every legal ply for the side to move."""
        return list(self._legal_iter())

    def _legal_by_trial(self) -> list[tuple]:
        """Every legal ply, each tested by trial: the slow reference for tests."""
        return [ply for ply in self._pseudo(self.turn) if self._is_legal(ply)]

    def _has_legal_move(self) -> bool:
        """Whether the side to move has any legal move (stops at the first)."""
        return next(self._legal_iter(), None) is not None

    def _position_key(self) -> str:
        """
        The identity of the position for repetition: placement, side to move,
        castling rights and en-passant square. As FIDE counts it, the en-passant
        square only counts when a legal en-passant capture exists.
        """
        ep = "-"
        if self.en_passant is not None:
            target = index(self.en_passant)
            pawn = PIECES[PAWN, self.turn]
            victim = target + 8 if self.turn is WHITE else target - 8
            attackers = (
                PAWN_ATTACKS[self.turn.opponent][target]
                if self._grid[victim] is PIECES[PAWN, self.turn.opponent]
                else ()
            )
            for frm in attackers:
                if self._grid[frm] is pawn and self._is_legal((frm, target, None, EN_PASSANT)):
                    ep = self.en_passant
                    break
        return f"{_fen.placement(self._grid)} {'w' if self.turn is WHITE else 'b'} {self.castling or '-'} {ep}"
