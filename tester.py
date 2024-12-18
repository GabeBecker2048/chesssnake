from chessql import Game
from dotenv import load_dotenv

load_dotenv()

g = Game(white_name="Bob", black_name="Phil")

g.move('d4',img=True).show()