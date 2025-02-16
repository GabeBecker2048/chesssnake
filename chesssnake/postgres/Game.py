from .PSql_Utils import execute_psql, psql_db_init, initialize_connection_pool
from . import GameError
from ..chesslib.Game import Game as BaseGame
from ..chesslib import Chess

# TODO
# - Fix Challenges class. Everything in there is mess
#   - Challenge.challenge should be the "everything" function, and should create games if successful
#   - Need to check if game exists as well as if challenge exists
#   - Add proper error checking
# - Standardize dtypes in args and returns (either add them EVERYWHERE or NOWHERE!)
# - Docstrings need double checking, especially for possible errors. Both for Game and Challenges


def db_init(sql_creds=None, create_database=False):
    """
    Initializes the database environment by optionally creating the database, setting
    up a connection pool, and initializing the database schema. This function provides
    a streamlined way to prepare the database infrastructure for an application, ensuring
    all essential components are properly configured.

    If `create_database` is True, it attempts to create the database if it does not exist.
    Recommended only for first time setup. Requires appropriate permissions to create the database.

    If `sql_creds` is not provided, it attempts to read the database credentials from the
    following environment variables: `CHESSDB_CONN_STR`, or
    `CHESSDB_NAME`, `CHESSDB_USER`, `CHESSDB_PASS`, `CHESSDB_HOST`, and `CHESSDB_PORT`.
    see the chesssnake.postgres "Getting Started" for more details.

    :param sql_creds: Database credentials used to establish a connection.
    :type sql_creds: dict, optional
    :param create_database: Flag to indicate whether to create the database if it
        does not exist. Requires appropriate permissions.
    :type create_database: bool
    :return: None
    :raises GameError: If any errors occur during the database initialization steps.
    """
    try:
        # create the database if it doesn't exist (require proper permissions)
        if create_database:
            psql_db_init(sql_creds=sql_creds)

        # Initialize the connection pool with provided or environment credentials
        initialize_connection_pool(sql_creds=sql_creds)

        print("Database initialized successfully.")
    except Exception as e:
        raise GameError.GameError(f"Database initialization error:\n{str(e)}")


class Game(BaseGame):
    """
    Extends the functionality of the `Game` class from `chesssnake.chesslib` to include SQL database support.

    The `Game` class manages chess gameplay logic while adding functionality for game persistence and interaction with an PostgreSQL database.
    Games can be loaded, saved, and automatically updated in the database.

    :param white_id: ID of the player playing as white. Default is 0.
    :type white_id: int
    :param black_id: ID of the player playing as black. Default is 1.
    :type black_id: int
    :param group_id: Group or game ID. Default is 0.
    :type group_id: int
    :param white_name: Name of the white player. Default is an empty string ('').
    :type white_name: str
    :param black_name: Name of the black player. Default is an empty string ('').
    :type black_name: str
    :param sql: Whether to enable SQL support. Default is False.
    :type sql: bool
    :param auto_sql: Whether to automatically update the database after every state change. Default is False.
    :type auto_sql: bool
    """

    def __init__(self,
                 white_id: int=0,
                 black_id: int=1,
                 group_id: int=0,
                 white_name: str='',
                 black_name: str='',
                 sql: bool=True,
                 auto_sql: bool=False):
        """
        Initializes a new chess game and synchronizes with the SQL database if required.

        If `sql` or `auto_sql` is enabled, it checks the database for a game with the given IDs. If a game exists, it loads
        the data into memory. Otherwise, it creates a new record in the database and initializes the game in memory.

        :param white_id: ID of the player playing as white. Default is 0.
        :type white_id: int
        :param black_id: ID of the player playing as black. Default is 1.
        :type black_id: int
        :param group_id: Group or game ID. Default is 0.
        :type group_id: int
        :param white_name: Name of the white player. Default is an empty string ('').
        :type white_name: str
        :param black_name: Name of the black player. Default is an empty string ('').
        :type black_name: str
        :param sql: Whether to enable SQL support. Default is False.
        :type sql: bool
        :param auto_sql: Whether to automatically update the database after every state change. Default is False.
        :type auto_sql: bool
        """
        # Ensure IDs are the correct type
        if not isinstance(white_id, int) or not isinstance(black_id, int) or not isinstance(group_id, int):
            GameError.SQLIdError(white_id, black_id, group_id)

        # Validate IDs are within the allowed BIGINT range
        BIGINT_MIN = -9223372036854775808
        BIGINT_MAX = 9223372036854775807
        if not (BIGINT_MIN <= white_id <= BIGINT_MAX and
                BIGINT_MIN <= black_id <= BIGINT_MAX and
                BIGINT_MIN <= group_id <= BIGINT_MAX):
            raise GameError.SQLIdError(white_id, black_id, group_id)

        # if sql=True, then we check the database to see if a game exists
        ## if it exists, we load the sql data into memory
        ## if it doesn't, we create a blank game in the DB and load a new game into memory
        if sql or auto_sql:
            # Initialize or load game data
            game_data = self.sql_game_init(white_id, black_id, group_id, white_name, black_name)


        super().__init__(white_id,
                         black_id,
                         group_id,
                         white_name = game_data["wname"],
                         black_name = game_data["bname"],
                         board = game_data["board"],
                         draw = game_data["draw"])
        self.sql = sql
        self.auto_sql = auto_sql


    def move(self, move, img=False, save=None):
        """
        Executes a chess move if it is the active player's turn.

        This method validates the move, applies it to the board, and changes the turn to the other player.
        The move is validated and applied to the board, changing the turn. Optionally
        generates a visual representation of the board or saves it as a PNG file.
        Automatically updates the SQL database if `auto_sql` is enabled.

        :param move: The move to execute, in standard chess notation (e.g., "e4").
        :type move: str
        :param img: If `True`, returns a `PIL.Image` object representing the board. Default is `False`.
        :type img: bool
        :param save: File path to save the board image as a PNG. If provided, it implies `img=True`.
        :type save: str
        :return: None or a `PIL.Image` object if `img=True` or `save` is specified.
        :rtype: None or PIL.Image
        :raises ChessError.MoveIntoCheckError: If the move would put the player in check.
        :raises ChessError.PromotionError: If an invalid promotion is attempted or a promotion is required.
        :raises ChessError.InvalidCastleError: If an invalid castling move is attempted.
        :raises ChessError.PieceNotFoundError: If no eligible piece is found for the move.
        :raises ChessError.MultiplePiecesFoundError: If more than one matching piece is found.
        :raises ChessError.NothingToCaptureError: If no opposing piece exists on the target square.
        :raises ChessError.CaptureOwnPieceError: If a piece of the same color exists on the target square.
        :raises ChessError.PieceOnSquareError: If an allied or opponent’s piece occupies the target square improperly.
        """
        img = super().move(move, img=img, save=save)

        if self.auto_sql:
            self.update_db()
        return img


    def draw_offer(self, player_id):
        """
        Offers a draw in the current game.

        Updates the SQL database with the draw offer if `auto_sql` is enabled.
        If both players offer a draw, the game instantly ends in a stalemate.

        :param player_id: The ID of the player offering the draw.
        :type player_id: int
        :raises ChessError.DrawAlreadyOfferedError: If the same player has already made a draw offer.
        :raises ChessError.DrawWrongTurnError: If the player offers a draw out of turn.
        """
        super().draw_offer(player_id)
        if self.auto_sql:
            self.update_draw_status()


    def draw_accept(self, player_id):
        """
        Accepts the opponent's existing draw offer.

        Marks the game as a draw.

        :param player_id: The player accepting the draw offer.
        :type player_id: int
        :raises ChessError.DrawNotOfferedError: If no draw offer exists.
        """
        super().draw_accept(player_id)
        if self.auto_sql:
            self.update_draw_status()


    def draw_decline(self, player_id):
        """
        Declines an active draw request.

        Updates the game state, removing the draw request. Automatically updates the database if `auto_sql` is enabled.

        :param player_id: The player who declines the draw.
        :type player_id: int
        :raises ChessError.DrawNotOfferedError: If there is no draw request to decline.
        """
        super().draw_decline(player_id)
        if self.auto_sql:
            self.clear_draw_status()


    def end(self):
        """
        Checks if the game is over, either by draw or checkmate.
        If the game is over, removes it from the SQL database.

        :return: True if the game is over and deleted, False otherwise.
        :rtype: bool
        """
        if self.board.status != 0:
            self.sql_delete_game()
            return True
        return False


    def update_db(self):
        """
        Updates the database with the current game state.

        If SQL support is enabled (`sql` or `auto_sql`), updates the game's record in the database
        with the current board state, turn, draw status, and player information. This function is for when
        `sql` is True and `auto_sql` is False.
        """
        query = """
            UPDATE Games
            SET Board = %(board)s,
                Turn = %(turn)s,
                PawnMove = %(pawnmove)s,
                Draw = %(draw)s,
                Moved = %(moved)s,
                Status = %(status)s,
                WName = %(wname)s,
                BName = %(bname)s
            WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
        """
        disassembled_board = self.board.disassemble_board(self.board)
        params = {
            "board": disassembled_board[0],
            "turn": self.turn,
            "pawnmove": self.board.two_moveP.c_notation if self.board.two_moveP else None,
            "draw": self.draw,
            "moved": disassembled_board[1],
            "status": self.board.status,
            "wname": self.wname,
            "bname": self.bname,
            "group_id": self.gid,
            "white_id": self.wid,
            "black_id": self.bid,
        }
        execute_psql(query, params=params)


    def update_draw_status(self):
        """
        Updates the draw status in the database.
        """
        query = """
            UPDATE Games
            SET Draw = %(draw)s, Status = %(status)s
            WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
        """
        params = {"draw": self.draw, "status": self.board.status, "group_id": self.gid, "white_id": self.wid, "black_id": self.bid}
        execute_psql(query, params=params)


    def clear_draw_status(self):
        """
        Clears the draw status in the database.
        """
        query = """
            UPDATE Games
            SET Draw = NULL
            WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
        """
        params = {"group_id": self.gid, "white_id": self.wid, "black_id": self.bid}
        execute_psql(query, params=params)


    def sql_delete_game(self):
        """
        Deletes the specified game from the database.
        """
        query = """
            DELETE FROM Games
            WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
        """
        params = {"group_id": self.gid, "white_id": self.wid, "black_id": self.bid}
        execute_psql(query, params=params)


    @staticmethod
    def sql_game_init(white_id, black_id, group_id=0, white_name='', black_name=''):
        """
        Initializes or loads a game from the SQL database.

        If the specified players are not already in a game, a new record is created in the database.
        Otherwise, the existing game state is retrieved.

        :return: dict containing game data: board, turn, last pawn move, draw status, game status, and player names.
        :rtype: dict | None
        """
        query = """
            INSERT INTO Games (GroupId, WhiteId, BlackId, Board, Turn, PawnMove, Draw, Moved, Status, WName, BName)
            VALUES (%(group_id)s, %(white_id)s, %(black_id)s, %(board)s, %(turn)s, %(pawnmove)s, %(draw)s, %(moved)s, %(status)s, %(wname)s, %(bname)s)
            ON CONFLICT (GroupId, WhiteId, BlackId) DO NOTHING;

            SELECT * FROM Games WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
        """
        params = {
            "group_id" : group_id,
            "white_id" : white_id,
            "black_id" : black_id,
            "board"    : "R1 N1 B1 Q1 K1 B1 N1 R1;P1 P1 P1 P1 P1 P1 P1 P1;-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;"
                         "-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;P0 P0 P0 P0 P0 P0 P0 P0;R0 N0 B0 Q0 K0 B0 N0 R0",
            "turn"     : 0,
            "pawnmove" : None,
            "draw"     : None,
            "moved"    : "000000",
            "status"   : 0,
            "wname"    : white_name,
            "bname"    : black_name
        }
        game: execute_psql(query, params=params)[0]

        pawnmove = Chess.Square(game["pawnmove"][0], game["pawnmove"][1]) if game["pawnmove"] is not None else None
        boardarr = Chess.Board.assemble_board(game["board"], game["moved"])
        board = Chess.Board(board=boardarr, two_moveP=pawnmove)
        board.status = int(game["status"])

        return {
            "board"    : board,
            "turn"     : int(game["turn"]),
            "draw"     : int(game["draw"]) if game["draw"] is not None else None,
            "wname"    : game["wname"],
            "bname"    : game["bname"]
        }


    @staticmethod
    def psql_current_games(player_id: int, gid: int = 0):
        """
            Provides the list of current active games for a player from the SQL database.

            This method queries the database to find active games associated with the given player ID within the specified group.
            It determines opponents based on whether the player ID is set as WhiteId or BlackId in the database.

            :param player_id: The ID of the player for whom active games are being retrieved.
            :type player_id: int
            :param gid: The group ID for the games. Default is 0.
            :type gid: int
            :return: A list of IDs of opponents currently involved in active games with the given player.
            :rtype: list[int]
            """
        query = """
            WITH PlayerResult AS (
                SELECT 
                    CASE 
                        WHEN WhiteId = %s THEN BlackId
                        WHEN BlackId = %s THEN WhiteId
                        ELSE NULL
                    END AS OpponentId
                FROM Games
                WHERE GroupId = %s
            )
            SELECT OpponentId
            FROM PlayerResult
            WHERE OpponentId IS NOT NULL;
            """
        params = (player_id, player_id, gid)
        games = execute_psql(query, params=params)
        games = [g['OpponentId'] for g in games]
        return games


    @staticmethod
    def psql_game_exists(player1: int, player2: int, gid: int = 0):
        """
            Checks if a game already exists between two players in the database.

            :param player1: The ID of the first player.
            :type player1: int
            :param player2: The ID of the second player.
            :type player2: int
            :param gid: The ID of the group in which the players are playing.
            :type gid: int
            :return: Dict of player IDs with keys "WhiteID" and "BlackID" if the game exists, otherwise None.
            :rtype: dict | None
            """
        query = """
                SELECT WhiteId, BlackId 
                FROM Games 
                WHERE GroupId = %s AND (
                    (WhiteId = %s AND BlackID = %s) OR 
                    (WhiteId = %s AND BlackID = %s)
                )
            """
        params = (gid, player1, player2, player2, player1)
        games = execute_psql(query, params=params)

        if games:
            return games[0]

        return None


class Challenge:
    """
    SQL wrapper for challenges recorded in the `Challenges` PostgreSQL table.

    Allows issuing, validating, and deleting game challenges between players.

    Currently only supports databases will envs for database creds.
    """
    @staticmethod
    def challenge(challenger=0, opponent=1, gid=0):
        """
        Issues a chess game challenge between two players.

        Validates that no active game or challenge exists between the players before creating a new challenge.
        If a reciprocal challenge exists, the challenge is accepted, and it proceeds to game creation.

        :param challenger: ID of the player making the challenge.
        :type challenger: int
        :param opponent: ID of the player being challenged.
        :type opponent: int
        :param gid: Group ID. Default is 0.
        :type gid: int
        :raises GameError.ChallengeError: If the challenge cannot be created.
        """

        if challenger == opponent:
            raise GameError.ChallengeError("You can't challenge yourself, silly")

        # checks if they are already in a game
        if Game.psql_game_exists(gid, challenger, opponent):
            raise GameError.ChallengeError(f"There is an unresolved game between {challenger} and {opponent} already!")

        # check if the challenge exists already
        challenge = Challenge.exists(challenger, opponent, gid)

        if challenge is None:
            Challenge.create_challenge(challenger, opponent, gid)
            print("Challenge created Successfully")
            return False

        elif challenger == challenge["challenger"]:
            raise GameError.ChallengeError(f"You have already challenged {opponent}! You must wait for them to accept")

        # if the challenge exists and is valid, we delete the challenge in the
        Challenge.delete_challenge(challenger, opponent, gid)

    # if the challenge exists, returns the challenger id and the challenge id in that order
    # otherwise, returns False
    @staticmethod
    def exists(player1, player2, gid=0):
        """
        Checks if a challenge exists between two players.

        :param player1: First player ID.
        :type player1: int
        :param player2: Second player ID.
        :type player2: int
        :param gid: Group ID. Default is 0.
        :type gid: int
        :return: True if a challenge exists. Otherwise, False.
        :rtype: bool
        """
        challenges = execute_psql(f"""
            SELECT Challenger, Challenged FROM Challenges 
            WHERE GroupId = {gid} AND (
                (Challenger = {player1} AND Challenged = {player2}) OR 
                (Challenger = {player2} AND Challenged = {player1})
            )
        """)

        if len(challenges) > 0:
            return True

        return False

    # if the challenge does not exist in the database, a new one is created
    @staticmethod
    def create_challenge(challenger, challenged, gid=0):
        """
        Creates a new challenge between two players in the database.

        :param challenger: The ID of the player issuing the challenge.
        :type challenger: int
        :param challenged: The ID of the player being challenged.
        :type challenged: int
        :param gid: Group ID. Default is 0.
        :type gid: int
        """
        execute_psql(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM Challenges WHERE GroupId={gid} and Challenger={challenger} and Challenged={challenged}) THEN
                    INSERT INTO Challenges (GroupId, Challenger, Challenged)
                    VALUES ({gid}, {challenger}, {challenged});
                END IF;
            END $$;
        """)

    # if the challenge exists in the database, it is deleted
    @staticmethod
    def delete_challenge(challenger, challenged, gid=0):
        """
        Deletes an existing challenge between two players from the database.

        :param challenger: The ID of the player who issued the challenge.
        :type challenger: int
        :param challenged: The ID of the player who was challenged.
        :type challenged: int
        :param gid: Group ID. Default is 0.
        :type gid: int
        """
        execute_psql(f"DELETE FROM Challenges WHERE GroupId={gid} and Challenger={challenger} and Challenged={challenged}")
