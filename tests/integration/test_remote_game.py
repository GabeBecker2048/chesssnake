"""
Full-stack integration tests: remote Game client -> REST API -> Postgres.

The server runs the engine; the client sends moves and mirrors the returned
state. The client's ApiClient is wired to an in-process TestClient (see conftest's
``remote_client``), so these exercise the real FastAPI app and database.
"""

import pytest

from chesssnake import Color, GameStatus, MoveResult, Termination
from chesssnake.db import errors as GameError
from chesssnake.engine import errors as ChessError
from chesssnake.remote.game import Game, challenge, challenge_exists

pytestmark = pytest.mark.integration


def make_game(remote_client, **kwargs):
    return Game.remote(client=remote_client, **kwargs)


def piece_at(board, c_notation):
    from chesssnake import engine as Chess

    i, j = Chess.Board.get_coords(c_notation)
    return board[i, j].piece


def test_move_returns_result_and_bumps_version(remote_client):
    g = make_game(remote_client, white_id=1, black_id=2, group_id=10, white_name="Bob", black_name="Phil")
    assert g.version == 1
    result = g.move("e4")
    assert isinstance(result, MoveResult)
    assert (result.from_square, result.to_square, result.san) == ("e2", "e4", "e4")
    assert g.to_move == Color.BLACK
    assert g.version == 2
    assert piece_at(g.board, "e4") is not None  # local mirror updated
    assert g.last_move is not None


def test_move_persists_across_clients(remote_client):
    g = make_game(remote_client, white_id=3, black_id=4, group_id=10)
    g.move("e4")
    reloaded = make_game(remote_client, white_id=3, black_id=4, group_id=10)
    assert piece_at(reloaded.board, "e4") is not None
    assert reloaded.to_move == Color.BLACK


def test_refresh_picks_up_other_clients_move(remote_client):
    a = make_game(remote_client, white_id=5, black_id=6, group_id=10)
    b = make_game(remote_client, white_id=5, black_id=6, group_id=10)
    a.move("d4")
    assert b.to_move == Color.WHITE  # not refreshed yet
    b.refresh()
    assert b.to_move == Color.BLACK and piece_at(b.board, "d4") is not None


def test_player_authorization(remote_client):
    # The white player's client may not move on black's turn.
    white = make_game(remote_client, white_id=7, black_id=8, group_id=10, player_id=7)
    white.move("e4")  # ok, white's turn
    with pytest.raises(GameError.NotYourTurnError):
        white.move("e5")  # now black's turn, but this client is player 7 (white)


def test_illegal_move_raises_chess_error(remote_client):
    g = make_game(remote_client, white_id=9, black_id=10, group_id=10)
    with pytest.raises(ChessError.InvalidNotationError):
        g.move("not-a-move")
    with pytest.raises(ChessError.PieceNotFoundError):
        g.move("e5")


def test_resign_and_winner(remote_client):
    g = make_game(remote_client, white_id=11, black_id=12, group_id=10)
    g.move("e4")
    g.resign(12)  # black resigns
    assert g.result == GameStatus.WHITE_WON
    assert g.winner == Color.WHITE
    assert g.termination == Termination.RESIGNATION


def test_legal_moves_and_pgn_over_the_wire(remote_client):
    g = make_game(remote_client, white_id=13, black_id=14, group_id=10, white_name="A", black_name="B")
    assert len(g.legal_moves()) == 20
    g.move("e4")
    g.move("e5")
    assert "1. e4 e5" in g.pgn()
    assert [m["san"] for m in g.history()] == ["e4", "e5"]


def test_render_works_from_mirror(remote_client):
    g = make_game(remote_client, white_id=15, black_id=16, group_id=10, white_name="A", black_name="B")
    g.move("e4")
    assert g.render().size == (1190, 644)


def test_draw_offer_persists(remote_client):
    g = make_game(remote_client, white_id=17, black_id=18, group_id=10)
    g.draw_offer(17)
    assert g.draw_offered_by == Color.WHITE
    reloaded = make_game(remote_client, white_id=17, black_id=18, group_id=10)
    assert reloaded.draw_offered_by == Color.WHITE


def test_challenge_lifecycle(remote_client):
    assert challenge(100, 200, group_id=10, client=remote_client) is False
    assert challenge_exists(100, 200, group_id=10, client=remote_client) is not None
    assert challenge(200, 100, group_id=10, client=remote_client) is True


def test_self_challenge_raises(remote_client):
    with pytest.raises(GameError.ChallengeError):
        challenge(300, 300, group_id=10, client=remote_client)


def _mate(game):
    for m in ["f3", "e5", "g4", "Qh4"]:  # fool's mate -> black wins
        game.move(m)


def test_rematch_starts_new_generation(remote_client):
    g = make_game(remote_client, white_id=20, black_id=21, group_id=10)
    _mate(g)
    assert g.generation == 1 and g.is_over
    rematch = make_game(remote_client, white_id=20, black_id=21, group_id=10)
    assert rematch.generation == 2 and not rematch.is_over


def test_load_and_archive_past_games(remote_client):
    g = make_game(remote_client, white_id=22, black_id=23, group_id=10)
    _mate(g)
    make_game(remote_client, white_id=22, black_id=23, group_id=10)  # start generation 2

    old = Game.remote(22, 23, 10, generation=1, client=remote_client)
    assert old.generation == 1 and old.is_over
    assert "Qh4#" in old.pgn()

    archive = Game.archive(22, 23, 10, client=remote_client)
    assert [a["generation"] for a in archive] == [1, 2]


def test_challenge_allowed_after_game_finishes(remote_client):
    # a *finished* game between two players must not block a fresh challenge
    g = make_game(remote_client, white_id=30, black_id=31, group_id=10)
    _mate(g)
    assert challenge(30, 31, group_id=10, client=remote_client) is False  # created, not blocked
