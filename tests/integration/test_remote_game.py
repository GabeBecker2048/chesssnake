"""
Full-stack integration tests: remote Game client -> REST API -> database.

The server runs the engine; the client sends moves and mirrors the returned
state. The client's ApiClient is wired to an in-process TestClient (see conftest's
``remote_client``), so these exercise the real FastAPI app and database.
"""

import pytest

from chesssnake import Color, GameState, GameStatus, MoveResult, Termination, User
from chesssnake.db import errors as GameError
from chesssnake.engine import errors as ChessError
from chesssnake.remote.game import (
    Game,
    challenge,
    challenge_exists,
    create_user,
    get_user,
    record,
    user_for_identity,
)

pytestmark = pytest.mark.integration


def make_game(remote_client, white, black, **kwargs):
    kwargs.setdefault("group_id", 10)
    return Game.remote(white, black, client=remote_client, **kwargs)


def piece_at(board, c_notation):
    from chesssnake import engine as Chess

    i, j = Chess.Board.get_coords(c_notation)
    return board[i, j].piece


def _mate(game):
    for m in ["f3", "e5", "g4", "Qh4"]:  # fool's mate -> black wins
        game.move(m)


# --- users -----------------------------------------------------------------


def test_create_and_get_user(remote_client):
    alice = create_user("Alice", client=remote_client)
    assert isinstance(alice, User) and alice.role == "user"
    assert get_user(alice.id, client=remote_client) == alice
    assert get_user("alice", client=remote_client) == alice
    with pytest.raises(GameError.UserExistsError):
        create_user("ALICE", client=remote_client)
    with pytest.raises(GameError.UserNotFoundError):
        get_user("nobody", client=remote_client)


def test_user_for_identity_is_stable(remote_client):
    """What a bot calls on every interaction: same external id, same user."""
    first = user_for_identity("discord", 123456789012345678, "gabe", client=remote_client)
    again = user_for_identity("discord", "123456789012345678", "renamed-meanwhile", client=remote_client)
    assert again.id == first.id and again.username == "gabe"
    assert first.identities == [{"provider": "discord", "external_id": "123456789012345678"}]


def test_games_are_opened_by_username(remote_client, pair):
    g = make_game(remote_client, "white", "BLACK", player_id="white")
    assert (g.wid, g.bid, g.player_id) == (*pair, pair[0])
    assert (g.wname, g.bname) == ("white", "black")
    assert isinstance(g.id, int)
    with pytest.raises(GameError.UserNotFoundError):
        make_game(remote_client, "white", "nobody")


# --- games -----------------------------------------------------------------


def test_move_returns_result_and_bumps_version(remote_client, pair):
    g = make_game(remote_client, *pair)
    assert g.version == 1
    result = g.move("e4")
    assert isinstance(result, MoveResult)
    assert (result.from_square, result.to_square, result.san) == ("e2", "e4", "e4")
    assert result.state.id == g.id and result.state.white_name == "white"
    assert g.to_move == Color.BLACK
    assert g.version == 2
    assert piece_at(g.board, "e4") is not None  # local mirror updated
    assert g.last_move is not None


def test_move_persists_across_clients(remote_client, pair):
    g = make_game(remote_client, *pair)
    g.move("e4")
    reloaded = make_game(remote_client, *pair)
    assert reloaded.id == g.id
    assert piece_at(reloaded.board, "e4") is not None
    assert reloaded.to_move == Color.BLACK


def test_fen_accessors_mirror_from_wire(remote_client, pair):
    g = make_game(remote_client, *pair)
    assert g.castling_rights == "KQkq"
    assert g.en_passant is None
    assert g.fullmove_number == 1 and g.halfmove_clock == 0
    g.move("e4")  # double push -> en-passant target mirrored from the server's FEN
    assert g.en_passant == "e3"
    assert g.fen.split()[3] == "e3"


def test_refresh_picks_up_other_clients_move(remote_client, pair):
    a = make_game(remote_client, *pair)
    b = make_game(remote_client, *pair)
    a.move("d4")
    assert b.to_move == Color.WHITE  # not refreshed yet
    b.refresh()
    assert b.to_move == Color.BLACK and piece_at(b.board, "d4") is not None


def test_player_authorization(remote_client, pair):
    white_id, _ = pair
    # The white player's client may not move on black's turn.
    white = make_game(remote_client, *pair, player_id=white_id)
    white.move("e4")  # ok, white's turn
    with pytest.raises(GameError.NotYourTurnError):
        white.move("e5")  # now black's turn, but this client is white


def test_illegal_move_raises_chess_error(remote_client, pair):
    g = make_game(remote_client, *pair)
    with pytest.raises(ChessError.InvalidNotationError):
        g.move("not-a-move")
    with pytest.raises(ChessError.PieceNotFoundError):
        g.move("e5")


def test_resign_and_winner(remote_client, pair):
    g = make_game(remote_client, *pair)
    g.move("e4")
    g.resign(pair[1])  # black resigns
    assert g.result == GameStatus.WHITE_WON
    assert g.winner == Color.WHITE
    assert g.termination == Termination.RESIGNATION


def test_legal_moves_and_pgn_over_the_wire(remote_client, pair):
    g = make_game(remote_client, *pair)
    assert len(g.legal_moves()) == 20
    g.move("e4")
    g.move("e5")
    assert "1. e4 e5" in g.pgn()
    assert '[White "white"]' in g.pgn()
    assert [m["san"] for m in g.history()] == ["e4", "e5"]


def test_render_works_from_mirror(remote_client, pair):
    g = make_game(remote_client, *pair)
    g.move("e4")
    assert g.render().size == (1190, 644)


def test_draw_offer_persists(remote_client, pair):
    g = make_game(remote_client, *pair)
    g.draw_offer(pair[0])
    assert g.draw_offered_by == Color.WHITE
    reloaded = make_game(remote_client, *pair)
    assert reloaded.draw_offered_by == Color.WHITE


def test_challenge_lifecycle(remote_client, pair):
    a, b = pair
    assert challenge(a, b, group_id=10, client=remote_client) is False
    assert challenge_exists("white", "black", group_id=10, client=remote_client) is not None
    assert challenge("black", "white", group_id=10, client=remote_client) is True


def test_self_challenge_raises(remote_client):
    with pytest.raises(GameError.ChallengeError):
        challenge(300, 300, group_id=10, client=remote_client)


def test_rematch_starts_new_generation(remote_client, pair):
    g = make_game(remote_client, *pair)
    _mate(g)
    assert g.generation == 1 and g.is_over
    rematch = make_game(remote_client, *pair)
    assert rematch.generation == 2 and not rematch.is_over
    assert rematch.id != g.id


def test_a_stale_client_is_refused_by_the_server(remote_client, pair):
    """The server checks the generation itself: no session-side guard is involved here."""
    stale = make_game(remote_client, *pair)
    stale.resign(pair[0])
    live = make_game(remote_client, *pair)  # generation 2
    live.move("d4")
    assert live.version == stale.version, "so a version check alone would let it through"
    with pytest.raises(GameError.GenerationConflictError):
        stale.move("d5")
    assert [m["san"] for m in live.history()] == ["d4"]


def test_load_and_archive_past_games(remote_client, pair):
    g = make_game(remote_client, *pair)
    _mate(g)
    make_game(remote_client, *pair)  # start generation 2

    old = Game.remote(*pair, 10, generation=1, client=remote_client)
    assert old.generation == 1 and old.is_over and old.id == g.id
    assert "Qh4#" in old.pgn()

    archive = Game.archive("white", "black", 10, client=remote_client)
    assert all(isinstance(a, GameState) for a in archive)
    assert [a.generation for a in archive] == [1, 2]
    assert archive[0].id == g.id


def test_challenge_allowed_after_game_finishes(remote_client, pair):
    # a *finished* game between two players must not block a fresh challenge
    g = make_game(remote_client, *pair)
    _mate(g)
    assert challenge(*pair, group_id=10, client=remote_client) is False  # created, not blocked


def test_record_helper(remote_client, pair):
    w, b = pair
    g = make_game(remote_client, w, b)
    g.move("e4")
    g.resign(b)  # black resigns -> white wins
    rec = record("white", "black", group_id=10, client=remote_client)
    assert rec == {"player1": w, "player2": b, "player1_wins": 1, "player2_wins": 0, "draws": 0}


def test_current_games_and_exists_return_states(remote_client, pair):
    g = make_game(remote_client, *pair)
    current = remote_client.current_games(pair[0])
    assert [state.id for state in current] == [g.id]
    assert remote_client.game_exists(pair[1], pair[0], group_id=10).id == g.id
    assert remote_client.game_exists(pair[1], pair[0], group_id=11) is None
    assert remote_client.get_game(g.id).white_name == "white"
