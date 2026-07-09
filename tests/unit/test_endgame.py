"""Unit tests for terminal game states: checkmate and stalemate detection."""

from chesssnake.engine import Game


def test_fools_mate_is_checkmate():
    # 1. f3 e5 2. g4 Qh4#  -- the fastest checkmate.
    g = Game()
    for m in ["f3", "e5", "g4", "Qh4"]:
        g.move(m)
    assert g.board.status == 2  # black wins (fool's mate)


def test_back_rank_checkmate(make_board):
    # Black king boxed in by its own pawns; white rook delivers mate on the 8th rank.
    board = make_board(
        {
            (7, 0): "R0",
            (7, 4): "K0",  # white rook a1, white king e1
            (0, 6): "K1",  # black king g8
            (1, 5): "P1",
            (1, 6): "P1",
            (1, 7): "P1",  # black pawns f7 g7 h7
        }
    )
    g = Game(board=board, turn=0)
    g.move("Ra8")
    assert g.board.status == 1  # white wins (back-rank mate)


def test_stalemate_detection(make_board):
    # Black king h8 with no legal moves and not in check after white plays Qg6.
    board = make_board(
        {
            (0, 7): "K1",  # black king h8
            (1, 5): "K0",  # white king f7
            (2, 0): "Q0",  # white queen a6
        }
    )
    g = Game(board=board, turn=0)
    g.move("Qg6")
    assert g.board.status == 3  # draw (stalemate)


def test_pawn_can_block_check_is_not_mate(make_board):
    # Regression: a check that can only be answered by a pawn *advancing* to block
    # must not be scored as checkmate. Earlier versions never detected a blocking
    # pawn push (they tested `isinstance(pawn, Pawn)` on a value that is a Square),
    # so they wrongly declared this position mate.
    #
    # Black king e5 is boxed by its own pawns; the white rook on a5 checks along
    # rank 5. The sole legal reply is d6-d5, interposing the pawn.
    board = make_board(
        {
            (3, 4): "K1",  # black king e5
            (3, 0): "R0",  # white rook a5 (checks along rank 5)
            (2, 3): "P1",
            (2, 4): "P1",
            (2, 5): "P1",  # black pawns d6 e6 f6
            (4, 3): "P1",
            (4, 4): "P1",
            (4, 5): "P1",  # black pawns d4 e4 f4
            (7, 4): "K0",  # white king e1
        }
    )
    assert board.check_for_check(1) is True
    assert board.check_for_mate(1) is False  # d6-d5 blocks the check


def test_diagonal_check_can_be_blocked_is_not_mate(make_board):
    # Regression: a *diagonal* check that can be answered by interposing a piece
    # must not be scored as mate. The blocking-square math for diagonals was doubly
    # broken (it used `king_square.j` where it meant `.i`, and was off by one), so a
    # blockable diagonal check could be misreported as checkmate.
    #
    # Black king h8 is checked by the white bishop a1 along the long diagonal; the
    # king is boxed (own pawns g8/h7, and g7 lies on the checking diagonal). The one
    # defense is Rb2, interposing the rook on the diagonal.
    board = make_board(
        {
            (0, 7): "K1",  # black king h8
            (7, 0): "B0",  # white bishop a1 (checks along a1-h8)
            (0, 6): "P1",
            (1, 7): "P1",  # black pawns g8, h7 (box the king)
            (0, 1): "R1",  # black rook b8 -> can interpose with Rb2
            (7, 4): "K0",  # white king e1
        }
    )
    assert board.check_for_check(1) is True
    assert board.check_for_mate(1) is False  # Rb2 blocks the diagonal


def test_diagonal_checkmate_is_mate(make_board):
    # Positive counterpart: a genuine long-range diagonal mate must still be scored
    # as mate (guards against a fix that simply never reports diagonal mates).
    #
    # White bishop c3 checks the black king h8 along c3-h8; the white queen f7 covers
    # every escape (g8, h7, g7). Nothing can interpose on d4/e5/f6/g7 or capture the
    # bishop -> checkmate.
    board = make_board(
        {
            (0, 7): "K1",  # black king h8
            (5, 2): "B0",  # white bishop c3 (checks along c3-h8)
            (1, 5): "Q0",  # white queen f7 (covers g8/h7/g7)
            (7, 4): "K0",  # white king e1
        }
    )
    assert board.check_for_check(1) is True
    assert board.check_for_mate(1) is True


def test_diagonal_check_can_be_captured_is_not_mate(make_board):
    # A diagonal check answered by capturing the checker is not mate.
    # Black rook h3 shares the 3rd rank with the checking bishop c3 -> Rxc3.
    board = make_board(
        {
            (0, 7): "K1",  # black king h8
            (5, 2): "B0",  # white bishop c3 (checks along c3-h8)
            (1, 5): "Q0",  # white queen f7 (covers the king's escapes)
            (5, 7): "R1",  # black rook h3 -> can capture with Rxc3
            (7, 4): "K0",  # white king e1
        }
    )
    assert board.check_for_check(1) is True
    assert board.check_for_mate(1) is False  # Rxc3 removes the checker


def test_ongoing_game_has_no_terminal_status():
    g = Game()
    g.move("e4")
    g.move("e5")
    assert g.board.status == 0
