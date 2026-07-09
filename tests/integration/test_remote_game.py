"""
Full-stack integration tests: remote Game client -> REST API -> Postgres.

The server runs the engine; the client sends moves and mirrors the returned
state. The client's ApiClient is wired to an in-process TestClient (see conftest's
``remote_client``), so these exercise the real FastAPI app and database.
"""

import pytest

from chesssnake import Color, MoveResult
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


def test_move_returns_move_result_and_updates_mirror(remote_client):
    g = make_game(remote_client, white_id=1, black_id=2, group_id=10, white_name="Bob", black_name="Phil")
    result = g.move("e4")
    assert isinstance(result, MoveResult)
    assert (result.from_square, result.to_square) == ("e2", "e4")
    # local mirror reflects the server-applied move
    assert g.to_move == Color.BLACK
    assert piece_at(g.board, "e4") is not None
    assert g.last_move is not None  # render highlight available


def test_move_persists_across_clients(remote_client):
    g = make_game(remote_client, white_id=3, black_id=4, group_id=10)
    g.move("e4")

    reloaded = make_game(remote_client, white_id=3, black_id=4, group_id=10)
    assert piece_at(reloaded.board, "e4") is not None
    assert reloaded.to_move == Color.BLACK


def test_refresh_picks_up_other_clients_move(remote_client):
    a = make_game(remote_client, white_id=5, black_id=6, group_id=10)
    b = make_game(remote_client, white_id=5, black_id=6, group_id=10)

    a.move("d4")  # client A moves
    assert b.to_move == Color.WHITE  # B hasn't refreshed yet
    b.refresh()
    assert b.to_move == Color.BLACK
    assert piece_at(b.board, "d4") is not None


def test_illegal_move_raises_chess_error(remote_client):
    g = make_game(remote_client, white_id=7, black_id=8, group_id=10)
    with pytest.raises(ChessError.InvalidNotationError):
        g.move("not-a-move")
    with pytest.raises(ChessError.PieceNotFoundError):
        g.move("e5")  # no white pawn can reach e5 in one move


def test_render_works_from_mirror(remote_client):
    g = make_game(remote_client, white_id=9, black_id=10, group_id=10, white_name="A", black_name="B")
    g.move("e4")
    img = g.render()  # uses the local mirror + last-move marker
    assert img.size == (1190, 644)


def test_draw_offer_persists(remote_client):
    g = make_game(remote_client, white_id=11, black_id=12, group_id=10)
    g.draw_offer(11)
    assert g.draw_offered_by == Color.WHITE

    reloaded = make_game(remote_client, white_id=11, black_id=12, group_id=10)
    assert reloaded.draw_offered_by == Color.WHITE


def test_new_remote_game_starts_fresh(remote_client):
    g = make_game(remote_client, white_id=13, black_id=14, group_id=10)
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
