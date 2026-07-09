from . import errors as ChessError
from .board import Board
from .enums import Color, GameStatus
from .image import render_board
from .move import Move


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
    :ivar turn: Whose turn it is, as a :class:`~chesssnake.engine.enums.Color`.
        Prefer the :attr:`to_move` accessor in user code.
    :type turn: Color
    :ivar draw: Which color has an open draw offer (a
        :class:`~chesssnake.engine.enums.Color`), or ``None`` if none is active.
        Prefer the :attr:`draw_offered_by` accessor in user code.
    :type draw: Color or None
    :ivar last_move: The most recent :class:`~chesssnake.engine.move.Move`, or
        ``None`` before any move. Used to highlight the board on :meth:`render`.
    :type last_move: Move or None

    Intention-revealing accessors (prefer these over the raw ints/enums above):
    :attr:`is_over`, :attr:`result`, :attr:`winner`, :attr:`to_move`,
    :attr:`draw_offered_by`.
    """

    def __init__(
        self,
        white_id: int = 0,
        black_id: int = 1,
        group_id: int = 0,
        white_name: str = "",
        black_name: str = "",
        board: "Board | None" = None,
        turn: int = 0,
        draw: "int | None" = None,
    ):
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
        self.board = Board() if board is None else board
        self.turn = Color(turn)
        self.draw: Color | None = Color(draw) if draw is not None else None
        self.last_move: Move | None = None

    def __str__(self):
        """
        Provides a string representation of the current chessboard state.

        :return: A string representation of the board.
        :rtype: str
        """
        return str(self.board)

    # --- state accessors ---------------------------------------------------

    @property
    def to_move(self) -> Color:
        """The :class:`Color` whose turn it is to move."""
        return self.turn

    @property
    def is_over(self) -> bool:
        """``True`` if the game has ended (by checkmate or draw)."""
        return self.board.status != GameStatus.IN_PLAY

    @property
    def result(self) -> GameStatus:
        """The current :class:`GameStatus` (``IN_PLAY``, ``CHECKMATE``, or ``DRAW``)."""
        return self.board.status

    @property
    def winner(self) -> "Color | None":
        """The winning :class:`Color` on checkmate, or ``None`` if drawn/ongoing."""
        if self.board.status == GameStatus.CHECKMATE:
            # the mating side is the one that just moved — the opposite of to_move
            return self.turn.opponent
        return None

    @property
    def draw_offered_by(self) -> "Color | None":
        """The :class:`Color` with an open draw offer, or ``None`` if there is none."""
        return self.draw

    def is_players_turn(self, player_id: int) -> bool:
        """
        Checks whether it is a given player's turn to move.

        :param player_id: The ID of the player whose turn is being checked.
        :type player_id: int
        :return: `True` if it is the player's turn, otherwise `False`.
        :rtype: bool
        """
        if (self.turn == Color.WHITE and player_id == self.wid) or (self.turn == Color.BLACK and player_id == self.bid):
            return True
        else:
            return False

    def move(self, move: str) -> Move:
        """
        Executes a chess move if it is the active player's turn.

        Validates the move, applies it to the board, and passes the turn to the
        other player. Rendering is separate — use :meth:`render` or :meth:`save`.

        :param move: The move to execute, in standard chess notation (e.g., "e4").
        :type move: str
        :return: The :class:`~chesssnake.engine.move.Move` that was played.
        :rtype: Move
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
        if not Move.is_valid_c_notation(move):
            raise ChessError.InvalidNotationError(move)

        if self.board.status != GameStatus.IN_PLAY:
            raise ChessError.GameOverError()

        m = self.board.move(move, self.turn)
        self.last_move = m
        self.turn = self.turn.opponent  # Changes whose turn it is
        return m

    def render(self):
        """
        Render the current board to an image (both orientations, last move highlighted).

        :return: A `PIL.Image` of the board.
        :rtype: PIL.Image
        """
        return render_board(self.board, self.wname, self.bname, self.last_move)

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
        if self.board.status != GameStatus.IN_PLAY:
            raise ChessError.GameOverError()

        if (self.draw == Color.WHITE and player_id == self.wid) or (self.draw == Color.BLACK and player_id == self.bid):
            raise ChessError.DrawAlreadyOfferedError()
        elif (self.draw == Color.BLACK and player_id == self.wid) or (
            self.draw == Color.WHITE and player_id == self.bid
        ):
            self.draw_accept(player_id)
        elif not self.is_players_turn(player_id):
            raise ChessError.DrawWrongTurnError()

        self.draw = Color.WHITE if player_id == self.wid else Color.BLACK

    def draw_accept(self, player_id: int):
        """
        Accepts an existing draw offer and ends the game.

        If both players agree to a draw, this method sets the game's status to a stalemate (draw).

        :param player_id: The ID of the player accepting the draw.
        :type player_id: int
        :raises ChessError.GameOverError: If the game is over (i.e., the game has ended).
        :raises ChessError.DrawNotOfferedError: If no draw offer exists to accept.
        """
        if self.board.status != GameStatus.IN_PLAY:
            raise ChessError.GameOverError()

        if (
            (self.draw == Color.WHITE and player_id == self.wid)
            or (self.draw == Color.BLACK and player_id == self.bid)
            or self.draw is None
        ):
            raise ChessError.DrawNotOfferedError()

        self.board.status = GameStatus.DRAW  # Set game status to draw

    def draw_decline(self, player_id: int):
        """
        Declines an active draw offer.

        Removes any existing draw offer from the game state.

        :param player_id: The ID of the player declining the draw.
        :type player_id: int
        :raises ChessError.GameOverError: If the game is over (i.e., the game has ended).
        :raises ChessError.DrawNotOfferedError: If no draw offer exists to decline.
        """
        if self.board.status != GameStatus.IN_PLAY:
            raise ChessError.GameOverError()

        if (
            (self.draw == Color.WHITE and player_id == self.wid)
            or (self.draw == Color.BLACK and player_id == self.bid)
            or self.draw is None
        ):
            raise ChessError.DrawNotOfferedError()

        self.draw = None

    def save(self, image_fp: str):
        """
        Saves the current state of the chessboard as a PNG image file.

        :param image_fp: The file path where the board image will be saved.
        :type image_fp: str
        """
        self.render().save(image_fp)
