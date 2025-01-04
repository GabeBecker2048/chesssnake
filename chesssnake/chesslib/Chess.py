from . import ChessError


class Piece:
    """
    Base class representing a chess piece.

    This class provides basic functionality and attributes common to all chess pieces,
    such as type and color. It also contains methods for identifying a piece's full
    name and determining if it is pinned on the board.

    :ivar piecetype: The type of the chess piece represented by a single character
                     ('K', 'Q', 'R', 'B', 'P', or 'N').
    :type piecetype: str
    :ivar color: The color of the piece, where 0 represents white and 1 represents black.
    :type color: int
    """
    def __init__(self, piecetype, color):
        """
        Initializes a generic chess piece.

        :param piecetype: A single character representing the piece type ('K', 'Q', 'R', 'B', 'P', or 'N').
        :type piecetype: str
        :param color: The color of the piece, where 0 represents white and 1 represents black.
        :type color: int
        """

        self.piecetype = str(piecetype)
        self.color = int(color)

    def fullname(self):
        """
        Returns the full name of the chess piece.

        :return: The name of the piece (e.g., "king", "queen", "pawn").
        :rtype: str
        """
        if self.piecetype == 'P':
            return "pawn"
        elif self.piecetype == 'R':
            return "rook"
        elif self.piecetype == 'N':
            return "knight"
        elif self.piecetype == 'B':
            return "bishop"
        elif self.piecetype == 'Q':
            return "queen"
        elif self.piecetype == 'K':
            return "king"
        else:
            return "unknown"

    # dev note:
    # if the king is already in check, then this will *always* return true
    # only use this function if we know the king is not in check already
    def is_pinned(self, square, board):
        """
        Determines if the piece is pinned to the king.

        A piece is considered pinned if removing it from its current location exposes
        the king to a direct attack (check). Kings themselves are never pinned.

        :param square: The square the piece is currently on.
        :type square: Square
        :param board: The current state of the board, which tracks all pieces and their positions.
        :type board: Board
        :return: True if the piece is pinned, else False.
        :rtype: bool
        """

        if self.piecetype == 'K':
            return False

        # removes the piece from the board
        board[square.i, square.j].piece = None

        # if the player is in check without the piece there, then the piece is pinned
        pinned = True if board.check_for_check(self.color) else False

        # returns piece to board
        board[square.i, square.j].piece = self

        return pinned


class Rook(Piece):
    """
    Represents a Rook chess piece.

    A subclass of the `Piece` class. The Rook chess piece moves in straight lines along rows or columns and attacks
    in the same manner. This class implements the movement, threatening behavior, and special movement restrictions
    of a rook in chess.

    :ivar piecetype: The type of the piece, which is 'R' for Rook.
    :type piecetype: str
    :ivar color: The color of the piece, where 0 represents white and 1 represents black.
    :type color: int
    :ivar moved: Represents whether the piece has moved. Used for determining if a player can castle
    :type moved: bool
    """
    def __init__(self, color, moved=False):
        """
        Initializes a Rook chess piece.

        The rook is initialized with a color, and whether it has moved.
        The `color` is used to identify if the piece belongs to the white
        or black side, and the `moved` attribute helps determine if this rook can still
        participate in castling.

        :param color: The color of the rook (0 for white, 1 for black).
        :type color: int
        :param moved: Indicates whether the rook has moved. Defaults to `False`.
        :type moved: bool
        """
        super().__init__('R', color)

        self.moved = moved

    def threatens(self, square, board):
        """
        Determines the squares that this Rook can attack, regardless of pinning.

        This method calculates all reachable squares in any cardinal direction (up,
        down, left, right). The search includes squares blocked by other pieces, stopping
        at the first encountered piece. Opponent pieces are included in the threatened
        squares, but friendly pieces block further checks in that direction.

        :param square: The square where this rook is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: A list of squares that the rook can threaten.
        :rtype: list[Square]
        """
        moves = []
        i_pos, j_pos, i_neg, j_neg = True, True, True, True

        x = 0
        while i_pos or i_neg or j_pos or j_neg:
            x += 1

            # search in positive i direction
            if i_pos:
                i_pos_square = board[square.i + x, square.j]

                if i_pos_square is None:
                    i_pos = False

                elif i_pos_square.piece is not None:
                    i_pos = False

                    if i_pos_square.piece.color != self.color:
                        moves.append(i_pos_square)

                else:
                    moves.append(i_pos_square)

            # search in positive j direction
            if j_pos:
                j_pos_square = board[square.i, square.j + x]

                if j_pos_square is None:
                    j_pos = False

                elif j_pos_square.piece is not None:
                    j_pos = False

                    if j_pos_square.piece.color != self.color:
                        moves.append(j_pos_square)

                else:
                    moves.append(j_pos_square)

            # search in negative i direction
            if i_neg:
                i_neg_square = board[square.i - x, square.j]

                if i_neg_square is None:
                    i_neg = False

                elif i_neg_square.piece is not None:
                    i_neg = False

                    if i_neg_square.piece.color != self.color:
                        moves.append(i_neg_square)

                else:
                    moves.append(i_neg_square)

            # search in negative j direction
            if j_neg:
                j_neg_square = board[square.i, square.j - x]

                if j_neg_square is None:
                    j_neg = False

                elif j_neg_square.piece is not None:
                    j_neg = False

                    if j_neg_square.piece.color != self.color:
                        moves.append(j_neg_square)

                else:
                    moves.append(j_neg_square)

        return moves

    def can_move(self, square, board):
        """
        Determines if this Rook has at least one valid move.

        A rook is considered able to move if:
        - It is not pinned to its king (i.e., its move wouldn't expose the king to check).
        - It threatens an opponent's squares or empty squares.

        If pinned, the rook is further analyzed to determine if it can legally capture
        threatening pieces.

        :param square: The square where this rook is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: `True` if the rook has at least one legal move, otherwise `False`.
        :rtype: bool
        """
        # if the piece is pinned, we need to check if the piece can capture the other piece that is pinning it
        if self.is_pinned(square, board):

            # gets the list of threats to the king
            king_threats1 = board.threats_on(board.find_king(self.color), self.color)

            # removes the piece from board
            board[square.i, square.j].piece = None

            # gets the list of threats to the king again
            king_threats2 = board.threats_on(board.find_king(self.color), self.color)

            # gets the threats that are not in both lists, ie the threat that the piece should be blocking
            king_threats = [threat for threat in king_threats1 + king_threats2
                            if threat not in king_threats1 or threat not in king_threats2]

            # puts the piece back
            board[square.i, square.j].piece = self

            # if there is more than one threat the king, the piece is pinned and can't move
            if len(king_threats) != 1:
                return False

            # if the threat can be taken by the pinned piece, the piece can move
            if king_threats[0] in self.threatens(square, board):
                return True

            # the piece is pinned and can't move
            return False

        # if the piece is not pinned and threatens anything, then it can move
        if len(self.threatens(square, board)) != 0:
            return True

        return False

    @staticmethod
    def find(board, square, color, capture, file_limit=None, rank_limit=None, errors=True):
        """
        Finds the Rook that corresponds to a given move.

        Chess moves provide limited information to locate a specific piece, such as its
        type (Rook), the target square, and optional file or rank constraints. This method
        performs a targeted search to find valid rooks that match the move's description.

        If the `errors` flag is set to `True`, this method validates the legality of the
        identified Rook(s) for the move. If a valid Rook cannot be determined, or if
        multiple matching Rooks are found, it raises appropriate exceptions.

        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :param square: The square where the rook is attempting to move.
        :type square: Square
        :param color: The color of the rook being searched for (0 for white, 1 for black).
        :type color: int
        :param capture: Indicates whether the move involves capturing an opponent's piece.
        :type capture: bool
        :param file_limit: (Optional) Restricts to find rooks in a specific file (e.g., 'a', 'b', etc.).
        :type file_limit: str or None
        :param rank_limit: (Optional) Restricts to find rooks in a specific rank (e.g., '1', '2', etc.).
        :type rank_limit: str or None
        :param errors: If `True`, raises exceptions for invalid moves or ambiguities.
                       If `False`, returns `None` for invalid moves instead.
        :type errors: bool
        :return: The rook that can execute the move, or a list if multiples are found, or `None` when `errors=False`.
        :rtype: Rook or list[Rook] or None
        :raises ChessError.PieceNotFoundError: If no eligible rook is found for the move.
        :raises ChessError.MultiplePiecesFoundError: If more than one matching rook is found.
        :raises ChessError.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises ChessError.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises ChessError.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        found = []
        i_pos, j_pos, i_neg, j_neg = True, True, True, True

        x = 0
        while i_pos or i_neg or j_pos or j_neg:
            x += 1

            # search in positive i direction
            if i_pos:
                i_pos_square = board[square.i + x, square.j]

                if i_pos_square is None:
                    i_pos = False

                elif i_pos_square.piece is not None:
                    i_pos = False

                    if i_pos_square.piece.piecetype == 'R' and i_pos_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][i_pos_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - i_pos_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][i_pos_square.j]
                                    and rank_limit == str(8 - i_pos_square.i))
                        ):
                            found.append(i_pos_square)

            # search in positive j direction
            if j_pos:
                j_pos_square = board[square.i, square.j + x]

                if j_pos_square is None:
                    j_pos = False

                elif j_pos_square.piece is not None:
                    j_pos = False

                    if j_pos_square.piece.piecetype == 'R' and j_pos_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j_pos_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - j_pos_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j_pos_square.j]
                                    and rank_limit == str(8 - j_pos_square.i))
                        ):
                            found.append(j_pos_square)

            # search in negative i direction
            if i_neg:
                i_neg_square = board[square.i - x, square.j]

                if i_neg_square is None:
                    i_neg = False

                elif i_neg_square.piece is not None:
                    i_neg = False

                    if i_neg_square.piece.piecetype == 'R' and i_neg_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][i_neg_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - i_neg_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][i_neg_square.j]
                                    and rank_limit == str(8 - i_neg_square.i))
                        ):
                            found.append(i_neg_square)

            # search in negative j direction
            if j_neg:
                j_neg_square = board[square.i, square.j - x]

                if j_neg_square is None:
                    j_neg = False

                elif j_neg_square.piece is not None:
                    j_neg = False

                    if j_neg_square.piece.piecetype == 'R' and j_neg_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j_neg_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - j_neg_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j_neg_square.j]
                                    and rank_limit == str(8 - j_neg_square.i))
                        ):
                            found.append(j_neg_square)

        if len(found) == 0:
            if errors:
                raise ChessError.PieceNotFoundError(square, 'R')
            else:
                return None

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise ChessError.NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise ChessError.CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise ChessError.PieceOnSquareError(square, True)
                    else:
                        raise ChessError.PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise ChessError.MultiplePiecesFoundError(square, found)
            else:
                return found


class Knight(Piece):
    """
    Represents a Knight chess piece.

    A subclass of the `Piece` class. The Knight is a unique chess piece that moves in an "L" shape:
    two squares in one direction and one square perpendicular to it, or vice versa. Knights are
    the only pieces that can "jump" over other pieces while moving. This class implements the movement,
    threatening behavior, and related functionality of a Knight in chess.

    :ivar piecetype: The type of the piece, which is 'N' for Knight. 'K' is used by King.
    :type piecetype: str
    :ivar color: The color of the piece, where 0 represents white and 1 represents black.
    :type color: int
    """
    def __init__(self, color):
        """
        Initializes a Knight chess piece.

        The Knight is initialized with attributes for its type ('B') and for its color. The `color` is used
        to identify if the piece belongs to the white or black side.

        :param color: The color of the knight (0 for white, 1 for black).
        :type color: int
        """
        super().__init__('N', color)

    def threatens(self, square, board):
        """
        Determines the squares that this Knight can attack, regardless of pinning.

        The Knight moves in an "L" shape: two squares in one direction and one square
        perpendicular to that or vice versa. This method calculates all valid squares
        the Knight can threaten, considering that it can jump over other pieces. The
        threatened squares are valid even if they are occupied, as long as they belong
        to an opposing piece.

        :param square: The square where this knight is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: A list of squares that the Knight can threaten.
        :rtype: list[Square]
        """
        moves = []
        delta_is = [2, 1, -1, -2, -2, -1, 1, 2]
        delta_js = [1, 2, 2, 1, -1, -2, -2, -1]

        for index in range(8):

            psquare = board[square.i + delta_is[index], square.j + delta_js[index]]

            # The square must exist
            # If there is a piece on the square, it must be a different color than the current piece
            if (
                    psquare is not None
                    and ((psquare.piece is not None and psquare.piece.color != self.color)
                         or psquare.piece is None)
            ):
                moves.append(psquare)

        return moves

    def can_move(self, square, board):
        """
        Determines if this Knight has at least one valid move.

        A Knight is considered able to move if:
        - It is not pinned to its king (i.e., its move wouldn't expose the king to check).
        - It threatens an opponent's squares or empty squares.

        If pinned, the Knight is restricted and cannot move.

        :param square: The square where this knight is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: `True` if the Knight has at least one legal move, otherwise `False`.
        :rtype: bool
        """
        # if a knight is pinned, it can't move
        if self.is_pinned(square, board):
            return False

        # if the piece is not pinned and threatens anything, then it can move
        if len(self.threatens(square, board)) != 0:
            return True

        return False

    @staticmethod
    def find(board, square, color, capture, file_limit=None, rank_limit=None, errors=True):
        """
        Finds the Knight that corresponds to a given move.

        Chess moves provide limited information to locate a specific piece, such as its
        type (Knight), the target square, and optional file or rank constraints. This
        method performs a targeted search to find valid Knights that match the move's description.

        If the `errors` flag is set to `True`, this method validates the legality of the
        identified Knight(s) for the move. If a valid Knight cannot be determined, or if
        multiple matching Knights are found, it raises appropriate exceptions.

        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :param square: The square where the Knight is attempting to move.
        :type square: Square
        :param color: The color of the Knight being searched for (0 for white, 1 for black).
        :type color: int
        :param capture: Indicates whether the move involves capturing an opponent's piece.
        :type capture: bool
        :param file_limit: (Optional) Restricts to find Knights in a specific file (e.g., 'a', 'b', etc.).
        :type file_limit: str or None
        :param rank_limit: (Optional) Restricts to find Knights in a specific rank (e.g., '1', '2', etc.).
        :type rank_limit: str or None
        :param errors: If `True`, raises exceptions for invalid moves or ambiguities.
                       If `False`, returns `None` for invalid moves instead.
        :type errors: bool
        :return: The Knight that can execute the move, or a list if multiples are found, or `None` when `errors=False`.
        :rtype: Knight or list[Knight] or None
        :raises ChessError.PieceNotFoundError: If no eligible Knight is found for the move.
        :raises ChessError.MultiplePiecesFoundError: If more than one matching Knight is found.
        :raises ChessError.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises ChessError.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises ChessError.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        found = []
        delta_is = [2, 1, -1, -2, -2, -1, 1, 2]
        delta_js = [1, 2, 2, 1, -1, -2, -2, -1]

        for index in range(8):

            psquare = board[square.i + delta_is[index], square.j + delta_js[index]]

            # The square must exist
            # If there is a piece on the square, it must be the same color as the player
            if (
                    psquare is not None
                    and psquare.piece is not None
                    and psquare.piece.piecetype == 'N'
                    and psquare.piece.color == color
            ):
                # this checks for rank and file limits
                if (
                        (rank_limit is None and file_limit is None)
                        or (file_limit is not None and rank_limit is None
                            and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][psquare.j])
                        or (rank_limit is not None and file_limit is None
                            and rank_limit == str(8 - psquare.i))
                        or (rank_limit is not None and file_limit is not None
                            and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][psquare.j]
                            and rank_limit == str(8 - psquare.i))
                ):
                    found.append(psquare)

        if len(found) == 0:
            if errors:
                raise ChessError.PieceNotFoundError(square, 'N')
            else:
                return None

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise ChessError.NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise ChessError.CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise ChessError.PieceOnSquareError(square, True)
                    else:
                        raise ChessError.PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise ChessError.MultiplePiecesFoundError(square, found)
            else:
                return found


class Bishop(Piece):
    """
    Represents a Bishop chess piece.

    A subclass of the `Piece` class. The Bishop is a chess piece that moves diagonally across
    the board any number of squares, as long as there are no obstacles in its path. Bishops are
    limited to operating on squares of the same color as their starting position (light or dark).
    This class implements the movement, threatening behavior, and related functionality of a Bishop in chess.

    :ivar piecetype: The type of the piece, which is 'B' for Bishop.
    :type piecetype: str
    :ivar color: The color of the piece, where 0 represents white and 1 represents black.
    :type color: int
    """
    def __init__(self, color):
        """
        Initializes a Bishop chess piece.

        The Bishop is initialized with attributes for its type ('B') and color. The `color` is used
        to identify if the piece belongs to the white or black side.

        :param color: The color of the bishop (0 for white, 1 for black).
        :type color: int
        """
        super().__init__('B', color)

    def threatens(self, square, board):
        """
        Determines the squares that this Bishop can attack, regardless of pinning.

        The Bishop moves diagonally across the board in any direction. This method calculates
        all valid squares the Bishop threatens based on unobstructed diagonal paths. If an
        opponent's piece blocks the path, that square is included as threatened; however,
        the Bishop cannot threaten squares beyond that piece.

        :param square: The square where this bishop is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: A list of squares that the Bishop can threaten.
        :rtype: list[Square]
        """
        moves = []
        pos_pos, neg_pos, neg_neg, pos_neg = True, True, True, True

        x = 0
        while pos_pos or pos_neg or neg_pos or neg_neg:
            x += 1

            # search in the positive i positive j direction
            if pos_pos:
                pp_square = board[square.i + x, square.j + x]

                if pp_square is None:
                    pos_pos = False

                elif pp_square.piece is not None:
                    pos_pos = False

                    if pp_square.piece.color != self.color:
                        moves.append(pp_square)

                else:
                    moves.append(pp_square)

            # search in the negative i positive j direction
            if neg_pos:
                np_square = board[square.i - x, square.j + x]

                if np_square is None:
                    neg_pos = False

                elif np_square.piece is not None:
                    neg_pos = False

                    if np_square.piece.color is not self.color:
                        moves.append(np_square)

                else:
                    moves.append(np_square)

            # search in the negative i negative j direction
            if neg_neg:
                nn_square = board[square.i - x, square.j - x]

                if nn_square is None:
                    neg_neg = False

                elif nn_square.piece is not None:
                    neg_neg = False

                    if nn_square.piece.color != self.color:
                        moves.append(nn_square)

                else:
                    moves.append(nn_square)

            # search in the positive i negative j direction
            if pos_neg:
                pn_square = board[square.i + x, square.j - x]

                if pn_square is None:
                    pos_neg = False

                elif pn_square.piece is not None:
                    pos_neg = False

                    if pn_square.piece.color != self.color:
                        moves.append(pn_square)

                else:
                    moves.append(pn_square)

        return moves

    def can_move(self, square, board):
        """
        Determines if this Bishop has at least one valid move.

        A Bishop is considered able to move if:
        - It is not pinned to its king (i.e., its move wouldn't expose the king to check).
        - It threatens an opponent's squares or empty squares along diagonal paths.

        If pinned, the Bishop is further restricted and cannot move except under special circumstances.

        :param square: The square where this bishop is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: `True` if the Bishop has at least one legal move, otherwise `False`.
        :rtype: bool
        """
        # if the piece is pinned, we need to check if the piece can capture the other piece that is pinning it
        if self.is_pinned(square, board):

            # gets the list of threats to the king
            king_threats1 = board.threats_on(board.find_king(self.color), self.color)

            # removes the piece from board
            board[square.i, square.j].piece = None

            # gets the list of threats to the king again
            king_threats2 = board.threats_on(board.find_king(self.color), self.color)

            # gets the threats that are not in both lists, ie the threat that the piece should be blocking
            king_threats = [threat for threat in king_threats1 + king_threats2
                            if threat not in king_threats1 or threat not in king_threats2]

            # puts the piece back
            board[square.i, square.j].piece = self

            # if there is more than one threat the king, the piece is pinned and can't move
            if len(king_threats) != 1:
                return False

            # if the threat can be taken by the pinned piece, the piece can move
            if king_threats[0] in self.threatens(square, board):
                return True

            # the piece is pinned and can't move
            return False

        # if the piece is not pinned and threatens anything, then it can move
        if len(self.threatens(square, board)) != 0:
            return True

        return False

    @staticmethod
    def find(board, square, color, capture, file_limit=None, rank_limit=None, errors=True):
        """
        Finds the Bishop that corresponds to a given move.

        Chess moves provide limited information to locate a specific piece, such as its
        type (Bishop), the target square, and optional file or rank constraints. This
        method performs a targeted search to find valid Bishops that match the move's description.

        If the `errors` flag is set to `True`, this method validates the legality of the
        identified Bishop(s) for the move. If a valid Bishop cannot be determined, or if
        multiple matching Bishops are found, it raises appropriate exceptions.

        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :param square: The square where the Bishop is attempting to move.
        :type square: Square
        :param color: The color of the Bishop being searched for (0 for white, 1 for black).
        :type color: int
        :param capture: Indicates whether the move involves capturing an opponent's piece.
        :type capture: bool
        :param file_limit: (Optional) Restricts to find Bishops in a specific file (e.g., 'a', 'b', etc.).
        :type file_limit: str or None
        :param rank_limit: (Optional) Restricts to find Bishops in a specific rank (e.g., '1', '2', etc.).
        :type rank_limit: str or None
        :param errors: If `True`, raises exceptions for invalid moves or ambiguities.
                       If `False`, returns `None` for invalid moves instead.
        :type errors: bool
        :return: The Bishop that can execute the move, or a list if multiples are found, or `None` when `errors=False`.
        :rtype: Bishop or list[Bishop] or None
        :raises ChessError.PieceNotFoundError: If no eligible Bishop is found for the move.
        :raises ChessError.MultiplePiecesFoundError: If more than one matching Bishop is found.
        :raises ChessError.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises ChessError.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises ChessError.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        found = []
        pos_pos, neg_pos, neg_neg, pos_neg = True, True, True, True

        x = 0
        while pos_pos or pos_neg or neg_pos or neg_neg:
            x += 1

            # search in the positive i positive j direction
            if pos_pos:
                pp_square = board[square.i + x, square.j + x]

                if pp_square is None:
                    pos_pos = False

                elif pp_square.piece is not None:
                    pos_pos = False

                    if pp_square.piece.piecetype == 'B' and pp_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][pp_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - pp_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][pp_square.j]
                                    and rank_limit == str(8 - pp_square.i))
                        ):
                            found.append(pp_square)

            # search in the negative i positive j direction
            if neg_pos:
                np_square = board[square.i - x, square.j + x]

                if np_square is None:
                    neg_pos = False

                elif np_square.piece is not None:
                    neg_pos = False

                    if np_square.piece.piecetype == 'B' and np_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][np_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - np_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][np_square.j]
                                    and rank_limit == str(8 - np_square.i))
                        ):
                            found.append(np_square)

            # search in the negative i negative j direction
            if neg_neg:
                nn_square = board[square.i - x, square.j - x]

                if nn_square is None:
                    neg_neg = False

                elif nn_square.piece is not None:
                    neg_neg = False

                    if nn_square.piece.piecetype == 'B' and nn_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][nn_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - nn_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][nn_square.j]
                                    and rank_limit == str(8 - nn_square.i))
                        ):
                            found.append(nn_square)

            # search in the positive i negative j direction
            if pos_neg:
                pn_square = board[square.i + x, square.j - x]

                if pn_square is None:
                    pos_neg = False

                elif pn_square.piece is not None:
                    pos_neg = False

                    if pn_square.piece.piecetype == 'B' and pn_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][pn_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - pn_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][pn_square.j]
                                    and rank_limit == str(8 - pn_square.i))
                        ):
                            found.append(pn_square)

        if len(found) == 0:
            if errors:
                raise ChessError.PieceNotFoundError(square, 'B')
            else:
                return None

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise ChessError.NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise ChessError.CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise ChessError.PieceOnSquareError(square, True)
                    else:
                        raise ChessError.PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise ChessError.MultiplePiecesFoundError(square, found)
            else:
                return found


class Queen(Piece):
    """
    Represents a Queen chess piece.

    A subclass of the `Piece` class. The Queen is the most versatile piece in chess,
    combining the movement patterns of both the Rook (horizontal and vertical) and
    the Bishop (diagonal). It can move any number of squares along a rank, file, or diagonal
    but may not leap over other pieces. This class implements the movement, threatening
    behavior, and related functionality of a Queen in chess.

    :ivar piecetype: The type of the piece, which is 'Q' for Queen.
    :type piecetype: str
    :ivar color: The color of the piece, where 0 represents white and 1 represents black.
    :type color: int
    """
    def __init__(self, color):
        """
        Initializes a Queen chess piece.

        The Queen is initialized with attributes for its type ('Q') and color. The `color` is used
        to identify if the piece belongs to the white or black side.

        :param color: The color of the Queen (0 for white, 1 for black).
        :type color: int
        """
        super().__init__('Q', color)

    def threatens(self, square, board):
        """
        Determines the squares that this Queen can attack, regardless of pinning.

        The Queen combines the movement capabilities of a Rook and a Bishop. It threatens
        squares along ranks (horizontal), files (vertical), and diagonals. This method calculates
        all valid squares the Queen threatens until blocked by another piece. If the blocking piece
        belongs to the opponent, that square is treated as threatened.

        :param square: The square where this queen is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: A list of squares that the Queen can threaten.
        :rtype: list[Square]
        """
        moves = []
        i_pos, pos_pos, j_pos, neg_pos, i_neg, neg_neg, j_neg, pos_neg = True, True, True, True, True, True, True, True

        x = 0
        while i_pos or pos_pos or j_pos or neg_pos or i_neg or neg_neg or j_neg or pos_neg:
            x += 1

            # search in positive i direction
            if i_pos:
                i_pos_square = board[square.i + x, square.j]

                if i_pos_square is None:
                    i_pos = False

                elif i_pos_square.piece is not None:
                    i_pos = False

                    if i_pos_square.piece.color != self.color:
                        moves.append(i_pos_square)

                else:
                    moves.append(i_pos_square)

            # search in the positive i positive j direction
            if pos_pos:
                pp_square = board[square.i + x, square.j + x]

                if pp_square is None:
                    pos_pos = False

                elif pp_square.piece is not None:
                    pos_pos = False

                    if pp_square.piece.color != self.color:
                        moves.append(pp_square)

                else:
                    moves.append(pp_square)

            # search in positive j direction
            if j_pos:
                j_pos_square = board[square.i, square.j + x]

                if j_pos_square is None:
                    j_pos = False

                elif j_pos_square.piece is not None:
                    j_pos = False

                    if j_pos_square.piece.color != self.color:
                        moves.append(j_pos_square)

                else:
                    moves.append(j_pos_square)

            # search in the negative i positive j direction
            if neg_pos:
                np_square = board[square.i - x, square.j + x]

                if np_square is None:
                    neg_pos = False

                elif np_square.piece is not None:
                    neg_pos = False

                    if np_square.piece.color is not self.color:
                        moves.append(np_square)

                else:
                    moves.append(np_square)

            # search in negative i direction
            if i_neg:
                i_neg_square = board[square.i - x, square.j]

                if i_neg_square is None:
                    i_neg = False

                elif i_neg_square.piece is not None:
                    i_neg = False

                    if i_neg_square.piece.color != self.color:
                        moves.append(i_neg_square)

                else:
                    moves.append(i_neg_square)

            # search in the negative i negative j direction
            if neg_neg:
                nn_square = board[square.i - x, square.j - x]

                if nn_square is None:
                    neg_neg = False

                elif nn_square.piece is not None:
                    neg_neg = False

                    if nn_square.piece.color != self.color:
                        moves.append(nn_square)

                else:
                    moves.append(nn_square)

            # search in negative j direction
            if j_neg:
                j_neg_square = board[square.i, square.j - x]

                if j_neg_square is None:
                    j_neg = False

                elif j_neg_square.piece is not None:
                    j_neg = False

                    if j_neg_square.piece.color != self.color:
                        moves.append(j_neg_square)

                else:
                    moves.append(j_neg_square)

            # search in the positive i negative j direction
            if pos_neg:
                pn_square = board[square.i + x, square.j - x]

                if pn_square is None:
                    pos_neg = False

                elif pn_square.piece is not None:
                    pos_neg = False

                    if pn_square.piece.color != self.color:
                        moves.append(pn_square)

                else:
                    moves.append(pn_square)

        return moves

    def can_move(self, square, board):
        """
        Determines if this Queen has at least one valid move.

        A Queen is considered able to move if:
        - It is not pinned to its king (i.e., its move wouldn't expose the king to check).
        - It threatens squares along lines of movement (ranks, files, diagonals).

        A pinned Queen is further restricted and may have limited moves to respond to the pin.

        :param square: The square where this queen is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: `True` if the Queen has at least one legal move, otherwise `False`.
        :rtype: bool
        """
        # if the piece is pinned, we need to check if the piece can capture the other piece that is pinning it
        if self.is_pinned(square, board):

            # gets the list of threats to the king
            king_threats1 = board.threats_on(board.find_king(self.color), self.color)

            # removes the piece from board
            board[square.i, square.j].piece = None

            # gets the list of threats to the king again
            king_threats2 = board.threats_on(board.find_king(self.color), self.color)

            # gets the threats that are not in both lists, ie the threat that the piece should be blocking
            king_threats = [threat for threat in king_threats1 + king_threats2
                            if threat not in king_threats1 or threat not in king_threats2]

            # puts the piece back
            board[square.i, square.j].piece = self

            # if there is more than one threat the king, the piece is pinned and can't move
            if len(king_threats) != 1:
                return False

            # if the threat can be taken by the pinned piece, the piece can move
            if king_threats[0] in self.threatens(square, board):
                return True

            # the piece is pinned and can't move
            return False

        # if the piece is not pinned and threatens anything, then it can move
        if len(self.threatens(square, board)) != 0:
            return True

        return False

    @staticmethod
    def find(board, square, color, capture, file_limit=None, rank_limit=None, errors=True):
        """
        Finds the Queen that corresponds to a given move.

        Chess moves provide limited information to locate a specific piece, such as its
        type (Queen), the target square, and optional file or rank constraints. This
        method performs a targeted search to find valid Queens that match the move's description.

        If the `errors` flag is set to `True`, this method validates the legality of the
        identified Queen(s) for the move. If a valid Queen cannot be determined, or if
        multiple matching Queens are found, it raises appropriate exceptions.

        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :param square: The square where the Queen is attempting to move.
        :type square: Square
        :param color: The color of the Queen being searched for (0 for white, 1 for black).
        :type color: int
        :param capture: Indicates whether the move involves capturing an opponent's piece.
        :type capture: bool
        :param file_limit: (Optional) Restricts to find Queens in a specific file (e.g., 'a', 'b', etc.).
        :type file_limit: str or None
        :param rank_limit: (Optional) Restricts to find Queens in a specific rank (e.g., '1', '2', etc.).
        :type rank_limit: str or None
        :param errors: If `True`, raises exceptions for invalid moves or ambiguities.
                       If `False`, returns `None` for invalid moves instead.
        :type errors: bool
        :return: The Queen that can execute the move, or a list if multiples are found, or `None` when `errors=False`.
        :rtype: Queen or list[Queen] or None
        :raises ChessError.PieceNotFoundError: If no eligible Queen is found for the move.
        :raises ChessError.MultiplePiecesFoundError: If more than one matching Queen is found.
        :raises ChessError.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises ChessError.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises ChessError.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        found = []
        i_pos, pos_pos, j_pos, neg_pos, i_neg, neg_neg, j_neg, pos_neg = True, True, True, True, True, True, True, True

        x = 0
        while i_pos or pos_pos or j_pos or neg_pos or i_neg or neg_neg or j_neg or pos_neg:
            x += 1

            # search in positive i direction
            if i_pos:
                i_pos_square = board[square.i + x, square.j]

                if i_pos_square is None:
                    i_pos = False

                elif i_pos_square.piece is not None:
                    i_pos = False

                    if i_pos_square.piece.piecetype == 'Q' and i_pos_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][i_pos_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - i_pos_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][i_pos_square.j]
                                    and rank_limit == str(8 - i_pos_square.i))
                        ):
                            found.append(i_pos_square)

            # search in the positive i positive j direction
            if pos_pos:
                pp_square = board[square.i + x, square.j + x]

                if pp_square is None:
                    pos_pos = False

                elif pp_square.piece is not None:
                    pos_pos = False

                    if pp_square.piece.piecetype == 'Q' and pp_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][pp_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - pp_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][pp_square.j]
                                    and rank_limit == str(8 - pp_square.i))
                        ):
                            found.append(pp_square)

            # search in positive j direction
            if j_pos:
                j_pos_square = board[square.i, square.j + x]

                if j_pos_square is None:
                    j_pos = False

                elif j_pos_square.piece is not None:
                    j_pos = False

                    if j_pos_square.piece.piecetype == 'Q' and j_pos_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j_pos_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - j_pos_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j_pos_square.j]
                                    and rank_limit == str(8 - j_pos_square.i))
                        ):
                            found.append(j_pos_square)

            # search in the negative i positive j direction
            if neg_pos:
                np_square = board[square.i - x, square.j + x]

                if np_square is None:
                    neg_pos = False

                elif np_square.piece is not None:
                    neg_pos = False

                    if np_square.piece.piecetype == 'Q' and np_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][np_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - np_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][np_square.j]
                                    and rank_limit == str(8 - np_square.i))
                        ):
                            found.append(np_square)

            # search in negative i direction
            if i_neg:
                i_neg_square = board[square.i - x, square.j]

                if i_neg_square is None:
                    i_neg = False

                elif i_neg_square.piece is not None:
                    i_neg = False

                    if i_neg_square.piece.piecetype == 'Q' and i_neg_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][i_neg_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - i_neg_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][i_neg_square.j]
                                    and rank_limit == str(8 - i_neg_square.i))
                        ):
                            found.append(i_neg_square)

            # search in the negative i negative j direction
            if neg_neg:
                nn_square = board[square.i - x, square.j - x]

                if nn_square is None:
                    neg_neg = False

                elif nn_square.piece is not None:
                    neg_neg = False

                    if nn_square.piece.piecetype == 'Q' and nn_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][nn_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - nn_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][nn_square.j]
                                    and rank_limit == str(8 - nn_square.i))
                        ):
                            found.append(nn_square)

            # search in negative j direction
            if j_neg:
                j_neg_square = board[square.i, square.j - x]

                if j_neg_square is None:
                    j_neg = False

                elif j_neg_square.piece is not None:
                    j_neg = False

                    if j_neg_square.piece.piecetype == 'Q' and j_neg_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j_neg_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - j_neg_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j_neg_square.j]
                                    and rank_limit == str(8 - j_neg_square.i))
                        ):
                            found.append(j_neg_square)

            # search in the positive i negative j direction
            if pos_neg:
                pn_square = board[square.i + x, square.j - x]

                if pn_square is None:
                    pos_neg = False

                elif pn_square.piece is not None:
                    pos_neg = False

                    if pn_square.piece.piecetype == 'Q' and pn_square.piece.color == color:
                        # this checks for rank and file limits
                        if (
                                (rank_limit is None and file_limit is None)
                                or (file_limit is not None and rank_limit is None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][pn_square.j])
                                or (rank_limit is not None and file_limit is None
                                    and rank_limit == str(8 - pn_square.i))
                                or (rank_limit is not None and file_limit is not None
                                    and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][pn_square.j]
                                    and rank_limit == str(8 - pn_square.i))
                        ):
                            found.append(pn_square)

        if len(found) == 0:
            if errors:
                raise ChessError.PieceNotFoundError(square, 'Q')
            else:
                return None

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise ChessError.NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise ChessError.CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise ChessError.PieceOnSquareError(square, True)
                    else:
                        raise ChessError.PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise ChessError.MultiplePiecesFoundError(square, found)
            else:
                return found


class King(Piece):
    """
    Represents the King chess piece.

    A subclass of the `Piece` class. The King is the most crucial piece in chess and has
    restricted movement. It can move one square in any direction but cannot move into a square
    under attack. Additionally, the King has special castling rules, which are implemented
    in this class.

    :ivar piecetype: The type of the piece, which is 'K' for King.
    :type piecetype: str
    :ivar color: The color of the piece, where 0 represents white and 1 represents black.
    :type color: int
    :ivar moved: Indicates whether the King has moved. Used to determine if castling is allowed.
    :type moved: bool
    """
    def __init__(self, color, moved=False):
        """
        Initializes a King chess piece.

        The King is initialized with a color, and whether it has moved.
        The `color` is used to identify if the piece belongs to the white
        or black side, and the `moved` attribute helps determine if this King can still
        participate in castling.

        :param color: The color of the piece (0 for white, 1 for black).
        :type color: int
        :param moved: Indicates whether the King has moved. Defaults to `False`.
        :type moved: bool, optional
        """
        super().__init__('K', color)

        self.moved = moved

    def threatens(self, square, board):
        """
        Determines the squares that this King can threaten.

        The King threatens all adjacent squares in any direction (horizontally, vertically,
        or diagonally). However, this is independent of whether those squares are under threat
        themselves or are occupied by an opponent's piece.

        :param square: The square where this King is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: A list of squares that the King can threaten.
        :rtype: list[Square]
        """
        moves = []
        delta_is = [1, 1, 0, -1, -1, -1, 0, 1]
        delta_js = [0, 1, 1, 1, 0, -1, -1, -1]

        for x in range(8):

            psquare = board[square.i + delta_is[x], square.j + delta_js[x]]

            # The square must exist
            # If there is a piece on the square, it must be a different color than the current piece
            if (
                    psquare is not None
                    and ((psquare.piece is not None and psquare.piece.color != self.color)
                         or psquare.piece is None)
            ):
                moves.append(psquare)

        return moves

    def can_move(self, square, board):
        """
        Determines if this King has at least one valid move.

        The King can legally move to a square if:
        - The square is one step away in any direction (horizontal, vertical, or diagonal).
        - The square is not under attack by any of the opponent's pieces.

        :param square: The square where this King is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: `True` if the King has at least one legal move, otherwise `False`.
        :rtype: bool
        """
        threatens = self.threatens(square, board)
        for threat in threatens:
            if len(board.threats_on(threat, self.color)) == 0:
                return True
        return False

    def can_castle(self, board, direction):
        """
        Determines if the King can perform a castling move.

        Castling is a special move involving the King and one of the Rooks, executed under these conditions:
        - The King and the chosen Rook (either kingside or queenside) have not moved yet.
        - All squares between the King and the Rook are unoccupied.
        - None of the squares the King travels through (or lands on) are under attack.

        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :param direction: Specifies the side for castling:
                          - `'K'` for kingside castling.
                          - `'Q'` for queenside castling.
        :type direction: str
        :return: `True` if castling is allowed in the specified direction, otherwise `False`.
        :rtype: bool
        """
        # if the king moved, no castle
        if self.moved:
            return False

        x = 7 if self.color == 0 else 0

        # king side castle...
        if direction == 'K':

            king_rook_square = board[x, 0]
            between_square1, between_square2 = board[x, 5], board[x, 6]

            if (
                    king_rook_square.piece is not None
                    and king_rook_square.piece.piecetype == 'R'
                    and king_rook_square.piece.color == self.color
                    and not king_rook_square.piece.moved
                    and between_square1.piece is None
                    and len(board.threats_on(between_square1, self.color)) == 0
                    and between_square2.piece is None
            ):
                return True

        # queen side castle...
        elif direction == 'Q':

            queen_rook_square = board[x, 7]
            between_square1, between_square2, between_square3 = board[x, 1], board[x, 2], board[x, 3]

            if (
                    queen_rook_square.piece is not None
                    and queen_rook_square.piece.piecetype == 'R'
                    and queen_rook_square.piece.color == self.color
                    and not queen_rook_square.piece.moved
                    and between_square1.piece is None
                    and between_square2.piece is None
                    and len(board.threats_on(between_square2, self.color)) == 0
                    and between_square3.piece is None
            ):
                return True

        return False

    @staticmethod
    def find(board, square, color, capture, file_limit=None, rank_limit=None, errors=True):
        """
        Finds the King that corresponds to a given move.

        Since each side has only one King, this method validates whether the move involves the
        King and checks the constraints provided (e.g., file, rank limits). If the King is under
        check, additional conditions may apply to validate its moves.

        If the `errors` flag is set to `True`, this method verifies the legality of the move and
        raises exceptions when invalid. When `errors` is `False`, it will return `None` for invalid
        moves instead of raising exceptions.

        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :param square: The square where the King is attempting to move.
        :type square: Square
        :param color: The color of the King being searched for (0 for white, 1 for black).
        :type color: int
        :param capture: Indicates whether the move involves capturing an opponent's piece.
        :type capture: bool
        :param file_limit: (Optional) Restricts to find the King in a specific file (e.g., 'a', 'b', etc.).
        :type file_limit: str or None
        :param rank_limit: (Optional) Restricts to find the King in a specific rank (e.g., '1', '2', etc.).
        :type rank_limit: str or None
        :param errors: If `True`, raises exceptions for invalid moves or ambiguous cases.
                       If `False`, returns `None` for invalid moves instead.
        :type errors: bool
        :return: The King if it matches the given move, or `None` when `errors=False`.
        :rtype: King or None
        :raises ChessError.PieceNotFoundError: If no King is found on the board matching the criteria.
        :raises ChessError.NothingToCaptureError: If opponent's piece exists on the target square.
        :raises ChessError.CaptureOwnPieceError: If an allied piece exists on the target square.
        :raises ChessError.PieceOnSquareError: If an invalid move is attempted, such as landing
                                               on an occupied square.
        """
        found = []
        delta_is = [1, 1, 0, -1, -1, -1, 0, 1]
        delta_js = [0, 1, 1, 1, 0, -1, -1, -1]

        for index in range(8):

            psquare = board[square.i + delta_is[index], square.j + delta_js[index]]

            # The square must exist
            # If there is a piece on the square, it must be the same color as the player
            if (
                    psquare is not None
                    and psquare.piece is not None
                    and psquare.piece.piecetype == 'K'
                    and psquare.piece.color == color
            ):
                # this checks for rank and file limits
                if (
                        (rank_limit is None and file_limit is None)
                        or (file_limit is not None and rank_limit is None
                            and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][psquare.j])
                        or (rank_limit is not None and file_limit is None
                            and rank_limit == str(8 - psquare.i))
                        or (rank_limit is not None and file_limit is not None
                            and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][psquare.j]
                            and rank_limit == str(8 - psquare.i))
                ):
                    found.append(psquare)

        if len(found) == 0:
            if errors:
                raise ChessError.PieceNotFoundError(square, 'K')
            else:
                return found

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise ChessError.NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise ChessError.CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise ChessError.PieceOnSquareError(square, True)
                    else:
                        raise ChessError.PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise ChessError.MultiplePiecesFoundError(square, found)
            else:
                return found


class Pawn(Piece):
    """
    Represents a Pawn chess piece.

    A subclass of the `Piece` class. The Pawn has unique movement and capturing rules:
    - It moves forward (one square at a time or two squares on its first move).
    - It captures diagonally.
    - Special rules include the "en passant" capture and promotion when reaching the opposite end of the board.

    :ivar piecetype: The type of the piece, which is 'P' for Pawn.
    :type piecetype: str
    :ivar color: The color of the piece, where 0 represents white and 1 represents black.
    :type color: int
    """
    def __init__(self, color):
        """
        Initializes a Pawn chess piece.

        The Pawn is set up with its type ('P') and color, which determines its movement direction
        (white moves upward, black moves downward).

        :param color: The color of the Pawn (0 for white, 1 for black).
        :type color: int
        """
        super().__init__('P', color)

    def threatens(self, square, board):
        """
        Determines the squares that this Pawn can attack.

        A Pawn threatens diagonally forward squares based on its color:
        - For a white Pawn, this means threatening squares one step forward-left and forward-right.
        - For a black Pawn, this means threatening squares one step backward-left and backward-right.

        :param square: The square where this Pawn is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: A list of squares that the Pawn can attack or threaten.
        :rtype: list[Square]
        """
        moves = []

        # the direction the pawn threatens is determined by the player's color
        x = -1 if self.color == 0 else 1

        for y in [1, -1]:
            psquare = board[square.i + x, square.j + y]

            if (
                    # The square must exist
                    # If there is a piece on the square, it must be a different color than the current piece
                    psquare is not None
                    and ((psquare.piece is not None and psquare.piece.color != self.color)
                         or psquare.piece is None)
            ):
                moves.append(psquare)

        return moves

    def can_move(self, square, board):
        """
        Checks if this Pawn has any valid moves.

        The Pawn can move forward one square if unblocked, or two squares if it is its first move
        and both squares are unblocked. Additionally:
        - It can capture pieces diagonally forward on adjacent squares.
        - It can also capture a piece via "en passant" if applicable.

        This method also considers if the Pawn is pinned and adjusts its validity checks accordingly.

        :param square: The square where this Pawn is currently located.
        :type square: Square
        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :return: `True` if the Pawn can make at least one valid move, otherwise `False`.
        :rtype: bool
        """
        # if the piece is pinned, we need to check if the piece can capture the other piece that is pinning it
        if self.is_pinned(square, board):

            # gets the list of threats to the king
            king_threats1 = board.threats_on(board.find_king(self.color), self.color)

            # removes the piece from board
            board[square.i, square.j].piece = None

            # gets the list of threats to the king again
            king_threats2 = board.threats_on(board.find_king(self.color), self.color)

            # gets the threats that are not in both lists, ie the threat that the piece should be blocking
            king_threats = [threat for threat in king_threats1 + king_threats2
                            if threat not in king_threats1 or threat not in king_threats2]

            # puts the piece back
            board[square.i, square.j].piece = self

            # if there is more than one threat the king, the piece is pinned and can't move
            if len(king_threats) > 1 and king_threats[0] in self.threatens(square, board):
                return True

            # the piece is pinned and can't move
            return False

        ## the piece is not pinned:
        # the direction the pawn moves is determined by the player's color
        x = -1 if self.color == 0 else 1

        # checks if the pawn can move to the square directly in front of it
        # does not have to check square 2 in front, bc it can only do that if it can move to square 1 in front
        psquare = board[square.i + x, square.j]
        if psquare is not None and psquare.piece is None:
            return True

        threatens = self.threatens(square, board)
        if len(threatens) != 0:
            for threat in threatens:
                if threat.piece is not None and threat.piece.color != self.color:
                    return True

        return False

    @staticmethod
    def find(board, square, color, capture, file_limit=None, rank_limit=None, errors=True, en=False):
        """
        Finds a Pawn on the board that matches a given move.

        Pawns have unique behavior compared to other pieces:
        - If not capturing, they are checked for one or two steps behind the target square, depending on
          whether the move is a single or double square advance.
        - If capturing, they are checked on diagonally adjacent squares.
        - If "en passant" capture is involved, a hit on the diagonally adjacent square will be validated by
          matching the Pawn that made the two-square move.

        If the `errors` flag is set to `True`, exceptions are raised for invalid moves. Otherwise, invalid
        moves will return `None` or an empty list.

        :param board: The chessboard containing all pieces and their positions.
        :type board: Board
        :param square: The target square where the move is being attempted.
        :type square: Square
        :param color: The color of the Pawn being searched for (0 for white, 1 for black).
        :type color: int
        :param capture: Indicates whether the move involves capturing an opponent's piece.
        :type capture: bool
        :param file_limit: (Optional) Restricts to find Pawns in a specific file (e.g., 'a', 'b', etc.).
        :type file_limit: str or None
        :param rank_limit: (Optional) Restricts to find Pawns in a specific rank (e.g., '1', '2', etc.).
        :type rank_limit: str or None
        :param errors: If `True`, raises exceptions for invalid moves. If `False`, returns `None` for invalid cases.
        :type errors: bool
        :param en: Indicates whether the search includes checking for an "en passant" capture.
        :type en: bool
        :return: The Pawn that matches the given move, or a list of possible Pawns, or `None` for invalid moves.
        :rtype: Pawn or list[Pawn] or None
        :raises ChessError.PieceNotFoundError: If no Pawn is found on the board matching the criteria.
        :raises ChessError.NothingToCaptureError: If no opponent's piece is present to capture on the target square.
        :raises ChessError.CaptureOwnPieceError: If an allied piece is found on the target square.
        :raises ChessError.MultiplePiecesFoundError: If several Pawns match, making the move ambiguous.
        """
        x = 1 if color == 0 else -1

        if not capture:

            square1 = board[square.i + x, square.j]
            square2 = board[square.i + (x * 2), square.j]

            # checks directly behind the square
            if (
                    square1 is not None
                    and square1.piece is not None
                    and square1.piece.piecetype == 'P'
                    and square1.piece.color == color
            ):
                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                if square.piece is not None and errors:
                    if square.piece.color == color:
                        raise ChessError.PieceOnSquareError(square, True)
                    else:
                        raise ChessError.PieceOnSquareError(square, False)

                # this checks for rank and file limits
                if (
                        (rank_limit is None and file_limit is None)
                        or (file_limit is not None and rank_limit is None
                            and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][square1.j])
                        or (rank_limit is not None and file_limit is None
                            and rank_limit == str(8 - square1.i))
                        or (rank_limit is not None and file_limit is not None
                            and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][square1.j]
                            and rank_limit == str(8 - square1.i))
                ):
                    return square1

                # this will only be raised if rank and file limit conditions are not met
                if errors:
                    raise ChessError.PieceNotFoundError(square, 'P')
                else:
                    return None

            # checks two squares behind the pawn
            elif (
                    square1 is not None
                    and square1.piece is None
                    and square2 is not None
                    and square2.piece is not None
                    and square2.piece.piecetype == 'P'
                    and square2.piece.color == color
            ):
                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                if square.piece is not None and errors:
                    if square.piece.color == color:
                        raise ChessError.PieceOnSquareError(square, True)
                    else:
                        raise ChessError.PieceOnSquareError(square, False)

                # this checks for rank and file limits
                if (
                        (rank_limit is None and file_limit is None)
                        or (file_limit is not None and rank_limit is None
                            and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][square2.j])
                        or (rank_limit is not None and file_limit is None
                            and rank_limit == str(8 - square2.i))
                        or (rank_limit is not None and file_limit is not None
                            and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][square2.j]
                            and rank_limit == str(8 - square2.i))
                ):
                    board.two_moveP = square
                    return square2

                # this will only be raised if rank and file limit conditions are not met
                if errors:
                    raise ChessError.PieceNotFoundError(square, 'P')
                else:
                    return None

            elif errors:
                raise ChessError.PieceNotFoundError(square, 'P')
            else:
                return None

        # if capture
        else:

            # checks the squares that are one backwards and one to the left/right
            found = []

            for y in [1, -1]:
                psquare1 = board[square.i + x, square.j + y]

                if (
                        psquare1 is not None
                        and psquare1.piece is not None
                        and psquare1.piece.piecetype == 'P'
                        and psquare1.piece.color == color
                ):

                    # this checks for rank and file limits
                    if (
                            (rank_limit is None and file_limit is None)
                            or (file_limit is not None and rank_limit is None
                                and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][psquare1.j])
                            or (rank_limit is not None and file_limit is None
                                and rank_limit == str(8 - psquare1.i))
                            or (rank_limit is not None and file_limit is not None
                                and file_limit == ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][psquare1.j]
                                and rank_limit == str(8 - psquare1.i))
                    ):
                        found.append(psquare1)

            if len(found) == 0:
                if errors:
                    raise ChessError.PieceNotFoundError(square, 'P')
                else:
                    return found

            elif len(found) == 1:

                # if the player is capturing, there must be an opponent's piece on the square (or pass en passant check)
                if square.piece is None and errors:

                    # this will check for a valid en passant, if needed
                    if en:
                        psquare2 = board[square.i + x, square.j]

                        if not (
                            psquare2 is not None
                            and psquare2.piece is not None
                            and psquare2.piece.piecetype == 'P'
                            and psquare2.piece.color != color
                            and board.two_moveP == psquare2
                        ):
                            raise ChessError.NothingToCaptureError(square)

                    else:
                        raise ChessError.NothingToCaptureError(square)

                elif square.piece is not None and square.piece.color == color and errors:
                    raise ChessError.CaptureOwnPieceError(square)

                return found[0]

            else:
                if errors:
                    raise ChessError.MultiplePiecesFoundError(square, found)
                else:
                    return found


class Square:
    """
    Represents a square on a chessboard.

    A square is one of 64 positions on a chessboard, identifiable by its
    coordinates `(i, j)` and chess notation (e.g., 'e4', 'a1'). It also
    stores the square's color and can optionally hold a chess piece.

    :ivar i: The row position (coordinate) of the square on the board,
        where 0 represents the top row (rank 8) and 7 represents the
        bottom row (rank 1).
    :type i: int
    :ivar j: The column position (coordinate) of the square on the board,
        where 0 represents the leftmost file ('a') and 7 represents the
        rightmost file ('h').
    :type j: int
    :ivar c_notation: The chess notation string of the square (e.g., 'a8', 'd4').
        This represents a file ('a' to 'h') combined with a rank ('1' to '8').
    :type c_notation: str
    :ivar color: The color of the square, where 0 represents light (white) and
        1 represents dark (black).
    :type color: int
    :ivar piece: The chess piece currently occupying the square, or `None` if
        the square is empty.
    :type piece: Optional[Piece]
    """
    def __init__(self, i, j, piece=None):
        """
        Initializes a square on a chessboard.

        This sets up the essential data for a square, including its position,
        chess notation, color, and any chess piece located on it.

        :param i: The row position of the square (0-7), where 0 is the top row (rank 8)
            and 7 is the bottom row (rank 1).
        :type i: int
        :param j: The column position of the square (0-7), where 0 is the leftmost
            file ('a') and 7 is the rightmost file ('h').
        :type j: int
        :param piece: The chess piece located on the square, or `None` if the square
            is empty. Defaults to `None`.
        :type piece: Optional[Piece]
        """
        # i and j are the square's coordinates on the board
        # c_notation is the chess notation for the square (in a string form)
        # color will be a binary bool where light is 0 and dark is 1
        # piece will either be a piece object or None

        self.i = i
        self.j = j

        # converts from coords to chess notation
        self.c_notation = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j] + str(8 - i)

        # determines color of square
        self.color = j % 2 if (i % 2) == 0 else (j + 1) % 2

        # sets the piece
        self.piece = piece

    def __eq__(self, other):
        """
        Compares two squares for equality.

        Two squares are considered equal if they have the same row (`i`)
        and column (`j`) coordinates.

        :param other: The other square to compare against.
        :type other: Square or None
        :return: `True` if the squares have the same coordinates,
            otherwise `False`.
        :rtype: bool
        """
        if other is None:
            return False

        if self.i == other.i and self.j == other.j:
            return True
        return False


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
        # status meaning:
        #   - a "0" status means the game is in play
        #   - a "1" status means the game ended with checkmate
        #   - a "2" status means the game ended with stalemate
        self.status = 0

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
                    out += self[i, j].piece.piecetype
                    out += str(self[i, j].piece.color)
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
        :raises ChessError.InvalidMoveError: If the move is invalid.
        :raises ChessError.PromotionError: If an invalid promotion is attempted or a promotion is required.
        :raises ChessError.InvalidCastleError: If an invalid castling move is attempted.
        :raises ChessError.PieceNotFoundError: If no eligible piece is found for the move.
        :raises ChessError.MultiplePiecesFoundError: If more than one matching piece is found.
        :raises ChessError.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises ChessError.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises ChessError.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        prev_two_moveP = self.two_moveP

        # makes the move object
        m = Move(move, player, self)

        # if en passant, delete the old piece
        if m.en:
            x = 1 if player == 0 else -1
            self[m.to.i + x, m.to.j].piece = None

        # moving the rook for castling
        if m.castle is not None:
            x = 7 if player == 0 else 0
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
            raise ChessError.MoveIntoCheckError

        # changes the game status if a mate or stalemate is detected
        if self.check_for_mate(1 - player):
            self.status = 1
        elif not self.check_for_check(1-player) and self.check_for_stalemate(1 - player):
            self.status = 2

        # if no pawns where moved two squares, the board remembers
        if prev_two_moveP is not None and self.two_moveP == prev_two_moveP:
            self.two_moveP = None

        # if the piece is a rook or a king, sets moved to True
        if new_piece.piecetype == 'K' or new_piece.piecetype == 'R':
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
        self.two_moveP = prev_two_moveP

        # if en passant, places back the old piece
        if move.en:
            x = 1 if player == 0 else -1
            self[move.to.i + x, move.to.j].piece = Pawn(1 - player)

        # moving the rook for castling
        if move.castle is not None:
            x = 7 if player == 0 else 0
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
        for x in range(8):

            # if color is white, search from bottom up
            # if color is black, search from top down
            i = 7 - x if color == 0 else x

            # search from right to left (it is common to kingside castle, which is towards the right)
            for j in range(7, -1, -1):

                if (
                        self[i, j].piece is not None
                        and self[i, j].piece.piecetype == 'K'
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
        threats = []

        pawns = Pawn.find(self, square, 1 - player, True, errors=False)
        if isinstance(pawns, Square):
            threats.append(pawns)
        elif pawns is not None:
            threats.extend(pawns)

        rooks = Rook.find(self, square, 1 - player, False, errors=False)
        if isinstance(rooks, Square):
            threats.append(rooks)
        elif rooks is not None:
            threats.extend(rooks)

        knights = Knight.find(self, square, 1 - player, False, errors=False)
        if isinstance(knights, Square):
            threats.append(knights)
        elif knights is not None:
            threats.extend(knights)

        bishops = Bishop.find(self, square, 1 - player, False, errors=False)
        if isinstance(bishops, Square):
            threats.append(bishops)
        elif bishops is not None:
            threats.extend(bishops)

        queens = Queen.find(self, square, 1 - player, False, errors=False)
        if isinstance(queens, Square):
            threats.append(queens)
        elif queens is not None:
            threats.extend(queens)

        kings = King.find(self, square, 1 - player, False, errors=False)
        if isinstance(kings, Square):
            threats.append(kings)
        elif kings is not None:
            threats.extend(kings)

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

        threats = self.threats_on(king_square, player)

        # if there are zero threats on the king, he is not in check
        if len(threats) == 0:
            return False

        # if there are threats on the king, he is in check
        else:
            return True

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
        if not self.check_for_check(player):
            return False

        king_square = self.find_king(player)
        if king_square is None:
            return False

        threats = self.threats_on(king_square, player)

        # checks if the kings can move
        delta_is = [1, 1, 0, -1, -1, -1, 0, 1]
        delta_js = [0, 1, 1, 1, 0, -1, -1, -1]
        for index in range(8):

            psquare = self[king_square.i + delta_is[index], king_square.j + delta_js[index]]

            # if there is a square that the king can move to, returns false
            if (
                    psquare is not None
                    and (psquare.piece is None
                         or (psquare.piece is not None and psquare.piece.color == 1 - player))
                    and len(self.threats_on(psquare, player)) == 0
            ):
                return False

        # checks if the piece threatening can be taken OR if the piece threatening can be blocked
        if len(threats) == 1:  # this will only work if there is only one threatening piece

            # this is the only threat, now saved to threat
            threat = threats[0]

            # if the piece can be taken, returns False
            if len(self.threats_on(threat, 1 - player)) > 0:
                return False

            # blocking
            if threat.piece.piecetype == 'R' or threat.piece.piecetype == 'B' or threat.piece.piecetype == 'Q':
                pbsquares = []
                # horizontal and vertical
                if threat.piece.piecetype == 'R' or threat.piece.piecetype == 'Q':

                    # if they are on the same rank...
                    if threat.i == king_square.i:
                        if threat.j > king_square.j:
                            upper = threat.j
                            lower = king_square.j
                        else:
                            upper = king_square.j
                            lower = threat.j

                        # loops through all squares between the threatening piece and the king
                        for x in range(lower + 1, upper):
                            pbsquares.append(self[threat.i, x])

                    # if they are on the same file...
                    elif threat.j == king_square.j:
                        if threat.i > king_square.i:
                            upper = threat.i
                            lower = king_square.i
                        else:
                            upper = king_square.i
                            lower = threat.i

                        # loops through all squares between the threatening piece and the king
                        for x in range(lower + 1, upper):
                            pbsquares.append(self[x, threat.j])

                # diagonal
                if threat.piece.piecetype == 'B' or threat.piece.piecetype == 'Q':

                    delta_i = threat.i - king_square.j
                    delta_j = threat.j - king_square.j

                    # this is the number of squares diagonally inbetween the threat and the king
                    num_between = abs(delta_i) - 1

                    # threat is positive i positive j compared to king
                    if delta_i > 0 < delta_j:
                        for x in range(num_between):
                            pbsquares.append(self[threat.i - x, threat.j - x])

                    # threat is negative i positive j compared to king
                    elif delta_i < 0 < delta_j:
                        for x in range(num_between):
                            pbsquares.append(self[threat.i + x, threat.j - x])

                    # threat is negative i negative j compared to king
                    elif delta_i < 0 > delta_j:
                        for x in range(num_between):
                            pbsquares.append(self[threat.i + x, threat.j + x])

                    # threat is positive i negative j compared to king
                    elif delta_i > 0 > delta_j:
                        for x in range(num_between):
                            pbsquares.append(self[threat.i - x, threat.j + x])

                # if any of the possible blocking squares (pbsquares) are blockable, returns false
                for pbsquare in pbsquares:

                    # this checks if a pawn can block the threat by moving forward (ie the "capture" parameter is False)
                    pawn = Pawn.find(self, pbsquare, player, False, errors=False)
                    if isinstance(pawn, Pawn):
                        return False

                    # this is a list of pieces that threaten the possible blocking squares
                    # possible blocking threats (pbthreats)
                    pbthreats = self.threats_on(pbsquare, 1 - player)
                    if len(pbthreats) != 0:

                        # kings and pawns need to be excluded from this list:
                        #   - kings can't block a check
                        #   - pawns can't block a check by capturing
                        for square in pbthreats:
                            if square.piece.piecetype != 'P' and square.piece.piecetype != 'K':
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
        for rank in self:
            for square in rank:
                if square.piece is not None and square.piece.color == player and square.piece.can_move(square, self):
                    return False

        return True

    @staticmethod
    def get_coords(c_notation):
        """
        Converts chess notation (e.g., 'e4') into board coordinates `(i, j)`.

        :param c_notation: The chess notation string.
        :type c_notation: str
        :return: A tuple `(i, j)` where `i` is the row and `j` is the column.
        :rtype: tuple[int, int]
        """
        # changes file to j coord
        y = 0
        for i in range(8):
            if ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][i] == c_notation[0]:
                y = i
                break

        # changes row to i coord
        x = 8 - int(c_notation[1])

        return x, y

    @staticmethod
    def get_c_notation(i, j):
        """
        Converts board coordinates `(i, j)` into chess notation (e.g., 'e4').

        :param i: The row coordinate on the board.
        :type i: int
        :param j: The column coordinate on the board.
        :type j: int
        :return: The chess notation string.
        :rtype: str
        """
        # converts from coords to chess notation
        return ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'][j] + str(8 - i)

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

        :param board: The board in array form (8x8 list of `Square` objects).
        :type board: list[list[Square]]
        :return: A tuple containing the serialized board string and a string
            indicating move states for certain pieces.
        :rtype: tuple[str, str]
        """
        boardstring = ""
        moved = ['0', '0', '0', '0', '0', '0']
        for rank in board:
            for square in rank:
                if square.piece is not None:
                    boardstring += square.piece.piecetype + str(square.piece.color) + " "

                    if (square.i == 7 and square.j == 0) and square.piece.piecetype == 'R' and square.piece.moved:
                        moved[0] = "1"
                    elif (square.i == 7 and square.j == 4) and square.piece.piecetype == 'K' and square.piece.moved:
                        moved[1] = "1"
                    elif (square.i == 7 and square.j == 7) and square.piece.piecetype == 'R' and square.piece.moved:
                        moved[2] = "1"
                    elif (square.i == 0 and square.j == 0) and square.piece.piecetype == 'R' and square.piece.moved:
                        moved[3] = "1"
                    elif (square.i == 0 and square.j == 4) and square.piece.piecetype == 'K' and square.piece.moved:
                        moved[4] = "1"
                    elif (square.i == 0 and square.j == 7) and square.piece.piecetype == 'R' and square.piece.moved:
                        moved[5] = "1"

                else:
                    boardstring += "-- "

            boardstring = boardstring[:-1]
            boardstring += ";"
        boardstring = boardstring[:-1]
        moved = "".join(moved)

        return boardstring, moved


class Move:
    """
    Represents a move in a chess game.

    The `Move` class handles all aspects of parsing, validating, and storing information about a particular chess move.
    It provides support for special moves like castles, promotions, and en passant, while accounting for chess rules.

    :ivar piece: The piece being moved during this move.
    :type piece: Piece or None
    :ivar prev: The `Square` from which the piece is moved.
    :type prev: Square or None
    :ivar to: The `Square` to which the piece is moved.
    :type to: Square or None
    :ivar castle: Indicates the type of castling performed ('K' for king-side, 'Q' for queen-side,
        or `None` if this is not a castling move).
    :type castle: str or None
    :ivar promotion: Indicates the piece type that a pawn is being promoted to, if applicable. Possible values
        are 'R', 'N', 'B', 'Q', or `None` if the move is not a promotion.
    :type promotion: str or None
    :ivar en: Indicates whether this move is an en passant capture.
    :type en: bool
    """
    def __init__(self, move, player, board):
        """
        Initializes a move object based on the input move command, player, and the board.

        This method processes standard notation for chess moves, determines the piece being moved, its starting
        and destination squares, as well as any special characteristics of the move (e.g., castling, promotion,
        or en passant).

        :param move: The move command in standard chess notation, e.g., 'e4', 'Nf3', '0-0', or 'axb8Q'.
        :type move: str
        :param player: The player making the move (0 for white, 1 for black).
        :type player: int
        :param board: The board on which the move is executed.
        :type board: Board
        :raises ChessError.PromotionError: If an invalid promotion is attempted or a promotion is required.
        :raises ChessError.InvalidCastleError: If an invalid castling move is attempted.
        :raises ChessError.PieceNotFoundError: If no eligible piece is found for the move.
        :raises ChessError.MultiplePiecesFoundError: If more than one matching piece is found.
        :raises ChessError.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises ChessError.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises ChessError.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        piece = None
        prev = None
        to = None
        castle = None
        promotion = None
        en = False

        # regular movement (not castling)
        if move != "0-0" and move != "0-0-0":

            if move[0] in ['R', 'N', 'B', 'Q', 'K', 'P']:

                if move[0] == 'P' and move[-1] in ['R', 'N', 'B', 'Q']:
                    promotion = move[-1]
                    coords = board.get_coords(move[-3:-1])

                    # makes sure the player cannot promote with being on the opponent's back row
                    if coords[0] != (0 if player == 0 else 7):
                        raise ChessError.PromotionError(invalid_promotion=True)

                else:
                    coords = board.get_coords(move[-2:])

                # gets the i-j coords for where the piece is moving to
                i, j = coords
                to = board[i, j]
                file_limit, rank_limit = None, None
                capture = False

                # checks if there is a file limit, rank limit, or capture
                for char in (move[1:-3] if (move[0] == 'P' and promotion is not None) else move[1:-2]):
                    if char in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']:
                        file_limit = char
                        continue
                    elif char in ['1', '2', '3', '4', '5', '6', '7', '8']:
                        rank_limit = char
                        continue
                    elif char == 'x':
                        capture = True
                        continue

                try:
                    if move[0] == 'R':
                        square = Rook.find(board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit)
                    elif move[0] == 'N':
                        square = Knight.find(board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit)
                    elif move[0] == 'B':
                        square = Bishop.find(board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit)
                    elif move[0] == 'Q':
                        square = Queen.find(board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit)
                    elif move[0] == 'K':
                        square = King.find(board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit)
                    elif move[0] == 'P':
                        try:
                            square = Pawn.find(board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit)
                        except ChessError.NothingToCaptureError:
                            square = Pawn.find(board, to, player, capture, en=True, file_limit=file_limit, rank_limit=rank_limit)
                            en = True

                except ChessError.ChessError as e:
                    raise e

                else:
                    piece = square.piece
                    prev = square

                    # makes sure the player cannot move a pawn to opponent's back rank without promoting
                    if piece.piecetype == 'P' and i == (0 if player == 0 else 7) and promotion is None:
                        raise ChessError.PromotionError(need_promotion=True)


            # pawn exclusive movement
            elif move[0] in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']:
                file_limit = move[0]

                if move[-1] in ['R', 'N', 'B', 'Q']:
                    promotion = move[-1]
                    coords = Board.get_coords(move[-3:-1])

                    # makes sure the player cannot promote with being on the opponent's back row
                    if coords[0] != (0 if player == 0 else 7):
                        raise ChessError.PromotionError(invalid_promotion=True)

                else:
                    coords = Board.get_coords(move[-2:])

                i, j = coords
                to = board[i, j]

                capture = True if move[1] == 'x' else False

                try:
                    square = Pawn.find(board, to, player, capture, file_limit=file_limit)
                except ChessError.NothingToCaptureError:
                    square = Pawn.find(board, to, player, capture, en=True, file_limit=file_limit)
                    en = True

                else:
                    piece = square.piece
                    prev = square

                    # makes sure the player cannot move a pawn to opponent's back rank without promoting
                    if i == (0 if player == 0 else 7) and promotion is None:
                        raise ChessError.PromotionError(need_promotion=True)

        # castling
        else:

            x = 7 if player == 0 else 0

            piece = board.find_king(player).piece

            # king side castle
            if move == "0-0":

                prev, to = board[x, 4], board[x, 6]
                castle = 'K'

                if not piece.can_castle(board, 'K'):
                    raise ChessError.InvalidCastleError('K')

            # queen side castle
            else:

                prev, to = board[x, 4], board[x, 2]
                castle = 'Q'

                if not piece.can_castle(board, 'Q'):
                    raise ChessError.InvalidCastleError('Q')

        self.piece = piece
        self.prev = prev
        self.to = to
        self.castle = castle
        self.promotion = promotion
        self.en = en

    @staticmethod
    def is_valid_c_notation(movename):
        """
        Validates whether the given chess move adheres to algebraic notation.
        See https://en.wikipedia.org/wiki/Algebraic_notation_(chess) for more information on algebraic notation.

        This method checks whether the `movename` string corresponds to a valid chess move in accordance
        with standard chess rules (e.g., proper format for regular moves, promotions, castling, and captures).

        This method does NOT check if the move is legal or not, but rather if the move syntax is correct.

        :param movename: The move name to validate (e.g., 'e2e4', 'Nf3', '0-0').
        :type movename: str
        :return: `True` if the move is valid, otherwise `False`.
        :rtype: bool

        **Rules for a valid move string**:
        - Must be at least two characters in length. (a pawn move)
        - Can end with '+' (check) or '#' (checkmate) symbols, but this is never required.
        - Castling must be in the format '0-0' (king-side) or '0-0-0' (queen-side).
        - Must contain valid chess piece designations ('R', 'N', 'B', 'Q', 'K', or 'P'), if specified.
        - Must use valid ranks ('1' to '8') and files ('a' to 'h').
        - Captures are marked with 'x', e.g., 'Nxe5'.
        """
        # any valid move must be at least 2 in length
        if len(movename) < 2:
            return False

        # cuts off check or checkmate symbol from tail end
        if '+' == movename[-1]:
            movename = movename[:-1]
        if '#' == movename[-1]:
            movename = movename[-1]

        # if the move is a castling move, returns true
        if movename == "0-0" or movename == "0-0-0":
            return True

        # if not a pawn (or using traditional notation with 'P')...
        if movename[0] in ['R', 'N', 'B', 'Q', 'K', 'P']:
            # temp is everything that isn't square location or piecetype
            temp = movename[1:-2]

        # if a pawn...
        elif movename[0] in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']:

            # if there is a promotion, it is removed from the string
            if movename[-1] in ['R', 'N', 'B', 'Q']:
                movename = movename[:-1]

            # if there is a capture sign as the second letter...
            if movename[1] == 'x':
                # temp is everything that isn't square location or piecetype
                temp = movename[1:-2]

            # otherwise, temp is the entire movename
            else:
                temp = movename

        # if the first character is not valid, returns false
        else:
            return False

        # makes sure the last 2 characters are a square
        if movename[-2] not in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'] or \
           movename[-1] not in ['1', '2', '3', '4', '5', '6', '7', '8']:
            return False

        if len(temp) == 0:
            return True

        # if temp is one character and is not a valid character, returns false
        elif len(temp) == 1:
            if temp not in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', '1', '2', '3', '4', '5', '6', '7', '8', 'x']:
                return False

        # if temp is two characters...
        elif len(temp) == 2:

            # if temp is a capture and the first letter of temp is not valid, returns false
            if 'x' == temp[1] and temp[0] not in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', '1', '2', '3', '4', '5', '6',
                                                  '7', '8']:
                return False

            # if temp is a specification move and uses invalid characters, returns false
            if temp[0] not in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'] or \
               temp[1] not in ['1', '2', '3', '4', '5', '6', '7', '8']:
                return False

        # if temp is three characters...
        elif len(temp) == 3:

            # if temp is a specification and capture move and uses invalid specification, returns false
            if temp[0] not in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'] or \
               temp[1] not in ['1', '2', '3', '4', '5', '6', '7', '8'] or \
               temp[2] != 'x':
                return False

        # if temp is more than 3 characters, it is invalid
        else:
            return False

        # if all checks are passed, it returns true
        return True
