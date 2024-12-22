import importlib.resources

from .Sql_Utils import execute_sql
from . import GameError
from ..chesslib.Game import Game as BaseGame
from ..chesslib import Chess


class Game(BaseGame):
    # this loads game data from the database into the game object
    # if the game does not exist in the database, a new one is created
    def __init__(self, white_id: int=0, black_id: int=1, group_id: int=0, white_name: str='', black_name: str='', sql: bool=False, auto_sql: bool=False):

        super().__init__(white_id, black_id, group_id, white_name, black_name)

        self.sql = sql
        self.auto_sql = auto_sql

        # if sql=True, then we check the database to see if a game exists
        ## if it exists, we load the sql data into memory
        ## if it doesn't, we create a blank game in the DB and load a new game into memory
        # if sql=False, we create a new game in memory only
        if sql or auto_sql:
            boardarray, turn, draw, two_move_p = self.sql_game_init(white_id, black_id, group_id, white_name, black_name)

        else:
            boardarray = None
            two_move_p = None
            turn = 0
            draw = 0

        # TODO: Find a way to make Chess.Board() be called only once
        #       Currently, Chess.Board() is called in super().__init__ and here
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

        img = super().move(move, img, save)

        # handle SQL updating
        if self.auto_sql:
            boardstr, moved = Chess.Board.disassemble_board(self.board)
            pawnmove = "NULL" if self.board.two_moveP is None else f"'{self.board.two_moveP.c_notation}'"
            draw = "NULL" if (self.draw is not None and self.turn != self.draw) or self.draw is None else f"'{self.draw}'"

            execute_sql(f"""
                UPDATE Games SET Board = '{boardstr}', Turn = '{self.turn}', PawnMove = {pawnmove}, Moved = '{moved}', Draw = {draw}
                WHERE GroupId = {self.gid} and WhiteId = {self.wid} and BlackId = {self.bid}
            """)

        return img

    # offers a draw
    # "player_id" refers to the player offering the draw
    def draw_offer(self, player_id):

        super().draw_offer(player_id)

        if self.auto_sql:
            execute_sql(f"""
                UPDATE Games SET Draw = '{self.draw}'
                WHERE GroupId = {self.gid} and WhiteId = {self.wid} and BlackId = {self.bid}
            """)

    # checks if a draw exists and accepts if offered
    # "player_id" refers to the player offering the draw
    def draw_accept(self, player_id):

        super().draw_accept(player_id)

        self.end_check()

    # checks if a draw exists and declines if offered
    # "player_id" refers to the player offering the draw
    def draw_decline(self, player_id):

        super().draw_decline(player_id)

        if self.auto_sql:
            execute_sql(f"""
                UPDATE Games SET Draw = NULL
                WHERE GroupId = {self.gid} and WhiteId = {self.wid} and BlackId = {self.bid}
            """)

    # checks if the game is over and deletes the game from the database accordingly
    def end_check(self):
        if self.board.status != 0:
            if self.auto_sql:
                self.sql_delete_game(self.gid, self.wid, self.bid)
            return True
        return False

    # This is the function for updating the database, for cases where sql=true but auto_sql=false
    # returns False and does nothing if sql is not enabled
    def update_db(self):
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
            """)
            return True
        else:
            return False

    @staticmethod
    def sql_db_init():
        db_init_fp = str(importlib.resources.files('chesssnake.chesslib').joinpath('data/init.sql'))

        with open(db_init_fp, 'r') as db_init_file:
            db_init = db_init_file.read()

        execute_sql(db_init)

    # checks the sql data if a game exists
    #   if it does, get the game data from the database
    #   if it doesn't, create the game and return the new game data
    @staticmethod
    def sql_game_init(white_id, black_id, group_id=0, white_name='', black_name=''):
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
        """)[0]

        boardarray = Chess.Board.assemble_board(game[3], game[7])
        turn = int(game[4])
        draw = int(game[6]) if game[6] else None
        two_move_p = Chess.Square(Chess.Board.get_coords(game[5])[0], Chess.Board.get_coords(game[5])[1]) if game[5] else None

        return boardarray, turn, draw, two_move_p

    @staticmethod
    def sql_current_games(player_id, gid=0):

        games = execute_sql(f"""
            WITH PlayerResult AS (
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
        """)
        games = [g[0] for g in games]
        return games

    # if the game exists, returns the white player's id and black player's id in that order
    # returns False if the game is not found in the database
    @staticmethod
    def sql_game_exists(player1, player2, gid=0):

        games = execute_sql(f"""
            SELECT WhiteId, BlackId FROM Games 
            WHERE GroupId = {gid} AND (
                (WhiteId = {player1} AND BlackID = {player2}) OR 
                (WhiteId = {player2} AND BlackID = {player1})
            )
        """)

        if games:
            return games[0]

        return False

    # removes a game from the database
    @staticmethod
    def sql_delete_game(wid, bid, gid=0):
        execute_sql(f"DELETE FROM games WHERE GroupId = {gid} and WhiteId = {wid} and BlackId = {bid}")


# the SQL wrapper function for the Challenges table
# This class is not compatible with non-SQL games
class Challenge:
    @staticmethod
    def challenge(challenger=0, opponent=1, gid=0):

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
        execute_sql(f"DELETE FROM Challenges WHERE GroupId={gid} and Challenger={challenger} and Challenged={challenged}")
