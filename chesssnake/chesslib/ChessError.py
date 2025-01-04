class ChessError(Exception):
    """
    Represents an exception specific to errors occurring in chess-related
    operations.

    Used to handle and distinguish errors within the chess logic or
    system-specific exceptions during gameplay or chess computation.
    """
    def __init__(self, message):
        super().__init__(message)


class InvalidNotationError(ChessError):
    """
    Exception raised for invalid chess algebraic notation input.

    This class represents an error thrown when the user provides input
    that does not conform to standard algebraic notation in chess.
    """
    def __init__(self, user_input):
        super().__init__(f"\"{user_input}\" is not in valid algebraic notation")


class PieceOnSquareError(ChessError):
    """
    Represents an error that occurs when a piece is already present on a specified
    square on the chessboard. This error can indicate either an attempt to place a piece
    on an occupied square or a possible failure to specify a capture if the pieces are
    of different colors
    (i.e. the player might have forgotten to specify a capture by adding an 'x' to their move).

    This exception handles cases where placement or movement of pieces violates the rules
    concerning square occupancy in chess games.
    """
    def __init__(self, square, is_same_color):
        if is_same_color:
            super().__init__(f"There is already a piece on {square.c_notation}")
        else:
            super().__init__(f"There is already a piece on {square.c_notation} (possible failure to specify a capture)")


class NothingToCaptureError(ChessError):
    """
    Represents an error that occurs when attempting to capture a piece on a
    square without a valid target.

    This exception indicates that a capture move has been attempted on a square
    where no piece is present.
    """
    def __init__(self, square):
        super().__init__(f"There is not a piece to capture on {square.c_notation}")


class CaptureOwnPieceError(ChessError):
    """
    Exception raised when a player attempts to capture their own piece.

    This exception indicates that a player is trying to make an invalid move
    by attempting to capture one of their own pieces.
    """
    def __init__(self, square):
        super().__init__(f"The piece on {square.c_notation} belongs to the player. Players cannot capture their own pieces")


class PieceNotFoundError(ChessError):
    """
    Raised when a specific chess piece cannot move to the designated square.

    This error specifically encapsulates the scenario where a chess piece of a
    given type (pawn, rook, knight, bishop, queen, or king) cannot move to the
    specified square. It provides a descriptive error message for debugging
    or informational purposes.
    """
    def __init__(self, square, piecetype):

        if piecetype == 'P':
            piece = "pawn"
        elif piecetype == 'R':
            piece = "rook"
        elif piecetype == 'N':
            piece = "knight"
        elif piecetype == 'B':
            piece = "bishop"
        elif piecetype == 'Q':
            piece = "queen"
        elif piecetype == 'K':
            piece = "king"
        else:
            piece = "unknown"

        super().__init__(f"No {piece}s can move to {square.c_notation}")


class MultiplePiecesFoundError(ChessError):
    """
    Represents an error that occurs when multiple chess pieces can move to the same
    destination square.

    This exception is raised when there are multiple valid moves for pieces of the
    same type to the same square, indicating ambiguity in the move notation. It
    provides detailed information about the conflicting pieces and their positions.
    """
    def __init__(self, square, found):

        piecetype = found[0].piece.piecetype

        if piecetype == 'P':
            piece = "pawn"
        elif piecetype == 'R':
            piece = "rook"
        elif piecetype == 'N':
            piece = "knight"
        elif piecetype == 'B':
            piece = "bishop"
        elif piecetype == 'Q':
            piece = "queen"
        elif piecetype == 'K':
            piece = "king"
        else:
            piece = "unknown"

        message = f"Multiple {piece}s can move to {square.c_notation}. The {piece}s are:"
        for psquare in found:
            message += f"\n\ton {psquare.c_notation}"

        super().__init__(message)


class PromotionError(ChessError):
    """
    Represents an error related to pawn promotion in a chess game.

    The class handles different promotion-related errors such as attempting
    promotion outside the opponent's back rank or failing to promote upon
    reaching the opponent's back rank.
    """
    def __init__(self, invalid_promotion=False, need_promotion=False):
        if invalid_promotion:
            super().__init__("You cannot promote unless you are on your opponent's back rank")
        elif need_promotion:
            super().__init__("You cannot move a pawn to your opponent's back rank without promoting")
        else:
            super().__init__("Promotion Error")


class InvalidCastleError(ChessError):
    """
    Represents an error that occurs when an invalid castling move is attempted
    in a chess game.

    This exception is raised when a player tries to perform a castling move
    that is either not allowed by the rules of the game or is attempted under
    invalid conditions.
    """
    def __init__(self, side):
        if side == 'K':
            super().__init__("You cannot kingside castle")
        elif side == 'Q':
            super().__init__("You cannot queenside castle")
        else:
            super().__init__("You cannot castle that way")


class MoveIntoCheckError(ChessError):
    """
    Exception raised when a chess move would place the player in check.

    This class represents a specific type of chess error that is triggered
    when a move is attempted which would cause the player's king to end
    up in check.
    """
    def __init__(self):
        super().__init__("Making that move would put you in check")


class DrawWrongTurnError(ChessError):
    """
    Represents an error raised when a player attempts to offer a draw
    outside their turn.

    This exception is used to enforce the game rule that a draw offer is only
    valid when it is a player's turn. This error helps ensure the rules of chess
    are adhered to during gameplay.
    """
    def __init__(self):
        super().__init__("You can only offer a draw when it is your turn")


class DrawAlreadyOfferedError(ChessError):
    """
    Represents an error raised when a player attempts to offer a draw after
    already having offered one.

    This error is used in the chess game logic to enforce the rule that a player
    cannot repeatedly offer a draw when it has already been proposed.
    """
    def __init__(self):
        super().__init__("You have already offered a draw")


class DrawNotOfferedError(ChessError):
    """
    Exception raised when a draw has not been offered in a chess game.

    This class is specifically used in the context of chess applications to indicate
    that an operation requiring a draw offer cannot proceed because no draw was offered.
    """
    def __init__(self):
        super().__init__("You have not been offered a draw")
