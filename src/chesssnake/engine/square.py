"""The `Square` value type: one of the 64 board positions."""

from .notation import FILES


class Square:
    """
    Represents a square on a chessboard.

    A square is one of 64 positions on a chessboard, identifiable by its
    coordinates `(i, j)` and chess notation (e.g., 'e4', 'a1'). It also
    stores the square's color and can optionally hold a chess piece.

    :ivar i: The row position (coordinate) of the square on the board,
        where 0 represents the top row (rank 8) and 7 represents the
        bottom row (rank 1).
    :type i: int
    :ivar j: The column position (coordinate) of the square on the board,
        where 0 represents the leftmost file ('a') and 7 represents the
        rightmost file ('h').
    :type j: int
    :ivar c_notation: The chess notation string of the square (e.g., 'a8', 'd4').
        This represents a file ('a' to 'h') combined with a rank ('1' to '8').
    :type c_notation: str
    :ivar color: The color of the square, where 0 represents light (white) and
        1 represents dark (black).
    :type color: int
    :ivar piece: The chess piece currently occupying the square, or `None` if
        the square is empty.
    :type piece: Optional[Piece]
    """
    def __init__(self, i: int, j: int, piece=None):
        """
        Initializes a square on a chessboard.

        This sets up the essential data for a square, including its position,
        chess notation, color, and any chess piece located on it.

        :param i: The row position of the square (0-7), where 0 is the top row (rank 8)
            and 7 is the bottom row (rank 1).
        :type i: int
        :param j: The column position of the square (0-7), where 0 is the leftmost
            file ('a') and 7 is the rightmost file ('h').
        :type j: int
        :param piece: The chess piece located on the square, or `None` if the square
            is empty. Defaults to `None`.
        :type piece: Optional[Piece]
        """
        # i and j are the square's coordinates on the board
        # c_notation is the chess notation for the square (in a string form)
        # color will be a binary bool where light is 0 and dark is 1
        # piece will either be a piece object or None

        self.i = i
        self.j = j

        # converts from coords to chess notation
        self.c_notation = FILES[j] + str(8 - i)

        # determines color of square
        self.color = j % 2 if (i % 2) == 0 else (j + 1) % 2

        # sets the piece
        self.piece = piece

    def __eq__(self, other) -> bool:
        """
        Compares two squares for equality.

        Two squares are considered equal if they have the same row (`i`)
        and column (`j`) coordinates.

        :param other: The other square to compare against.
        :type other: Square or None
        :return: `True` if the squares have the same coordinates,
            otherwise `False`.
        :rtype: bool
        """
        if other is None:
            return False

        if self.i == other.i and self.j == other.j:
            return True
        return False
