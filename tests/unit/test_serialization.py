"""Unit tests for board serialization (disassemble_board / assemble_board)."""

from chesssnake.chesslib.Chess import Board


def test_initial_board_disassembles_to_expected_string():
    board = Board()
    boardstring, moved = Board.disassemble_board(board)
    expected = (
        "R1 N1 B1 Q1 K1 B1 N1 R1;P1 P1 P1 P1 P1 P1 P1 P1;"
        "-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;"
        "-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;"
        "P0 P0 P0 P0 P0 P0 P0 P0;R0 N0 B0 Q0 K0 B0 N0 R0"
    )
    assert boardstring == expected
    assert moved == "000000"  # nothing has moved on a fresh board


def test_disassemble_reassemble_round_trip():
    board = Board()
    # play a handful of moves through the board directly
    for move, player in [("e4", 0), ("e5", 1), ("Nf3", 0), ("Nc6", 1)]:
        board.move(move, player)

    boardstring, moved = Board.disassemble_board(board)
    rebuilt = Board(board=Board.assemble_board(boardstring, moved))

    assert str(rebuilt) == str(board)
    # the rebuilt board serializes back to the identical representation
    assert Board.disassemble_board(rebuilt) == (boardstring, moved)


def test_moved_flag_set_for_rook_that_returned_home():
    # The `moved` string flags a king/rook that is on its home square and has
    # moved (so castling rights are correctly lost even if the rook returns).
    board = Board()
    board.move("a4", 0)    # open the a-file in front of the a1 rook
    board.move("Ra3", 0)   # a1 rook steps out
    board.move("Ra1", 0)   # ...and returns home, now flagged as moved

    _, moved = Board.disassemble_board(board)
    assert moved[0] == "1"          # white a1 rook has moved
    assert moved[1] == "0"          # white king has not
    assert moved[3:] == "000"       # black king/rooks untouched
