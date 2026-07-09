from chesssnake import Game

# Initialize a new local game
game = Game.local(white_name="Bob", black_name="Phil")

# Make moves (move() returns the Move that was played)
game.move("e4")  # Bob's move
game.move("e5")  # Phil's move

# Print the board
print(game)

# Rendering is separate from moving:
game.move("Nc3")
game.render().show()  # show the current board as an image

# save the board as a png (highlights the last move)
game.save("/path/to/your/image1.png")

# inspect game state through intention-revealing accessors
print("to move:", game.to_move)
print("game over?", game.is_over)
