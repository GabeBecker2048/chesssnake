"""
Full-stack integration tests: remote Game client -> REST API -> Postgres.

The client's ApiClient is wired to an in-process TestClient (see conftest's
``remote_client``), so these exercise the real FastAPI app and database.
"""

import pytest

from chesssnake import Color
from chesssnake.db import errors as GameError
from chesssnake.remote.game import Game, challenge, challenge_exists

pytestmark = pytest.mark.integration


def make_game(remote_client, **kwargs):
    return Game.remote(client=remote_client, **kwargs)


def piece_at(board, c_notation):
    from chesssnake import engine as Chess

    i, j = Chess.Board.get_coords(c_notation)
    return board[i, j].piece


def test_move_syncs_and_reloads(remote_client):
    g = make_game(
        remote_client, white_id=1, black_id=2, group_id=10, white_name="Bob", black_name="Phil", auto_sync=False
    )
    g.move("e4")
    g.move("e5")
    g.move("Nc3")
    g.sync()  # explicit sync (auto_sync disabled)

    reloaded = make_game(remote_client, white_id=1, black_id=2, group_id=10)
    assert str(reloaded) == str(g)
    assert reloaded.to_move == g.to_move == Color.BLACK
    assert reloaded.wname == "Bob"
    assert reloaded.bname == "Phil"


def test_auto_sync_persists_each_move(remote_client):
    g = make_game(remote_client, white_id=3, black_id=4, group_id=10)  # auto_sync defaults True
    g.move("e4")

    reloaded = make_game(remote_client, white_id=3, black_id=4, group_id=10)
    p = piece_at(reloaded.board, "e4")
    assert p is not None and p.piecetype.value == "P"
    assert reloaded.to_move == Color.BLACK


def test_context_manager_syncs_on_exit(remote_client):
    with make_game(remote_client, white_id=13, black_id=14, group_id=10, auto_sync=False) as g:
        g.move("d4")  # not synced yet (auto_sync off)

    # exiting the context should have pushed the state
    reloaded = make_game(remote_client, white_id=13, black_id=14, group_id=10)
    assert piece_at(reloaded.board, "d4") is not None


def test_en_passant_target_round_trips(remote_client):
    g = make_game(remote_client, white_id=5, black_id=6, group_id=10)
    g.move("e4")  # double pawn push sets the en-passant target

    reloaded = make_game(remote_client, white_id=5, black_id=6, group_id=10)
    assert reloaded.board.two_moveP is not None
    assert reloaded.board.two_moveP.c_notation == "e4"


def test_draw_offer_persists(remote_client):
    g = make_game(remote_client, white_id=7, black_id=8, group_id=10)
    g.draw_offer(7)

    reloaded = make_game(remote_client, white_id=7, black_id=8, group_id=10)
    assert reloaded.draw_offered_by == Color.WHITE


def test_new_remote_game_starts_fresh(remote_client):
    g = make_game(remote_client, white_id=11, black_id=12, group_id=10)
    assert g.to_move == Color.WHITE
    assert g.draw_offered_by is None
    assert g.is_over is False


def test_challenge_lifecycle(remote_client):
    assert challenge(100, 200, group_id=10, client=remote_client) is False
    assert challenge_exists(100, 200, group_id=10, client=remote_client) is not None

    assert challenge(200, 100, group_id=10, client=remote_client) is True
    assert challenge_exists(100, 200, group_id=10, client=remote_client) is None


def test_self_challenge_raises(remote_client):
    with pytest.raises(GameError.ChallengeError):
        challenge(300, 300, group_id=10, client=remote_client)
