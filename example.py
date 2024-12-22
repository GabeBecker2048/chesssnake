from chessnake import Game

# Initialize a new game
game = Game(white_name="Bob", black_name="Phil")

# Make moves
game.move('e4') # Bob's move
game.move('e5') # Phil's move

# Print the board
print(game)

# make the move, and show the board in png format
game.move('Nc3', img=True).show()

# save the board as a png
game.save('/path/to/your/image1.png')

# make the move, and save the board as a png
game.move('Bc5', save='/path/to/your/image2.png')
