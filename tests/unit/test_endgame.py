"""Unit tests for terminal game states: checkmate and stalemate detection."""

from chesssnake.chesslib.Game import Game


def test_fools_mate_is_checkmate():
    # 1. f3 e5 2. g4 Qh4#  -- the fastest checkmate.
    g = Game()
    for m in ["f3", "e5", "g4", "Qh4"]:
        g.move(m)
    assert g.board.status == 1  # checkmate


def test_back_rank_checkmate(make_board):
    # Black king boxed in by its own pawns; white rook delivers mate on the 8th rank.
    board = make_board({
        (7, 0): "R0", (7, 4): "K0",           # white rook a1, white king e1
        (0, 6): "K1",                          # black king g8
        (1, 5): "P1", (1, 6): "P1", (1, 7): "P1",  # black pawns f7 g7 h7
    })
    g = Game(board=board, turn=0)
    g.move("Ra8")
    assert g.board.status == 1  # checkmate


def test_stalemate_detection(make_board):
    # Black king h8 with no legal moves and not in check after white plays Qg6.
    board = make_board({
        (0, 7): "K1",   # black king h8
        (1, 5): "K0",   # white king f7
        (2, 0): "Q0",   # white queen a6
    })
    g = Game(board=board, turn=0)
    g.move("Qg6")
    assert g.board.status == 2  # stalemate


def test_ongoing_game_has_no_terminal_status():
    g = Game()
    g.move("e4")
    g.move("e5")
    assert g.board.status == 0