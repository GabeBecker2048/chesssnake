"""The `Board`: the 8x8 grid plus move/undo and check/mate detection."""

from contextlib import contextmanager

from . import errors, notation
from .enums import Color, GameStatus, PieceType
from .move import Move
from .pieces import Bishop, King, Knight, Pawn, Queen, Rook
from .square import Square


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
    :ivar status: Tracks the current game state:
        - 0: Game is in progress.
        - 1: Checkmate has occurred, and the game is over.
        - 2: Stalemate has occurred, and the game is over.
    :type status: int
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
            backrank = ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']

            # vertical
            for i in range(8):

                # adds new rank
                board.append([])

                # horizontal
                for j in range(8):

                    # black backrank
                    if i == 0:

                        if backrank[j] == 'R':
                            piece = Rook(1)
                        elif backrank[j] == 'N':
                            piece = Knight(1)
                        elif backrank[j] == 'B':
                            piece = Bishop(1)
                        elif backrank[j] == 'Q':
                            piece = Queen(1)
                        elif backrank[j] == 'K':
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

                        if backrank[j] == 'R':
                            piece = Rook(0)
                        elif backrank[j] == 'N':
                            piece = Knight(0)
                        elif backrank[j] == 'B':
                            piece = Bishop(0)
                        elif backrank[j] == 'Q':
                            piece = Queen(0)
                        elif backrank[j] == 'K':
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
            out += str(8-i) + "\t"
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
            j1 = 7 if m.castle == 'K' else 0
            j2 = 5 if m.castle == 'K' else 3
            self[x, j1].piece = None
            self[x, j2].piece = Rook(player, moved=True)

        # pawn promotions
        new_piece = m.piece
        if m.promotion is not None:
            if m.promotion == 'Q':
                new_piece = Queen(player)
            elif m.promotion == 'R':
                new_piece = Rook(player)
            elif m.promotion == 'B':
                new_piece = Bishop(player)
            elif m.promotion == 'N':
                new_piece = Knight(player)

        # sets the board correctly
        self[m.prev.i, m.prev.j].piece = None
        self[m.to.i, m.to.j].piece = new_piece

        # if the player is moving into check, we undo the move and raise an error
        if self.check_for_check(player):
            self.undo_move(m, player, prev_two_moveP)
            raise errors.MoveIntoCheckError

        # changes the game status if a mate or stalemate is detected
        if self.check_for_mate(player.opponent):
            self.status = GameStatus.CHECKMATE
        elif not self.check_for_check(player.opponent) and self.check_for_stalemate(player.opponent):
            self.status = GameStatus.DRAW

        # if no pawns where moved two squares, the board remembers
        if prev_two_moveP is not None and self.two_moveP == prev_two_moveP:
            self.two_moveP = None

        # if the piece is a rook or a king, sets moved to True
        if new_piece.piecetype in (PieceType.KING, PieceType.ROOK):
            new_piece.moved = True

        return m

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
            j1 = 7 if move.castle == 'K' else 0
            j2 = 5 if move.castle == 'K' else 3
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

    # coord<->notation helpers live in notation.py; kept here as facades
    get_coords = staticmethod(notation.get_coords)
    get_c_notation = staticmethod(notation.get_c_notation)

    # takes in a board that is stored in string form and converts it into array form
    # the opposite of Board.disassemble_board
    @staticmethod
    def assemble_board(boardstring, moved):
        """
        Converts a board string representation back into a 2D array of `Square` objects.

        Used for reconstructing a board's state from its serialized form.

        `moved` is a 6 character string of zeros and ones that indicates which Rook or Kings have moved.
        0 means unmoved, 1 means moved.
        - The first character indicates whether the white Rook starting on A1 has moved
        - The second character indicates whether the white King has moved
        - The third character indicates whether the white Rook starting on H1 has moved
        - The fourth character indicates whether the black Rook starting on A8 has moved
        - The fifth character indicates whether the black King has moved
        - The sixth character indicates whether the black Rook starting on H8 has moved

        :param boardstring: Serialized string representation of the board.
        :type boardstring: str
        :param moved: String indicating whether certain pieces (e.g., Rooks, Kings)
            have moved, for rules like castling.
        :type moved: str
        :return: A reconstructed board as a 2D list of `Square` objects.
        :rtype: list[list[Square]]
        """
        # splits the string into a 2D array of strings
        boardstringarray = boardstring.split(";")
        for i in range(len(boardstringarray)):
            boardstringarray[i] = boardstringarray[i].split()

        # creates the array
        board = []
        for i in range(8):
            board.append([])
            for j in range(8):

                # creates the piece
                if boardstringarray[i][j][0] == "R":
                    if (
                        (i == 7 and j == 0 and moved[0] == '1') or
                        (i == 7 and j == 7 and moved[2] == '1') or
                        (i == 0 and j == 0 and moved[0] == '1') or
                        (i == 0 and j == 7 and moved[2] == '1')
                    ):
                        piece = Rook(boardstringarray[i][j][1], True)
                    else:
                        piece = Rook(boardstringarray[i][j][1], False)
                elif boardstringarray[i][j][0] == "N":
                    piece = Knight(boardstringarray[i][j][1])
                elif boardstringarray[i][j][0] == "B":
                    piece = Bishop(boardstringarray[i][j][1])
                elif boardstringarray[i][j][0] == "Q":
                    piece = Queen(boardstringarray[i][j][1])
                elif boardstringarray[i][j][0] == "K":
                    if (
                        (i == 7 and j == 4 and moved[1] == '1') or
                        (i == 0 and j == 4 and moved[1] == '1')
                    ):
                        piece = King(boardstringarray[i][j][1], True)
                    else:
                        piece = King(boardstringarray[i][j][1], False)
                elif boardstringarray[i][j][0] == "P":
                    piece = Pawn(boardstringarray[i][j][1])
                else:
                    piece = None

                # adds the square
                board[i].append(Square(i, j, piece=piece))

        return board

    # takes in a board that is stored in array form and converts it into string form
    # the opposite of Board.assemble_board
    @staticmethod
    def disassemble_board(board):
        """
        Serializes the board into a string representation.

        Used to store the board's state compactly in string form.

        Returns two strings:
        - The first string is the serialized board state
        - The second string is a string of zeros and ones that indicates which Rook or Kings have moved

        The `moved` string is a 6 character string of zeros and ones that indicates which Rook or Kings have moved.
        0 means unmoved, 1 means moved.
        - The first character indicates whether the white Rook starting on A1 has moved
        - The second character indicates whether the white King has moved
        - The third character indicates whether the white Rook starting on H1 has moved
        - The fourth character indicates whether the black Rook starting on A8 has moved
        - The fifth character indicates whether the black King has moved
        - The sixth character indicates whether the black Rook starting on H8 has moved

        :param board: The board object that we are disassembling
        :type board: Board
        :return: A tuple containing the serialized board string and a string
            indicating move states for certain pieces.
        :rtype: tuple[str, str]
        """
        boardstring = ""
        moved = ['0', '0', '0', '0', '0', '0']
        for rank in board:
            for square in rank:
                if square.piece is not None:
                    boardstring += square.piece.piecetype.value + str(int(square.piece.color)) + " "

                    if (square.i == 7 and square.j == 0) and square.piece.piecetype == PieceType.ROOK and square.piece.moved:
                        moved[0] = "1"
                    elif (square.i == 7 and square.j == 4) and square.piece.piecetype == PieceType.KING and square.piece.moved:
                        moved[1] = "1"
                    elif (square.i == 7 and square.j == 7) and square.piece.piecetype == PieceType.ROOK and square.piece.moved:
                        moved[2] = "1"
                    elif (square.i == 0 and square.j == 0) and square.piece.piecetype == PieceType.ROOK and square.piece.moved:
                        moved[3] = "1"
                    elif (square.i == 0 and square.j == 4) and square.piece.piecetype == PieceType.KING and square.piece.moved:
                        moved[4] = "1"
                    elif (square.i == 0 and square.j == 7) and square.piece.piecetype == PieceType.ROOK and square.piece.moved:
                        moved[5] = "1"

                else:
                    boardstring += "-- "

            boardstring = boardstring[:-1]
            boardstring += ";"
        boardstring = boardstring[:-1]
        moved = "".join(moved)

        return boardstring, moved
