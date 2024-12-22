from . import Chess
from . import ChessImg
from . import ChessError


class Game:
    # this loads game data from the database into the game object
    # if the game does not exist in the database, a new one is created
    def __init__(self, white_id: int=0, black_id: int=1, group_id: int=0, white_name: str='', black_name: str=''):

        self.gid = group_id
        self.wid = white_id
        self.bid = black_id
        self.wname = white_name
        self.bname = black_name
        self.board = Chess.Board()
        self.turn = 0
        self.draw = 0

    def __str__(self):
        return str(self.board)

    # returns True if it is a given player's turn to move and False otherwise
    def is_players_turn(self, player_id):

        if (self.turn == 0 and player_id == self.wid) or (self.turn == 1 and player_id == self.bid):
            return True
        else:
            return False

    # makes a given move, assuming it is the correct player's turn
    # if img=True, return a PIL.Image object. Otherwise, return None
    # if save is a string to a filepath, we save a PNG image of the board to the given location
    #   save implies img=True
    def move(self, move, img=False, save=None):

        # if invalid notation, we raise an error
        if not Chess.Move.is_valid_c_notation(move):
            raise ChessError.InvalidNotationError(move)

        # makes the move on the board
        m = self.board.move(move, self.turn)

        # changes whose turn it is
        self.turn = 1 - self.turn

        # handle optional args
        if img or save:
            image = ChessImg.img(self.board, self.wname, self.bname, m)
            if save:
                image.save(save)
            return image
        return None

    # offers a draw
    # "player_id" refers to the player offering the draw
    def draw_offer(self, player_id):

        # if a player has already offered draw
        if (self.draw == 0 and player_id == self.wid) or (self.draw == 1 and player_id == self.bid):
            raise ChessError.DrawAlreadyOfferedError()

        # if a player offers a draw after being offered a draw, the draw is accepted
        elif (self.draw == 1 and player_id == self.wid) or (self.draw == 0 and player_id == self.bid):
            self.draw_accept(player_id)

        # if it is not the players turn
        elif not self.is_players_turn(player_id):
            raise ChessError.DrawWrongTurnError()

        # player offers draw
        self.draw = 0 if player_id == self.wid else 1

    # checks if a draw exists and accepts if offered
    # "player_id" refers to the player offering the draw
    def draw_accept(self, player_id):

        if (self.draw == 0 and player_id == self.wid) or (self.draw == 1 and player_id == self.bid) or self.draw is None:
            raise ChessError.DrawNotOfferedError()

        self.board.status = 2

    # checks if a draw exists and declines if offered
    # "player_id" refers to the player offering the draw
    def draw_decline(self, player_id):

        if (self.draw == 0 and player_id == self.wid) or (self.draw == 1 and player_id == self.bid) or self.draw is None:
            raise ChessError.DrawNotOfferedError()

        self.draw = None

    # saves the board as a png to a given filepath
    def save(self, image_fp: str):
        ChessImg.img(self.board, self.wname, self.bname).save(image_fp)
