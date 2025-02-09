from . import Chess
from . import ChessImg
from . import ChessError


class Game:
    """
    Manages the logic and state of a chess game between two players.

    The `Game` class encapsulates the main gameplay functionalities, including managing player turns,
    handling moves, offering/accepting/declining draws, and saving board states as images. It acts as
    the central controller of the chess game, interacting with other components like `Board` and `Move`.

    :ivar gid: The group ID.
    :type gid: int
    :ivar wid: The ID of the player playing as white.
    :type wid: int
    :ivar bid: The ID of the player playing as black.
    :type bid: int
    :ivar wname: The name of the player playing as white.
    :type wname: str
    :ivar bname: The name of the player playing as black.
    :type bname: str
    :ivar board: The chess board used in the game, represented as a `Board` object.
    :type board: Board
    :ivar turn: Keeps track of whose turn it is (0 for white, 1 for black).
    :type turn: int
    :ivar draw: Indicates the draw offer state:
        - 0: White has offered a draw.
        - 1: Black has offered a draw.
        - `None`: No draw offer is currently active.
    :type draw: int or None
    """

    def __init__(self, white_id: int = 0, black_id: int = 1, group_id: int = 0, white_name: str = '', black_name: str = ''):
        """
        Initializes a new chess game.

        This method creates a new game instance for the given players, initializes a blank chessboard,
        and sets default parameters for the game's turn and draw status.

        :param white_id: ID for the player playing as white. Default is 0.
        :type white_id: int
        :param black_id: ID for the player playing as black. Default is 1.
        :type black_id: int
        :param group_id: Group or game ID. Default is 0.
        :type group_id: int
        :param white_name: Name of the player playing as white. Default is an empty string.
        :type white_name: str
        :param black_name: Name of the player playing as black. Default is an empty string.
        :type black_name: str
        """
        self.gid = group_id
        self.wid = white_id
        self.bid = black_id
        self.wname = white_name
        self.bname = black_name
        self.board = Chess.Board()
        self.turn = 0
        self.draw = 0

    def __str__(self):
        """
        Provides a string representation of the current chessboard state.

        :return: A string representation of the board.
        :rtype: str
        """
        return str(self.board)

    def is_players_turn(self, player_id: int) -> bool:
        """
        Checks whether it is a given player's turn to move.

        :param player_id: The ID of the player whose turn is being checked.
        :type player_id: int
        :return: `True` if it is the player's turn, otherwise `False`.
        :rtype: bool
        """
        if (self.turn == 0 and player_id == self.wid) or (self.turn == 1 and player_id == self.bid):
            return True
        else:
            return False

    def move(self, move: str, img: bool = False, save: str = None):
        """
        Executes a chess move if it is the active player's turn.

        This method validates the move, applies it to the board, and changes the turn to the other player.
        Optionally, it can generate a visual representation of the board as an image or save it as a PNG file.

        :param move: The move to execute, in standard chess notation (e.g., "e4").
        :type move: str
        :param img: If `True`, returns a `PIL.Image` object representing the board. Default is `False`.
        :type img: bool
        :param save: File path to save the board image as a PNG. If provided, it implies `img=True`.
        :type save: str
        :return: None or a `PIL.Image` object if `img=True` or `save` is specified.
        :rtype: None or PIL.Image
        :raises ChessError.InvalidNotationError: If the move is not in standard chess notation.
        :raises ChessError.GameOverError: If the game is over (i.e., the game has ended).
        :raises ChessError.MoveIntoCheckError: If the move puts the player in check.
        :raises ChessError.PromotionError: If an invalid promotion is attempted or a promotion is required.
        :raises ChessError.InvalidCastleError: If an invalid castling move is attempted.
        :raises ChessError.PieceNotFoundError: If no eligible piece is found for the move.
        :raises ChessError.MultiplePiecesFoundError: If more than one matching piece is found.
        :raises ChessError.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises ChessError.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises ChessError.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        if not Chess.Move.is_valid_c_notation(move):
            raise ChessError.InvalidNotationError(move)

        if self.board.status != 0:
            raise ChessError.GameOverError()

        m = self.board.move(move, self.turn)
        self.turn = 1 - self.turn  # Changes whose turn it is

        if img or save:
            image = ChessImg.img(self.board, self.wname, self.bname, m)
            if save:
                image.save(save)
            return image
        return None

    def draw_offer(self, player_id: int):
        """
        Offers a draw in the game.

        This method records the player's draw offer.
        If the opponent has already offered a draw, this method will accept the draw and end the game.

        :param player_id: The ID of the player offering the draw.
        :type player_id: int
        :raises ChessError.GameOverError: If the game is over (i.e., the game has ended).
        :raises ChessError.DrawAlreadyOfferedError: If the same player has already made a draw offer.
        :raises ChessError.DrawWrongTurnError: If the player offers a draw out of turn.
        """
        if self.board.status != 0:
            raise ChessError.GameOverError()

        if (self.draw == 0 and player_id == self.wid) or (self.draw == 1 and player_id == self.bid):
            raise ChessError.DrawAlreadyOfferedError()
        elif (self.draw == 1 and player_id == self.wid) or (self.draw == 0 and player_id == self.bid):
            self.draw_accept(player_id)
        elif not self.is_players_turn(player_id):
            raise ChessError.DrawWrongTurnError()

        self.draw = 0 if player_id == self.wid else 1

    def draw_accept(self, player_id: int):
        """
        Accepts an existing draw offer and ends the game.

        If both players agree to a draw, this method sets the game's status to a stalemate (draw).

        :param player_id: The ID of the player accepting the draw.
        :type player_id: int
        :raises ChessError.GameOverError: If the game is over (i.e., the game has ended).
        :raises ChessError.DrawNotOfferedError: If no draw offer exists to accept.
        """
        if self.board.status != 0:
            raise ChessError.GameOverError()

        if (self.draw == 0 and player_id == self.wid) or (
                self.draw == 1 and player_id == self.bid) or self.draw is None:
            raise ChessError.DrawNotOfferedError()

        self.board.status = 2  # Set game status to draw

    def draw_decline(self, player_id: int):
        """
        Declines an active draw offer.

        Removes any existing draw offer from the game state.

        :param player_id: The ID of the player declining the draw.
        :type player_id: int
        :raises ChessError.GameOverError: If the game is over (i.e., the game has ended).
        :raises ChessError.DrawNotOfferedError: If no draw offer exists to decline.
        """
        if self.board.status != 0:
            raise ChessError.GameOverError()

        if (self.draw == 0 and player_id == self.wid) or (
                self.draw == 1 and player_id == self.bid) or self.draw is None:
            raise ChessError.DrawNotOfferedError()

        self.draw = None

    def save(self, image_fp: str):
        """
        Saves the current state of the chessboard as a PNG image file.

        :param image_fp: The file path where the board image will be saved.
        :type image_fp: str
        """
        ChessImg.img(self.board, self.wname, self.bname).save(image_fp)
