from chessql import Game
from dotenv import load_dotenv

load_dotenv()

g = Game()

g.move('d4',img=True).show()