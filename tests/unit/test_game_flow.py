"""Unit tests for the engine Game controller: turns, errors, and draw offers."""

import pytest

from chesssnake import Color, GameStatus
from chesssnake.engine import Game
from chesssnake.engine import errors as ChessError


def test_new_game_defaults():
    g = Game(white_name="A", black_name="B")
    assert g.turn == 0  # white to move
    assert g.draw is None
    assert g.board.status == 0  # in play


def test_accessors_ongoing_game():
    g = Game(white_name="A", black_name="B")
    assert g.to_move == Color.WHITE
    assert g.is_over is False
    assert g.result == GameStatus.IN_PLAY
    assert g.winner is None
    assert g.draw_offered_by is None
    g.move("e4")
    assert g.to_move == Color.BLACK


def test_accessors_report_checkmate_winner():
    g = Game()
    for m in ["f3", "e5", "g4", "Qh4"]:  # fool's mate — black (Qh4#) wins
        g.move(m)
    assert g.is_over is True
    assert g.result == GameStatus.BLACK_WON
    assert g.winner == Color.BLACK


def test_move_returns_the_move_played():
    g = Game()
    m = g.move("e4")
    assert m is g.last_move
    assert m.to.c_notation == "e4"


def test_render_returns_an_image():
    g = Game(white_name="A", black_name="B")
    g.move("e4")
    img = g.render()
    assert img.size == (1190, 644)


def test_move_alternates_turn():
    g = Game()
    assert g.turn == 0
    g.move("e4")
    assert g.turn == 1
    g.move("e5")
    assert g.turn == 0


def test_invalid_notation_raises():
    g = Game()
    with pytest.raises(ChessError.InvalidNotationError):
        g.move("not-a-move")


def test_move_after_game_over_raises():
    g = Game()
    g.board.status = 1  # pretend the game ended
    with pytest.raises(ChessError.GameOverError):
        g.move("e4")


def test_is_players_turn():
    g = Game(white_id=10, black_id=20)
    assert g.is_players_turn(10) is True
    assert g.is_players_turn(20) is False
    g.move("e4")
    assert g.is_players_turn(20) is True
    assert g.is_players_turn(10) is False


def test_draw_offer_and_accept_ends_in_draw():
    g = Game(white_id=10, black_id=20)
    g.draw_offer(10)  # white (to move) offers
    assert g.draw == 0
    assert g.draw_offered_by == Color.WHITE
    g.draw_offer(20)  # black offering back accepts the draw
    assert g.board.status == 3  # draw / stalemate status
    assert g.result == GameStatus.DRAW
    assert g.winner is None


def test_double_draw_offer_raises():
    g = Game(white_id=10, black_id=20)
    g.draw_offer(10)
    with pytest.raises(ChessError.DrawAlreadyOfferedError):
        g.draw_offer(10)


def test_draw_offer_out_of_turn_raises():
    g = Game(white_id=10, black_id=20)  # white to move
    with pytest.raises(ChessError.DrawWrongTurnError):
        g.draw_offer(20)  # black offers out of turn


def test_decline_with_no_offer_raises():
    g = Game(white_id=10, black_id=20)
    with pytest.raises(ChessError.DrawNotOfferedError):
        g.draw_decline(10)


def test_draw_decline_clears_offer():
    g = Game(white_id=10, black_id=20)
    g.draw_offer(10)
    g.draw_decline(20)
    assert g.draw is None
    assert g.board.status == 0
