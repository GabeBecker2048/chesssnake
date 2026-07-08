"""The `Move`: parses one algebraic move against a board into concrete squares."""

from . import errors, notation
from .enums import PieceType
from .notation import FILES, RANKS
from .pieces import Bishop, King, Knight, Pawn, Queen, Rook


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
        :raises errors.PromotionError: If an invalid promotion is attempted or a promotion is required.
        :raises errors.InvalidCastleError: If an invalid castling move is attempted.
        :raises errors.PieceNotFoundError: If no eligible piece is found for the move.
        :raises errors.MultiplePiecesFoundError: If more than one matching piece is found.
        :raises errors.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises errors.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises errors.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        piece = None
        prev = None
        to = None
        castle = None
        promotion = None
        en = False

        # regular movement (not castling)
        if move != "0-0" and move != "0-0-0":
            if move[0] in "RNBQKP":
                if move[0] == "P" and move[-1] in "RNBQ":
                    promotion = move[-1]
                    coords = notation.get_coords(move[-3:-1])

                    # makes sure the player cannot promote with being on the opponent's back row
                    if coords[0] != (0 if player == 0 else 7):
                        raise errors.PromotionError(invalid_promotion=True)

                else:
                    coords = notation.get_coords(move[-2:])

                # gets the i-j coords for where the piece is moving to
                i, j = coords
                to = board[i, j]
                file_limit, rank_limit = None, None
                capture = False

                # checks if there is a file limit, rank limit, or capture
                for char in move[1:-3] if (move[0] == "P" and promotion is not None) else move[1:-2]:
                    if char in FILES:
                        file_limit = char
                        continue
                    elif char in RANKS:
                        rank_limit = char
                        continue
                    elif char == "x":
                        capture = True
                        continue

                try:
                    if move[0] == "R":
                        square = Rook.find_one(board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit)
                    elif move[0] == "N":
                        square = Knight.find_one(
                            board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit
                        )
                    elif move[0] == "B":
                        square = Bishop.find_one(
                            board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit
                        )
                    elif move[0] == "Q":
                        square = Queen.find_one(
                            board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit
                        )
                    elif move[0] == "K":
                        square = King.find_one(board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit)
                    elif move[0] == "P":
                        try:
                            square = Pawn.find_one(
                                board, to, player, capture, file_limit=file_limit, rank_limit=rank_limit
                            )
                        except errors.NothingToCaptureError:
                            square = Pawn.find_one(
                                board, to, player, capture, en=True, file_limit=file_limit, rank_limit=rank_limit
                            )
                            en = True

                except errors.ChessError as e:
                    raise e

                else:
                    piece = square.piece
                    prev = square

                    # makes sure the player cannot move a pawn to opponent's back rank without promoting
                    if piece.piecetype == PieceType.PAWN and i == (0 if player == 0 else 7) and promotion is None:
                        raise errors.PromotionError(need_promotion=True)

            # pawn exclusive movement
            elif move[0] in FILES:
                file_limit = move[0]

                if move[-1] in "RNBQ":
                    promotion = move[-1]
                    coords = notation.get_coords(move[-3:-1])

                    # makes sure the player cannot promote with being on the opponent's back row
                    if coords[0] != (0 if player == 0 else 7):
                        raise errors.PromotionError(invalid_promotion=True)

                else:
                    coords = notation.get_coords(move[-2:])

                i, j = coords
                to = board[i, j]

                capture = True if move[1] == "x" else False

                try:
                    square = Pawn.find_one(board, to, player, capture, file_limit=file_limit)
                except errors.NothingToCaptureError:
                    square = Pawn.find_one(board, to, player, capture, en=True, file_limit=file_limit)
                    en = True

                piece = square.piece
                prev = square

                # makes sure the player cannot move a pawn to opponent's back rank without promoting
                if i == (0 if player == 0 else 7) and promotion is None:
                    raise errors.PromotionError(need_promotion=True)

        # castling
        else:
            x = 7 if player == 0 else 0

            piece = board.find_king(player).piece

            # king side castle
            if move == "0-0":
                prev, to = board[x, 4], board[x, 6]
                castle = "K"

                if not piece.can_castle(board, "K"):
                    raise errors.InvalidCastleError("K")

            # queen side castle
            else:
                prev, to = board[x, 4], board[x, 2]
                castle = "Q"

                if not piece.can_castle(board, "Q"):
                    raise errors.InvalidCastleError("Q")

        self.piece = piece
        self.prev = prev
        self.to = to
        self.castle = castle
        self.promotion = promotion
        self.en = en

    # notation-syntax validation lives in notation.py; kept here as a facade
    is_valid_c_notation = staticmethod(notation.is_valid_c_notation)
