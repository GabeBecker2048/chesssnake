import Game

g = Game.Game("Gabe", "Wyatt", SQL=False)

g.move('d4', img=True).show()
print(str(g))