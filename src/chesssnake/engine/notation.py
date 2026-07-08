"""Algebraic-notation helpers: coordinate<->notation conversion and syntax validation.

Coordinate system (matching the rest of the engine): ``i`` is the row index 0-7
from the top (i=0 is rank 8, i=7 is rank 1); ``j`` is the file index 0-7 (j=0 is
file 'a').
"""

# The eight files, 'a' (j=0) through 'h' (j=7), and ranks '1' through '8'.
FILES = "abcdefgh"
RANKS = "12345678"


def matches_disambiguation(square, file_limit: "str | None" = None, rank_limit: "str | None" = None) -> bool:
    """
    Whether ``square`` satisfies an optional file and/or rank disambiguation.

    Used when resolving algebraic notation like ``Rad1`` (file ``a``) or ``R1a3``
    (rank ``1``) back to a concrete piece.

    :param square: The candidate square to test.
    :type square: Square
    :param file_limit: Required file letter ('a'-'h'), or ``None`` for no constraint.
    :type file_limit: str or None
    :param rank_limit: Required rank digit ('1'-'8'), or ``None`` for no constraint.
    :type rank_limit: str or None
    :return: ``True`` if the square meets every supplied constraint.
    :rtype: bool
    """
    if file_limit is not None and file_limit != FILES[square.j]:
        return False
    if rank_limit is not None and rank_limit != str(8 - square.i):
        return False
    return True


def get_coords(c_notation: str) -> tuple[int, int]:
    """
    Converts chess notation (e.g., 'e4') into board coordinates `(i, j)`.

    :param c_notation: The chess notation string.
    :type c_notation: str
    :return: A tuple `(i, j)` where `i` is the row and `j` is the column.
    :rtype: tuple[int, int]
    """
    # changes file to j coord
    y = 0
    for i in range(8):
        if FILES[i] == c_notation[0]:
            y = i
            break

    # changes row to i coord
    x = 8 - int(c_notation[1])

    return x, y


def get_c_notation(i: int, j: int) -> str:
    """
    Converts board coordinates `(i, j)` into chess notation (e.g., 'e4').

    :param i: The row coordinate on the board.
    :type i: int
    :param j: The column coordinate on the board.
    :type j: int
    :return: The chess notation string.
    :rtype: str
    """
    # converts from coords to chess notation
    return FILES[j] + str(8 - i)


def is_valid_c_notation(movename: str) -> bool:
    """
    Validates whether the given chess move adheres to algebraic notation.
    See https://en.wikipedia.org/wiki/Algebraic_notation_(chess) for more information on algebraic notation.

    This method checks whether the `movename` string corresponds to a valid chess move in accordance
    with standard chess rules (e.g., proper format for regular moves, promotions, castling, and captures).

    This method does NOT check if the move is legal or not, but rather if the move syntax is correct.

    :param movename: The move name to validate (e.g., 'e2e4', 'Nf3', '0-0').
    :type movename: str
    :return: `True` if the move is valid, otherwise `False`.
    :rtype: bool

    **Rules for a valid move string**:
    - Must be at least two characters in length. (a pawn move)
    - Can end with '+' (check) or '#' (checkmate) symbols, but this is never required.
    - Castling must be in the format '0-0' (king-side) or '0-0-0' (queen-side).
    - Must contain valid chess piece designations ('R', 'N', 'B', 'Q', 'K', or 'P'), if specified.
    - Must use valid ranks ('1' to '8') and files ('a' to 'h').
    - Captures are marked with 'x', e.g., 'Nxe5'.
    """
    # any valid move must be at least 2 in length
    if len(movename) < 2:
        return False

    # cuts off check or checkmate symbol from tail end
    if '+' == movename[-1]:
        movename = movename[:-1]
    if '#' == movename[-1]:
        movename = movename[:-1]

    # if the move is a castling move, returns true
    if movename == "0-0" or movename == "0-0-0":
        return True

    # if not a pawn (or using traditional notation with 'P')...
    if movename[0] in "RNBQKP":
        # temp is everything that isn't square location or piecetype
        temp = movename[1:-2]

    # if a pawn...
    elif movename[0] in FILES:

        # if there is a promotion, it is removed from the string
        if movename[-1] in "RNBQ":
            movename = movename[:-1]

        # if there is a capture sign as the second letter...
        if movename[1] == 'x':
            # temp is everything that isn't square location or piecetype
            temp = movename[1:-2]

        # otherwise, temp is the entire movename
        else:
            temp = movename

    # if the first character is not valid, returns false
    else:
        return False

    # makes sure the last 2 characters are a square
    if movename[-2] not in FILES or movename[-1] not in RANKS:
        return False

    if len(temp) == 0:
        return True

    # if temp is one character and is not a valid character, returns false
    elif len(temp) == 1:
        if temp not in FILES + RANKS + "x":
            return False

    # if temp is two characters...
    elif len(temp) == 2:

        # if temp is a capture and the first letter of temp is not valid, returns false
        if 'x' == temp[1] and temp[0] not in FILES + RANKS:
            return False

        # if temp is a specification move and uses invalid characters, returns false
        if temp[0] not in FILES or temp[1] not in RANKS:
            return False

    # if temp is three characters...
    elif len(temp) == 3:

        # if temp is a specification and capture move and uses invalid specification, returns false
        if temp[0] not in FILES or temp[1] not in RANKS or temp[2] != 'x':
            return False

    # if temp is more than 3 characters, it is invalid
    else:
        return False

    # if all checks are passed, it returns true
    return True
