
from .Sql_Utils import execute_sql, sql_db_init
from . import GameError
from ..chesslib.Game import Game as BaseGame
from ..chesslib import Chess


class Game(BaseGame):
    """
    Extends the functionality of the `Game` class from `chesssnake.chesslib` to include SQL database support.

    The `Game` class manages chess gameplay logic while adding functionality for game persistence and interaction with an SQL database.
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
    :param db_conn_str: Database connection string. Default is None.
    :type db_conn_str: str or None
    :param db_name: Database name. Default is None.
    :type db_name: str or None
    :param db_user: Database username. Default is None.
    :type db_user: str or None
    :param db_password: Database password. Default is None.
    :type db_password: str or None
    :param db_host: Database host address. Default is None.
    :type db_host: str or None
    :param db_port: Database port number. Default is None.
    :type db_port: str or None
    """

    # this loads game data from the database into the game object
    # if the game does not exist in the database, a new one is created
    def __init__(self,
                 white_id: int=0,
                 black_id: int=1,
                 group_id: int=0,
                 white_name: str='',
                 black_name: str='',
                 sql: bool=False,
                 auto_sql: bool=False,
                 db_conn_str: str|None=None,
                 db_name: str|None=None,
                 db_user: str|None=None,
                 db_password: str|None=None,
                 db_host: str|None=None,
                 db_port: str|None=None):
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
        :param db_conn_str: Database connection string. Default is None.
        :type db_conn_str: str or None
        :param db_name: Database name. Default is None.
        :type db_name: str or None
        :param db_user: Database username. Default is None.
        :type db_user: str or None
        :param db_password: Database password. Default is None.
        :type db_password: str or None
        :param db_host: Database host address. Default is None.
        :type db_host: str or None
        :param db_port: Database port number. Default is None.
        :type db_port: str or None
        """

        super().__init__(white_id, black_id, group_id, white_name, black_name)

        self.sql = sql
        self.auto_sql = auto_sql

        # If a conn_str is given programmatically, we use that
        # Otherwise we attempt to load the database creds from environment variables
        self.sql_creds = {
            "conn_str": db_conn_str,
            "name": db_name,
            "user": db_user,
            "password": db_password,
            "host": db_host,
            "port": db_port,
        }

        # if sql=True, then we check the database to see if a game exists
        ## if it exists, we load the sql data into memory
        ## if it doesn't, we create a blank game in the DB and load a new game into memory
        # if sql=False, we create a new game in memory only
        if sql or auto_sql:
            boardarray, turn, draw, two_move_p = self.sql_game_init(white_id, black_id, group_id, white_name, black_name)
            self.board = Chess.Board(
                board=boardarray,
                two_moveP=two_move_p
            )

            self.turn = turn
            self.draw = draw

    # makes a given move, assuming it is the correct player's turn
    # if img=True, return a PIL.Image object. Otherwise, return None
    # if save is a string to a filepath, we save a PNG image of the board to the given location
    #   save implies img=True
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
        img = super().move(move, img, save)

        # handle SQL updating
        if self.auto_sql:
            boardstr, moved = Chess.Board.disassemble_board(self.board)
            pawnmove = "NULL" if self.board.two_moveP is None else f"'{self.board.two_moveP.c_notation}'"
            draw = "NULL" if (self.draw is not None and self.turn != self.draw) or self.draw is None else f"'{self.draw}'"

            execute_sql(f"""
                UPDATE Games SET Board = '{boardstr}', Turn = '{self.turn}', PawnMove = {pawnmove}, Moved = '{moved}', Draw = {draw}
                WHERE GroupId = {self.gid} and WhiteId = {self.wid} and BlackId = {self.bid}
            """, prog_sql_creds=self.sql_creds)

        return img

    # offers a draw
    # "player_id" refers to the player offering the draw
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
            execute_sql(f"""
                UPDATE Games SET Draw = '{self.draw}'
                WHERE GroupId = {self.gid} and WhiteId = {self.wid} and BlackId = {self.bid}
            """, prog_sql_creds=self.sql_creds)

    # checks if a draw exists and accepts if offered
    # "player_id" refers to the player offering the draw
    def draw_accept(self, player_id):
        """
        Accepts the opponent's existing draw offer.

        Marks the game as a draw. Automatically removes the game from the database if `auto_sql` is enabled.

        :param player_id: The player accepting the draw offer.
        :type player_id: int
        :raises ChessError.DrawNotOfferedError: If no draw offer exists.
        """
        super().draw_accept(player_id)

        self.end_check()

    # checks if a draw exists and declines if offered
    # "player_id" refers to the player offering the draw
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
            execute_sql(f"""
                UPDATE Games SET Draw = NULL
                WHERE GroupId = {self.gid} and WhiteId = {self.wid} and BlackId = {self.bid}
            """, prog_sql_creds=self.sql_creds)

    # checks if the game is over and deletes the game from the database accordingly
    def end_check(self):
        """
        Checks if the game is over, either by draw or checkmate, and removes it from the SQL database if finished.

        :return: True if the game is over, False otherwise.
        :rtype: bool
        """
        if self.board.status != 0:
            if self.auto_sql:
                self.sql_delete_game(self.gid, self.wid, self.bid)
            return True
        return False

    def update_db(self):
        """
        Updates the database with the current game state.

        This method is designed for cases where `sql=True` but `auto_sql=False`.
        If SQL support is enabled (`sql` or `auto_sql`), updates the game's record in the database
        with the current board state, turn, draw status, and player information.

        :return: True if the update was successful, False if SQL support is not enabled.
        :rtype: bool
        """
        if self.sql or self.auto_sql:
            execute_sql(f"""
            UPDATE Games SET
            Board = '{self.board.disassemble_board(self.board)[0]}', 
            Turn = '{self.turn}', 
            Pawnmove = {f"'{self.board.two_moveP.c_notation}'" if self.board.two_moveP else "NULL"}, 
            Draw = {f"'{self.draw}'" if self.draw else "NULL"}, 
            Moved = '{self.board.disassemble_board(self.board)[1]}', 
            WName = '{self.wname}', 
            BName = '{self.bname}'
            WHERE GroupId={self.gid} AND WhiteId={self.wid} AND BlackId={self.bid} 
            """, prog_sql_creds=self.sql_creds)
            return True
        else:
            return False

    def db_init(self):
        """
        Initializes the database for game storage and interaction.

        This method sets up the connection to the database using the credentials provided through
        environment variables or during the instantiation of the `Game` object.
        Typically used to ensure the database schema is initialized or available for interaction.
        """
        sql_db_init(prog_sql_creds=self.sql_creds)

    # checks the sql data if a game exists
    #   if it does, get the game data from the database
    #   if it doesn't, create the game and return the new game data
    def sql_game_init(self, white_id, black_id, group_id=0, white_name='', black_name=''):
        """
        Initializes or loads a game from the SQL database.

        If the specified players are not already in a game, a new record is created in the database.
        Otherwise, the existing game state is retrieved.

        :return: Tuple containing game data: board state, turn, draw status, pawn state.
        :rtype: tuple
        """
        game = execute_sql(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM Games WHERE GroupId={group_id} AND WhiteId={white_id} AND BlackId={black_id}) THEN
                    INSERT INTO Games (GroupId, WhiteId, BlackId, Board, Turn, Pawnmove, Draw, Moved, WName, BName)
                    VALUES ({group_id}, {white_id}, {black_id},
                    'R1 N1 B1 Q1 K1 B1 N1 R1;P1 P1 P1 P1 P1 P1 P1 P1;-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;P0 P0 P0 P0 P0 P0 P0 P0;R0 N0 B0 Q0 K0 B0 N0 R0',
                    '0', NULL, NULL, '000000', '{white_name}', '{black_name}');
                END IF;
            END $$;

            SELECT * FROM Games WHERE GroupId={group_id} AND WhiteId={white_id} AND BlackId={black_id};
        """, prog_sql_creds=self.sql_creds)[0]

        boardarray = Chess.Board.assemble_board(game[3], game[7])
        turn = int(game[4])
        draw = int(game[6]) if game[6] else None
        two_move_p = Chess.Square(Chess.Board.get_coords(game[5])[0], Chess.Board.get_coords(game[5])[1]) if game[5] else None

        return boardarray, turn, draw, two_move_p


    def sql_current_games(self, player_id: int, gid: int = 0):
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
        games = execute_sql("""WITH PlayerResult AS (
                SELECT 
                    CASE 
                        WHEN WhiteId = {player_id} THEN BlackId
                        WHEN BlackId = {player_id} THEN WhiteId
                        ELSE NULL
                    END AS Result
                FROM Games
                WHERE GroupId = {gid}
            )
            SELECT Result
            FROM PlayerResult
            WHERE Result IS NOT NULL;
        """, prog_sql_creds=self.sql_creds)
        games = [g[0] for g in games]
        return games

    # if the game exists, returns the white player's id and black player's id in that order
    # returns False if the game is not found in the database
    def sql_game_exists(self, player1, player2, gid=0):
        """
        Checks if a game already exists between two players in the database.

        :param player1: The ID of the first player.
        :type player1: int
        :param player2: The ID of the second player.
        :type player2: int
        :param gid: The ID of the group in which the players are playing.
        :type gid: int
        :return: Tuple of player IDs if the game exists, otherwise False.
        :rtype: tuple | bool
        """
        games = execute_sql(f"""
            SELECT WhiteId, BlackId FROM Games 
            WHERE GroupId = {gid} AND (
                (WhiteId = {player1} AND BlackID = {player2}) OR 
                (WhiteId = {player2} AND BlackID = {player1})
            )
        """, prog_sql_creds=self.sql_creds)

        if games:
            return games[0]

        return False

    # removes a game from the database
    def sql_delete_game(self, wid, bid, gid=0):
        """
        Deletes the specified game from the database.

        :param white_id: The ID of the white player.
        :type white_id: int
        :param black_id: The ID of the black player.
        :type black_id: int
        :param gid: The ID of the group.
        :type gid: int
        """
        execute_sql(f"DELETE FROM games WHERE GroupId = {gid} and WhiteId = {wid} and BlackId = {bid}",
                    prog_sql_creds=self.sql_creds)


# the SQL wrapper function for the Challenges table
# This class is not compatible with non-SQL games
class Challenge:
    """
    SQL wrapper for challenges recorded in the `Challenges` SQL table.

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
        if Game.sql_game_exists(gid, challenger, opponent):
            raise GameError.ChallengeError(f"There is an unresolved game between {challenger} and {opponent} already!")

        # check if the challenge exists already
        challenge = Challenge.exists(challenger, opponent, gid)

        if not challenge:
            raise Challenge.create_challenge(challenger, opponent, gid)

        elif challenger == challenge[0]:
            raise GameError.ChallengeError(f"You have already challenged {opponent}! You must wait for them to accept")

        # deletes users from challenges
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
        :return: Tuple `(challenger, challenged)` if a challenge exists. Otherwise, False.
        :rtype: tuple | bool
        """
        games = execute_sql(f"""
            SELECT Challenger, Challenged FROM Challenges 
            WHERE GroupId = {gid} AND (
                (Challenger = {player1} AND Challenged = {player2}) OR 
                (Challenger = {player2} AND Challenged = {player1})
            )
        """)

        if len(games) > 0:
            return games[0]

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
        execute_sql(f"""
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
        execute_sql(f"DELETE FROM Challenges WHERE GroupId={gid} and Challenger={challenger} and Challenged={challenged}")
