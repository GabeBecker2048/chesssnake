"""Unit tests for move mechanics: pawns, captures, en passant, castling, promotion, errors."""

import pytest

from chesssnake import engine as Chess
from chesssnake.engine import Game
from chesssnake.engine import errors as ChessError


def piece_at(board, c_notation):
    i, j = Chess.Board.get_coords(c_notation)
    return board[i, j].piece


def test_pawn_push_moves_piece():
    g = Game()
    g.move("e4")
    assert piece_at(g.board, "e2") is None
    p = piece_at(g.board, "e4")
    assert p is not None and p.piecetype.value == "P" and p.color == 0


def test_knight_move():
    g = Game()
    g.move("Nf3")
    p = piece_at(g.board, "f3")
    assert p is not None and p.piecetype.value == "N" and p.color == 0
    assert piece_at(g.board, "g1") is None


def test_pawn_capture():
    g = Game()
    g.move("e4")
    g.move("d5")
    g.move("exd5")
    p = piece_at(g.board, "d5")
    assert p is not None and p.piecetype.value == "P" and p.color == 0


def test_en_passant_capture():
    g = Game()
    g.move("e4")
    g.move("Nf6")
    g.move("e5")
    g.move("d5")        # black double-steps next to the white e5 pawn
    g.move("exd6")      # white captures en passant
    assert piece_at(g.board, "d6") is not None       # capturing pawn advanced
    assert piece_at(g.board, "d6").piecetype.value == "P"
    assert piece_at(g.board, "d5") is None           # captured pawn removed


def test_kingside_castle():
    g = Game()
    for m in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]:
        g.move(m)
    g.move("0-0")
    king = piece_at(g.board, "g1")
    rook = piece_at(g.board, "f1")
    assert king is not None and king.piecetype.value == "K"
    assert rook is not None and rook.piecetype.value == "R"
    assert piece_at(g.board, "e1") is None
    assert piece_at(g.board, "h1") is None


def test_promotion_to_queen(make_board):
    # White pawn on b7, kings on their home squares, white to move.
    board = make_board({(1, 1): "P0", (7, 4): "K0", (0, 4): "K1"})
    g = Game(board=board, turn=0)
    g.move("b8Q")
    promoted = piece_at(g.board, "b8")
    assert promoted is not None and promoted.piecetype.value == "Q" and promoted.color == 0
    assert piece_at(g.board, "b7") is None


def test_promotion_required_on_last_rank(make_board):
    board = make_board({(1, 1): "P0", (7, 4): "K0", (0, 4): "K1"})
    g = Game(board=board, turn=0)
    with pytest.raises(ChessError.PromotionError):
        g.move("b8")  # reaching the back rank without declaring a promotion


def test_piece_not_found_error():
    g = Game()
    with pytest.raises(ChessError.PieceNotFoundError):
        g.move("Nf6")  # no white knight can reach f6 from the start


def test_move_into_check_is_illegal(make_board):
    # White king e1, white knight e2 pinned by black rook e8. Moving the knight
    # would expose the king along the e-file.
    board = make_board({(7, 4): "K0", (6, 4): "N0", (0, 4): "R1", (0, 7): "K1"})
    g = Game(board=board, turn=0)
    with pytest.raises(ChessError.MoveIntoCheckError):
        g.move("Nc3")
