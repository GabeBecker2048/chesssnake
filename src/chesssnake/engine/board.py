"""The `Board`: the 8x8 grid plus move/undo and check/mate detection."""

import copy
from contextlib import contextmanager

from . import errors, notation
from .enums import Color, GameStatus, PieceType, Termination
from .move import Move
from .pieces import Bishop, King, Knight, Pawn, Queen, Rook
from .san import to_san
from .square import Square

# The four pieces a pawn may promote to.
_PROMOTIONS = ("Q", "R", "B", "N")


class Board:
    """
    Represents a chessboard and its related operations.

    The `Board` class encapsulates the 8x8 grid of a chessboard and provides methods for a
    variety of essential chess operations. It handles initializing the board, querying individual
    squares, moving pieces, undoing moves, detecting special conditions (e.g., check, checkmate,
    and stalemate), and interacting with pieces on the board.

    :ivar board: An 8x8 grid (list of lists) where each element is a `Square` object that
        represents a square on the chessboard.
    :type board: list[list[Square]]
    :ivar two_moveP: Records the `Square` where a pawn moved two spaces forward during the
        most recent move, for "en passant" capture handling.
    :type two_moveP: Square or None
    :ivar status: The :class:`~chesssnake.engine.enums.GameStatus`
        (``IN_PLAY``/``WHITE_WON``/``BLACK_WON``/``DRAW``). Set inside :meth:`move`.
    :type status: GameStatus
    :ivar termination: Why a finished game ended
        (:class:`~chesssnake.engine.enums.Termination`), or ``None`` while in play.
    :type termination: Termination or None
    :ivar halfmove_clock: Plies since the last pawn move or capture (fifty-move rule).
    :type halfmove_clock: int
    :ivar fullmove_number: The move number (starts at 1, increments after Black).
    :type fullmove_number: int
    """

    def __init__(self, board=None, two_moveP=None):
        """
        Initializes the chessboard.

        If no board is provided, a default board is created with all pieces
        arranged in their standard chess starting positions.

        :param board: Optional pre-constructed 8x8 grid of `Square` objects. If not
            provided, a new chessboard is constructed in the standard starting layout.
        :type board: list[list[Square]] or None
        :param two_moveP: Optional `Square` where a pawn moved two spaces forward
            in the last move, used for handling "en passant" captures. Default is `None`.
        :type two_moveP: Square or None
        """
        if board is None:
            # creates board
            board = []

            # sets up back rank template with same index as j
            backrank = ["R", "N", "B", "Q", "K", "B", "N", "R"]

            # vertical
            for i in range(8):
                # adds new rank
                board.append([])

                # horizontal
                for j in range(8):
                    # black backrank
                    if i == 0:
                        if backrank[j] == "R":
                            piece = Rook(1)
                        elif backrank[j] == "N":
                            piece = Knight(1)
                        elif backrank[j] == "B":
                            piece = Bishop(1)
                        elif backrank[j] == "Q":
                            piece = Queen(1)
                        elif backrank[j] == "K":
                            piece = King(1)
                        else:
                            piece = None

                        board[i].append(Square(i, j, piece=piece))

                    # black pawns
                    elif i == 1:
                        board[i].append(Square(i, j, piece=Pawn(1)))

                    # white pawns
                    elif i == 6:
                        board[i].append(Square(i, j, piece=Pawn(0)))

                    # white backrank
                    elif i == 7:
                        if backrank[j] == "R":
                            piece = Rook(0)
                        elif backrank[j] == "N":
                            piece = Knight(0)
                        elif backrank[j] == "B":
                            piece = Bishop(0)
                        elif backrank[j] == "Q":
                            piece = Queen(0)
                        elif backrank[j] == "K":
                            piece = King(0)
                        else:
                            piece = None

                        board[i].append(Square(i, j, piece=piece))

                    # empty squares
                    else:
                        board[i].append(Square(i, j))

        self.board = board
        self.two_moveP = two_moveP
        self.status = GameStatus.IN_PLAY
        self.termination: Termination | None = None
        # FEN clocks: halfmove counts plies since the last pawn move or capture
        # (for the fifty-move rule); fullmove starts at 1 and increments after Black.
        self.halfmove_clock = 0
        self.fullmove_number = 1

    @contextmanager
    def lifted(self, square):
        """
        Context manager that temporarily removes the piece on ``square``.

        The piece is restored when the block exits (even on exception), making
        "remove piece, inspect board, put it back" analyses exception-safe.
        """
        piece = square.piece
        square.piece = None
        try:
            yield
        finally:
            square.piece = piece

    def __iter__(self):
        """
        Allows iteration over the board's rows.

        Each iteration yields one of the 8 rows (lists of `Square` objects) in the board.

        :return: Iterator over the rows of the board.
        :rtype: iter
        """
        return iter(self.board)

    def __getitem__(self, pos):
        """
        Retrieves a specific `Square` object on the chessboard based on its coordinates.

        :param pos: Tuple `(i, j)` representing the row and column of the square.
        :type pos: tuple[int, int]
        :return: The `Square` object located at the specified coordinates, or `None`
            if the coordinates are out of bounds.
        :rtype: Square or None
        """
        i, j = pos
        if (i > 7) or (i < 0) or (j > 7) or (j < 0):
            return None

        return self.board[i][j]

    # returns a string that can be printed for a nice looking text-based board
    def __str__(self):
        """
        Converts the board into a human-readable string format.

        Each square is represented by its piece symbol (if present) and color
        (e.g., 'P0' for a white pawn, 'K1' for a black king). Empty squares are
        represented as `--`.

        :return: A string representation of the chessboard.
        :rtype: str
        """
        out = ""

        for i in range(0, 8):
            out += str(8 - i) + "\t"
            for j in range(0, 8):
                if self[i, j].piece is not None:
                    out += self[i, j].piece.piecetype.value
                    out += str(int(self[i, j].piece.color))
                    out += " "
                else:
                    out += "-- "
            out += "\n"
        out += "\n\ta  b  c  d  e  f  g  h\n"

        return out

    def move(self, move, player):
        """
        Executes a move on the chessboard.

        Updates the game state (`status`) in the event of checkmate or stalemate.

        Raises an exception if the move is invalid.

        :param move: The move object representing the player's action.
        :type move: Move
        :param player: The current player's color (0 for white, 1 for black).
        :type player: int
        :return: The executed move object for reference.
        :rtype: Move
        :raises errors.MoveIntoCheckError: If the move would put the player in check.
        :raises errors.PromotionError: If an invalid promotion is attempted or a promotion is required.
        :raises errors.InvalidCastleError: If an invalid castling move is attempted.
        :raises errors.PieceNotFoundError: If no eligible piece is found for the move.
        :raises errors.MultiplePiecesFoundError: If more than one matching piece is found.
        :raises errors.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises errors.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises errors.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        player = Color(player)
        prev_two_moveP = self.two_moveP

        # makes the move object
        m = Move(move, player, self)

        # if en passant, delete the old piece
        if m.en:
            x = 1 if player == Color.WHITE else -1
            self[m.to.i + x, m.to.j].piece = None

        # moving the rook for castling
        if m.castle is not None:
            x = 7 if player == Color.WHITE else 0
            j1 = 7 if m.castle == "K" else 0
            j2 = 5 if m.castle == "K" else 3
            self[x, j1].piece = None
            self[x, j2].piece = Rook(player, moved=True)

        # pawn promotions
        new_piece = m.piece
        if m.promotion is not None:
            if m.promotion == "Q":
                new_piece = Queen(player)
            elif m.promotion == "R":
                new_piece = Rook(player)
            elif m.promotion == "B":
                new_piece = Bishop(player)
            elif m.promotion == "N":
                new_piece = Knight(player)

        # detect a capture (for the halfmove clock) before the target is overwritten
        is_capture = self[m.to.i, m.to.j].piece is not None or m.en
        is_pawn_move = m.piece.piecetype == PieceType.PAWN

        # sets the board correctly
        self[m.prev.i, m.prev.j].piece = None
        self[m.to.i, m.to.j].piece = new_piece

        # if the player is moving into check, we undo the move and raise an error
        if self.check_for_check(player):
            self.undo_move(m, player, prev_two_moveP)
            raise errors.MoveIntoCheckError

        # if no pawns where moved two squares, the board remembers
        if prev_two_moveP is not None and self.two_moveP == prev_two_moveP:
            self.two_moveP = None

        # if the piece is a rook or a king, sets moved to True
        if new_piece.piecetype in (PieceType.KING, PieceType.ROOK):
            new_piece.moved = True

        # FEN clocks
        self.halfmove_clock = 0 if (is_pawn_move or is_capture) else self.halfmove_clock + 1
        if player == Color.BLACK:
            self.fullmove_number += 1

        # update the game outcome from the rules the board can see by itself
        # (threefold repetition is applied by Game.move, which holds the history)
        opponent = player.opponent
        if self.check_for_mate(opponent):
            self.status = GameStatus.won_by(player)
            self.termination = Termination.CHECKMATE
        elif not self.check_for_check(opponent) and self.check_for_stalemate(opponent):
            self.status = GameStatus.DRAW
            self.termination = Termination.STALEMATE
        elif self.insufficient_material():
            self.status = GameStatus.DRAW
            self.termination = Termination.INSUFFICIENT_MATERIAL
        elif self.halfmove_clock >= 100:
            self.status = GameStatus.DRAW
            self.termination = Termination.FIFTY_MOVE

        return m

    def insufficient_material(self):
        """
        Whether neither side has enough material to force checkmate.

        Covers the standard dead positions: K vs K, K vs K + a single minor, and
        K+B vs K+B with both bishops on same-colored squares. Any pawn, rook, or
        queen means mate is still possible.

        :rtype: bool
        """
        minors = 0
        bishop_square_colors = []
        for rank in self:
            for square in rank:
                piece = square.piece
                if piece is None or piece.piecetype == PieceType.KING:
                    continue
                if piece.piecetype in (PieceType.PAWN, PieceType.ROOK, PieceType.QUEEN):
                    return False
                minors += 1
                if piece.piecetype == PieceType.BISHOP:
                    bishop_square_colors.append(square.color)

        if minors <= 1:
            return True
        # K+B vs K+B (or same-side bishops) all on one square color can't mate
        return minors == len(bishop_square_colors) and len(set(bishop_square_colors)) == 1

    def undo_move(self, move, player, prev_two_moveP):
        """
        Reverses a previously executed move on the chessboard.

        Essentially restores the board's state to what it was before a move,
        including restoring captured pieces and undoing special moves
        (e.g., castling and "en passant").

        :param move: The move object to undo.
        :type move: Move
        :param player: The player's color (0 for white, 1 for black).
        :type player: int
        :param prev_two_moveP: The `Square` that stored the two-move pawn state
            prior to the move. Used to restore the en passant state.
        :type prev_two_moveP: Square or None
        """
        # changes self.two_moveP back to what it was before
        player = Color(player)
        self.two_moveP = prev_two_moveP

        # if en passant, places back the old piece
        if move.en:
            x = 1 if player == Color.WHITE else -1
            self[move.to.i + x, move.to.j].piece = Pawn(player.opponent)

        # moving the rook for castling
        if move.castle is not None:
            x = 7 if player == Color.WHITE else 0
            j1 = 7 if move.castle == "K" else 0
            j2 = 5 if move.castle == "K" else 3
            self[x, j1].piece = Rook(player, moved=False)
            self[x, j2].piece = None

        # sets the board correctly
        self[move.prev.i, move.prev.j].piece = move.piece
        self[move.to.i, move.to.j].piece = None

    # returns the first square found containing the king of the specified color
    def find_king(self, color):
        """
        Finds the `Square` containing the King of the specified color.

        Searches the board to locate the King for a given player.

        :param color: The color of the King to locate (0 for white, 1 for black).
        :type color: int
        :return: The `Square` where the King is located, or `None` if the King
            could not be found.
        :rtype: Square or None
        """
        color = Color(color)
        for x in range(8):
            # if color is white, search from bottom up
            # if color is black, search from top down
            i = 7 - x if color == Color.WHITE else x

            # search from right to left (it is common to kingside castle, which is towards the right)
            for j in range(7, -1, -1):
                if (
                    self[i, j].piece is not None
                    and self[i, j].piece.piecetype == PieceType.KING
                    and self[i, j].piece.color == color
                ):
                    return self[i, j]

        return None

    # returns a list of squares that have pieces that are threatening the given square for the given player
    def threats_on(self, square, player):
        """
        Determines all opposing pieces currently threatening a given square.

        A piece is considered "threatening" if it can legally capture the square (does not account for pinning).

        :param square: The target square to analyze.
        :type square: Square
        :param player: The player being threatened (0 for white, 1 for black).
        :type player: int
        :return: A list of squares that contain pieces threatening the specified square.
        :rtype: list[Square]
        """
        opponent = Color(player).opponent

        threats = []
        threats.extend(Pawn.find_all(self, square, opponent, capture=True))
        threats.extend(Rook.find_all(self, square, opponent))
        threats.extend(Knight.find_all(self, square, opponent))
        threats.extend(Bishop.find_all(self, square, opponent))
        threats.extend(Queen.find_all(self, square, opponent))
        threats.extend(King.find_all(self, square, opponent))
        return threats

    # returns true if given player is in check
    # returns false otherwise
    def check_for_check(self, player):
        """
        Determines if the player's King is currently in check.

        A King is in check if one or more opposing pieces are threatening its square.

        :param player: The player to check (0 for white, 1 for black).
        :type player: int
        :return: `True` if the player's King is in check, otherwise `False`.
        :rtype: bool
        """
        king_square = self.find_king(player)
        if king_square is None:
            return False

        return len(self.threats_on(king_square, player)) > 0

    def _squares_between(self, a, b):
        """
        Squares strictly between two colinear squares ``a`` and ``b`` (exclusive).

        Works for a shared rank, file, or diagonal — the only lines along which a
        sliding piece can check a king. Returns an empty list when the squares are
        adjacent (nothing can be interposed).

        :param a: One endpoint square (e.g. the king's square).
        :type a: Square
        :param b: The other endpoint square (e.g. the checking piece's square).
        :type b: Square
        :return: The list of `Square` objects strictly between ``a`` and ``b``.
        :rtype: list[Square]
        """
        di = b.i - a.i
        dj = b.j - a.j
        steps = max(abs(di), abs(dj))
        step_i = (di > 0) - (di < 0)  # sign of di (-1, 0, or 1)
        step_j = (dj > 0) - (dj < 0)  # sign of dj (-1, 0, or 1)
        return [self[a.i + s * step_i, a.j + s * step_j] for s in range(1, steps)]

    # returns true if the given player is in checkmate
    # returns false otherwise
    def check_for_mate(self, player):
        """
        Determines if the player is in checkmate.

        A player is in checkmate if the King is in check and no legal moves can
        remove it from check.

        :param player: The player to check for checkmate (0 for white, 1 for black).
        :type player: int
        :return: `True` if the player's King is in checkmate, otherwise `False`.
        :rtype: bool
        """
        player = Color(player)
        if not self.check_for_check(player):
            return False

        king_square = self.find_king(player)
        if king_square is None:
            return False

        threats = self.threats_on(king_square, player)

        # checks if the king can move.
        # The king is temporarily lifted off the board so it does not block a
        # sliding attacker's line of sight to the square behind it (otherwise an
        # escape square "behind" the king along the checking line, e.g. a back-rank
        # Kg8->h8, would incorrectly look safe).
        delta_is = [1, 1, 0, -1, -1, -1, 0, 1]
        delta_js = [0, 1, 1, 1, 0, -1, -1, -1]
        with self.lifted(king_square):
            for index in range(8):
                psquare = self[king_square.i + delta_is[index], king_square.j + delta_js[index]]

                # if there is a square that the king can move to, returns false
                if (
                    psquare is not None
                    and (psquare.piece is None or psquare.piece.color == player.opponent)
                    and len(self.threats_on(psquare, player)) == 0
                ):
                    return False

        # checks if the piece threatening can be taken OR if the piece threatening can be blocked
        if len(threats) == 1:  # this will only work if there is only one threatening piece
            # this is the only threat, now saved to threat
            threat = threats[0]

            # if the piece can be taken, returns False
            if len(self.threats_on(threat, player.opponent)) > 0:
                return False

            # blocking
            if threat.piece.piecetype in (PieceType.ROOK, PieceType.BISHOP, PieceType.QUEEN):
                # the squares between the (sliding) checker and the king — any of
                # which a friendly piece could interpose on to block the check
                pbsquares = self._squares_between(king_square, threat)

                # if any of the possible blocking squares (pbsquares) are blockable, returns false
                for pbsquare in pbsquares:
                    # a friendly pawn can block the threat by advancing (a non-capture move)
                    if Pawn.find_all(self, pbsquare, player, capture=False):
                        return False

                    # this is a list of pieces that threaten the possible blocking squares
                    # possible blocking threats (pbthreats)
                    pbthreats = self.threats_on(pbsquare, player.opponent)
                    if len(pbthreats) != 0:
                        # kings and pawns need to be excluded from this list:
                        #   - kings can't block a check
                        #   - pawns can't block a check by capturing
                        for square in pbthreats:
                            if square.piece.piecetype not in (PieceType.PAWN, PieceType.KING):
                                return False

        return True

    # returns true if the given player is in stalemate (can't move any of their pieces)
    # returns false otherwise
    def check_for_stalemate(self, player):
        """
        Determines if the player is in stalemate.

        A player is in stalemate if they are not in check and have no legal moves remaining.

        :param player: The player to check for stalemate (0 for white, 1 for black).
        :type player: int
        :return: `True` if the player is in stalemate, otherwise `False`.
        :rtype: bool
        """
        player = Color(player)
        for rank in self:
            for square in rank:
                if square.piece is not None and square.piece.color == player and square.piece.can_move(square, self):
                    return False

        return True

    def _pseudo_targets(self, square, piece):
        """Candidate destination squares for ``piece`` (a superset of legal moves)."""
        targets = list(piece.threatens(square, self))
        if piece.piecetype == PieceType.PAWN:
            # threatens() only covers diagonal attacks; add the forward pushes.
            forward = -1 if piece.color == Color.WHITE else 1
            for step in (1, 2):
                ahead = self[square.i + forward * step, square.j]
                if ahead is not None:
                    targets.append(ahead)
        return targets

    def legal_moves(self, turn):
        """
        Enumerate every fully-legal move for ``turn`` in the current position.

        Each entry is ``{"from", "to", "san", "promotion"}`` where ``san`` is a move
        string that can be handed straight back to :meth:`move` / the moves endpoint.
        Candidates are generated pseudo-legally and then confirmed by actually
        applying them to a throwaway copy (so castling, en passant, promotion, and
        self-check are all validated by the real move logic).

        :param turn: the side to move (0 white / 1 black).
        :rtype: list[dict]
        """
        turn = Color(turn)
        moves = []

        def _accept(san):
            trial = copy.deepcopy(self)
            try:
                trial.move(san, turn)
            except errors.ChessError:
                return False
            return True

        for rank in self:
            for square in rank:
                piece = square.piece
                if piece is None or piece.color != turn:
                    continue
                last_rank = 0 if turn == Color.WHITE else 7
                for to in self._pseudo_targets(square, piece):
                    promotions = _PROMOTIONS if (piece.piecetype == PieceType.PAWN and to.i == last_rank) else (None,)
                    for promo in promotions:
                        san = to_san(self, square, to, piece, promotion=promo)
                        if _accept(san):
                            moves.append(
                                {"from": square.c_notation, "to": to.c_notation, "san": san, "promotion": promo}
                            )

        # castling is generated from the king, not from target squares
        king_square = self.find_king(turn)
        if king_square is not None:
            for san in ("0-0", "0-0-0"):
                if _accept(san):
                    moves.append({"from": king_square.c_notation, "to": None, "san": san, "promotion": None})

        return moves

    # coord<->notation helpers live in notation.py; kept here as facades
    get_coords = staticmethod(notation.get_coords)
    get_c_notation = staticmethod(notation.get_c_notation)
