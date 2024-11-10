from random import randint
import psycopg2
from psycopg2.extras import RealDictCursor
import Chess
import ChessError
import ChessImg
import GameError

# For extracting env keys
from dotenv import load_dotenv
from os import getenv

from GameError import ChallengeError


def load_sql_env():
    load_dotenv()
    for db_var in ['CHESSDB_NAME', 'CHESSDB_USER', 'CHESSDB_PASS', 'CHESSDB_HOST', 'CHESSDB_PORT']:
        if getenv(db_var) is None:
            raise EnvironmentError(f"Environment variable '{db_var}' is not set.")


def execute_sql(statement: str, params=None):
    # Reload the execute_sql creds every time a query is called
    # This is a very small performance hit, but ensures that we can dynamically change the db credentials
    load_sql_env()
    CHESSDB_NAME = getenv("CHESSDB_NAME")
    CHESSDB_USER = getenv("CHESSDB_USER")
    CHESSDB_PASS = getenv("CHESSDB_PASS")
    CHESSDB_HOST = getenv("CHESSDB_HOST")
    CHESSDB_PORT = getenv("CHESSDB_PORT")

    conn_str = f"dbname='{CHESSDB_NAME}' user='{CHESSDB_USER}' password='{CHESSDB_PASS}' host='{CHESSDB_HOST}' port='{CHESSDB_PORT}'"

    with psycopg2.connect(conn_str) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(statement, params)
            try:
                results = cur.fetchall()
                return results
            except psycopg2.ProgrammingError:
                return None


class Game:
    # this loads game data from the database into the game object
    # if the game does not exist in the database, a new one is created
    def __init__(self, gid, wid, bid, wname='', bname=''):
        self.gid = gid
        self.wid = wid
        self.bid = bid
        self.wname = wname
        self.bname = bname

        game = execute_sql(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM Games WHERE GroupId={gid} AND WhiteId={wid} AND BlackId={bid}) THEN
                    INSERT INTO Games (GroupId, WhiteId, BlackId, Board, Turn, Pawnmove, Draw, Moved, WName, BName)
                    VALUES ({gid}, {wid}, {bid},
                    'R1 N1 B1 Q1 K1 B1 N1 R1;P1 P1 P1 P1 P1 P1 P1 P1;-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;P0 P0 P0 P0 P0 P0 P0 P0;R0 N0 B0 Q0 K0 B0 N0 R0',
                    '0', NULL, NULL, '000000', {wname}, {bname});
                END IF;
            END $$;
            
            SELECT * FROM Games WHERE GroupId={gid} AND WhiteId={wid} AND BlackId={bid};
        """)[0]

        boardarray = Chess.Board.assemble_board(game[3], game[7])

        self.board = Chess.Board(
            board=boardarray,
            two_moveP=None if game[5] is None else Chess.Square(Chess.Board.get_coords(game[5])[0], Chess.Board.get_coords(game[5])[1])
        )
        self.turn = int(game[4])
        self.draw = game[5]

    # returns True if it is a given player's turn to move and False otherwise
    def is_players_turn(self, player_id):

        if (self.turn == 0 and player_id == self.wid) or (self.turn == 1 and player_id == self.bid):
            return True
        else:
            return False

    # makes a given move, assuming it is the correct player's turn
    # return a PIL.Image object if img=True. Otherwise returns None
    # if save_to is a string to a filepath, we save a PNG image of the board to the given location
    def move(self, move, img=False, save_to=None):

        # if invalid notation, we raise an error
        if not Chess.Move.is_valid_c_notation(move):
            raise ChessError.InvalidNotationError(move)

        # makes the move on the board
        m = self.board.move(move, self.turn)

        boardstr, moved = Chess.Board.disassemble_board(self.board)
        pawnmove = "NULL" if self.board.two_moveP is None else f"'{self.board.two_moveP.c_notation}'"
        draw = "NULL" if (self.draw is not None and self.turn != self.draw) or self.draw is None else f"'{self.draw}'"

        # changes whose turn it is
        self.turn = 1 - self.turn

        execute_sql(f"""
            UPDATE Games SET Board = '{boardstr}', Turn = '{self.turn}', PawnMove = {pawnmove}, Moved = '{moved}', Draw = {draw}
            WHERE GroupId = {self.gid} and WhiteId = {self.wid} and BlackId = {self.bid}
        """)

        # handle optional args
        if img or save_to:
            image = ChessImg.img(self.board, self.wname, self.bname, m)
            if save_to:
                image.save(save_to)
            return image

    # takes in a list of moves and executes them in order; returns the last move
    def moves(self, moves):
        for move in moves:
            m = self.move(move)
        if len(moves) != 0:
            return m
        return None

    # offers a draw
    # "player_id" refers to the player offering the draw
    def draw_offer(self, player_id):

        # if a player has already offered draw
        if (self.draw == 0 and player_id == self.wid) or (self.draw == 1 and player_id == self.bid):
            raise ChessError.DrawAlreadyOfferedError

        # if a player offers a draw after being offered a draw, the draw is accepted
        elif (self.draw == 1 and player_id == self.wid) or (self.draw == 0 and player_id == self.bid):
            self.draw_accept(player_id)

        # if it is not the players turn
        elif not self.is_players_turn(player_id):
            raise ChessError.DrawWrongTurnError

        # player offers draw
        self.draw = 0 if player_id == self.wid else 1

        execute_sql(f"""
            UPDATE Games SET Draw = '{self.draw}'
            WHERE GroupId = {self.gid} and WhiteId = {self.wid} and BlackId = {self.bid}
        """)

    # checks if a draw exists and accepts if offered
    # "player_id" refers to the player offering the draw
    def draw_accept(self, player_id):

        if (self.draw == 0 and player_id == self.wid) or (self.draw == 1 and player_id == self.bid) or self.draw is None:
            raise ChessError.DrawNotOfferedError

        self.board.status = 2
        self.end_check()

    # checks if a draw exists and declines if offered
    # "player_id" refers to the player offering the draw
    def draw_decline(self, player_id):

        if (self.draw == 0 and player_id == self.wid) or (self.draw == 1 and player_id == self.bid) or self.draw is None:
            raise ChessError.DrawNotOfferedError

        execute_sql(f"""
            UPDATE Games SET Draw = NULL
            WHERE GroupId = {self.gid} and WhiteId = {self.wid} and BlackId = {self.bid}
        """)

        self.draw = None

    # checks if the game is over and deletes the game from the database accordingly
    def end_check(self):
        if self.board.status != 0:
            self.delete_game(self.gid, self.wid, self.bid)
            return True
        return False

    # saves the board as a png to a given filepath
    def save_to(self, image_fp: str):
        ChessImg.img(self.board, self.wname, self.bname).save(image_fp)

    @staticmethod
    def current_games(gid, player_id):

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
    def game_exists(gid, player1, player2):

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
    def delete_game(gid, wid, bid):
        execute_sql(f"DELETE FROM games WHERE GroupId = {gid} and WhiteId = {wid} and BlackId = {bid}")


class Challenge:
    @staticmethod
    def challenge(challenger, opponent, gid='0'):

        if challenger == opponent:
            GameError.ChallengeError("You can't challenge yourself, silly")

        # checks if they are already in a game
        if Game.game_exists(gid, challenger, opponent):
            GameError.ChallengeError(f"There is an unresolved game between {challenger} and {opponent} already!")

        # check if the challenge exists already
        challenge = Challenge.exists(gid, challenger, opponent)

        if not challenge:
            Challenge.create_challenge(gid, challenger, opponent)
            return

        elif challenger == challenge[0]:
            GameError.ChallengeError(f"You have already challenged {opponent}! You must wait for them to accept")
            return

        # From this point on, we know that "challenger" is accepting a challenge already given by "opponent"
        ridx = randint(0, 1)
        wid = [challenger, opponent][ridx]
        bid = [challenger, opponent][1 - ridx]

        # deletes users from challenges
        Challenge.delete_challenge(gid, challenger, opponent)

        # create a game if we've checked for everything else
        Game(gid, wid, bid)

    # if the challenge exists, returns the challenger id and the challenge id in that order
    # otherwise, returns False
    @staticmethod
    def exists(player1, player2, gid='0'):
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
    def create_challenge(challenger, challenged, gid='0'):
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
    def delete_challenge(challenger, challenged, gid='0'):
        execute_sql(f"DELETE FROM Challenges WHERE GroupId={gid} and Challenger={challenger} and Challenged={challenged}")
