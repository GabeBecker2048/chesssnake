class ChessError(Exception):
    def __init__(self, message):
        super().__init__(message)


class InvalidNotationError(ChessError):
    def __init__(self, user_input):
        super().__init__(f"\"{user_input}\" is not in valid algebraic notation")


class PieceOnSquareError(ChessError):
    def __init__(self, square, is_same_color):
        if is_same_color:
            super().__init__(f"There is already a piece on {square.c_notation}")
        else:
            super().__init__(f"There is already a piece on {square.c_notation} (possible failure to specify a capture)")


class NothingToCaptureError(ChessError):
    def __init__(self, square):
        super().__init__(f"There is not a piece to capture on {square.c_notation}")


class CaptureOwnPieceError(ChessError):
    def __init__(self, square):
        super().__init__(f"The piece on {square.c_notation} belongs to the player. Players cannot capture their own pieces")


class PieceNotFoundError(ChessError):
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

        message = f"Multiple {piece}s can move to {square.c_notation}. The {piece}s detached are:"
        for psquare in found:
            message += f"\n\ton {psquare.c_notation}"

        super().__init__(message)


class PromotionError(ChessError):
    def __init__(self, invalid_promotion=False, need_promotion=False):
        if invalid_promotion:
            super().__init__("You cannot promote unless you are on your opponent's back rank")
        elif need_promotion:
            super().__init__("You cannot move a pawn to your opponent's back rank without promoting")
        else:
            super().__init__("Promotion Error")


class InvalidCastleError(ChessError):
    def __init__(self, side):
        if side == 'K':
            super().__init__("You cannot kingside castle")
        elif side == 'Q':
            super().__init__("You cannot queenside castle")
        else:
            super().__init__("You cannot castle that way")


class MoveIntoCheckError(ChessError):
    def __init__(self):
        super().__init__("Making that move would put you in check")


class DrawWrongTurnError(ChessError):
    def __init__(self):
        super().__init__("You can only offer a draw when it is your turn")


class DrawAlreadyOfferedError(ChessError):
    def __init__(self):
        super().__init__("You have already offered a draw")


class DrawNotOfferedError(ChessError):
    def __init__(self):
        super().__init__("You have not been offered a draw")
