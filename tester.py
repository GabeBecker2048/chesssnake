import Game

g = Game.Game(0, 1, 2, 'g', 'a', SQL=False)

g.move('d4', img=True).show()
print(str(g))