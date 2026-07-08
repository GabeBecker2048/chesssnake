"""
Full-stack integration tests: remote Game client -> REST API -> Postgres.

The client's ApiClient is wired to an in-process TestClient (see conftest's
``remote_client``), so these exercise the real FastAPI app and database.
"""

import pytest

from chesssnake.remote.Game import Game, Challenge
from chesssnake.postgres import GameError


def make_game(remote_client, **kwargs):
    kwargs.setdefault("remote", True)
    return Game(_client=remote_client, **kwargs)


def piece_at(board, c_notation):
    from chesssnake.chesslib import Chess
    i, j = Chess.Board.get_coords(c_notation)
    return board[i, j].piece


def test_move_syncs_and_reloads(remote_client):
    g = make_game(remote_client, white_id=1, black_id=2, group_id=10, white_name="Bob", black_name="Phil")
    g.move("e4")
    g.move("e5")
    g.move("Nc3")
    g.sync()

    reloaded = make_game(remote_client, white_id=1, black_id=2, group_id=10)
    assert str(reloaded) == str(g)
    assert reloaded.turn == g.turn == 1
    assert reloaded.wname == "Bob"
    assert reloaded.bname == "Phil"


def test_auto_sync_persists_each_move(remote_client):
    g = make_game(remote_client, white_id=3, black_id=4, group_id=10, auto_sync=True)
    g.move("e4")

    reloaded = make_game(remote_client, white_id=3, black_id=4, group_id=10)
    p = piece_at(reloaded.board, "e4")
    assert p is not None and p.piecetype == "P"
    assert reloaded.turn == 1


def test_en_passant_target_round_trips(remote_client):
    g = make_game(remote_client, white_id=5, black_id=6, group_id=10, auto_sync=True)
    g.move("e4")  # double pawn push sets the en-passant target

    reloaded = make_game(remote_client, white_id=5, black_id=6, group_id=10)
    assert reloaded.board.two_moveP is not None
    assert reloaded.board.two_moveP.c_notation == "e4"


def test_draw_offer_persists(remote_client):
    g = make_game(remote_client, white_id=7, black_id=8, group_id=10, auto_sync=True)
    g.draw_offer(7)

    reloaded = make_game(remote_client, white_id=7, black_id=8, group_id=10)
    assert reloaded.draw == 0


def test_new_remote_game_starts_fresh(remote_client):
    g = make_game(remote_client, white_id=11, black_id=12, group_id=10)
    assert g.turn == 0
    assert g.draw is None
    assert g.board.status == 0


def test_challenge_lifecycle(remote_client):
    assert Challenge.challenge(100, 200, gid=10, _client=remote_client) is False
    assert Challenge.exists(100, 200, gid=10, _client=remote_client) is not None

    assert Challenge.challenge(200, 100, gid=10, _client=remote_client) is True
    assert Challenge.exists(100, 200, gid=10, _client=remote_client) is None


def test_self_challenge_raises(remote_client):
    with pytest.raises(GameError.ChallengeError):
        Challenge.challenge(300, 300, gid=10, _client=remote_client)
