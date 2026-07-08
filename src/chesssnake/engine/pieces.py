"""Chess pieces: the `Piece` base class and the six concrete piece types."""

from .errors import (
    CaptureOwnPieceError,
    MultiplePiecesFoundError,
    NothingToCaptureError,
    PieceNotFoundError,
    PieceOnSquareError,
)


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
        :raises PieceNotFoundError: If no eligible rook is found for the move.
        :raises MultiplePiecesFoundError: If more than one matching rook is found.
        :raises NothingToCaptureError: If no opposing piece exists on the target square.
        :raises CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
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
                raise PieceNotFoundError(square, 'R')
            else:
                return None

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise PieceOnSquareError(square, True)
                    else:
                        raise PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise MultiplePiecesFoundError(square, found)
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
        :raises PieceNotFoundError: If no eligible Knight is found for the move.
        :raises MultiplePiecesFoundError: If more than one matching Knight is found.
        :raises NothingToCaptureError: If no opposing piece exists on the target square.
        :raises CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
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
                raise PieceNotFoundError(square, 'N')
            else:
                return None

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise PieceOnSquareError(square, True)
                    else:
                        raise PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise MultiplePiecesFoundError(square, found)
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
        :raises PieceNotFoundError: If no eligible Bishop is found for the move.
        :raises MultiplePiecesFoundError: If more than one matching Bishop is found.
        :raises NothingToCaptureError: If no opposing piece exists on the target square.
        :raises CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
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
                raise PieceNotFoundError(square, 'B')
            else:
                return None

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise PieceOnSquareError(square, True)
                    else:
                        raise PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise MultiplePiecesFoundError(square, found)
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
        :raises PieceNotFoundError: If no eligible Queen is found for the move.
        :raises MultiplePiecesFoundError: If more than one matching Queen is found.
        :raises NothingToCaptureError: If no opposing piece exists on the target square.
        :raises CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
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
                raise PieceNotFoundError(square, 'Q')
            else:
                return None

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise PieceOnSquareError(square, True)
                    else:
                        raise PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise MultiplePiecesFoundError(square, found)
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
        :raises PieceNotFoundError: If no King is found on the board matching the criteria.
        :raises NothingToCaptureError: If opponent's piece exists on the target square.
        :raises CaptureOwnPieceError: If an allied piece exists on the target square.
        :raises PieceOnSquareError: If an invalid move is attempted, such as landing
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
                raise PieceNotFoundError(square, 'K')
            else:
                return found

        elif len(found) == 1:

            if errors:
                # if the player is capturing, there must be an opponent's piece on the square
                if capture:
                    if square.piece is None:
                        raise NothingToCaptureError(square)
                    elif square.piece.color == color:
                        raise CaptureOwnPieceError(square)

                # this makes sure the player cannot move a piece onto a square that already has a piece on it
                elif square.piece is not None:
                    if square.piece.color == color:
                        raise PieceOnSquareError(square, True)
                    else:
                        raise PieceOnSquareError(square, False)

            return found[0]

        else:
            if errors:
                raise MultiplePiecesFoundError(square, found)
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

        If the `errors` flag is set to `True`, exceptions are raised for invalid moves.
        Otherwise, invalid moves will return `None` or an empty list.

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
        :raises PieceNotFoundError: If no Pawn is found on the board matching the criteria.
        :raises NothingToCaptureError: If no opponent's piece is present to capture on the target square.
        :raises CaptureOwnPieceError: If an allied piece is found on the target square.
        :raises MultiplePiecesFoundError: If several Pawns match, making the move ambiguous.
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
                        raise PieceOnSquareError(square, True)
                    else:
                        raise PieceOnSquareError(square, False)

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
                    raise PieceNotFoundError(square, 'P')
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
                        raise PieceOnSquareError(square, True)
                    else:
                        raise PieceOnSquareError(square, False)

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
                    raise PieceNotFoundError(square, 'P')
                else:
                    return None

            elif errors:
                raise PieceNotFoundError(square, 'P')
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
                    raise PieceNotFoundError(square, 'P')
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
                            raise NothingToCaptureError(square)

                    else:
                        raise NothingToCaptureError(square)

                elif square.piece is not None and square.piece.color == color and errors:
                    raise CaptureOwnPieceError(square)

                return found[0]

            else:
                if errors:
                    raise MultiplePiecesFoundError(square, found)
                else:
                    return found
