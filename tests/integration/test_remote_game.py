"""
Full-stack integration tests: the Python client -> REST API -> database.

The server runs the engine; the client sends moves and mirrors the returned
state. Clients are wired to the in-process app through its TestClient, and act
as real, logged-in plain users unless a test is about administrators.
"""

import pytest

from chesssnake import Challenge, Color, Game, GameState, GameStatus, MoveResult, Termination, User, connect
from chesssnake.db import errors as GameError
from chesssnake.engine import errors as ChessError
from tests.integration.conftest import TEST_PASSWORD

pytestmark = pytest.mark.integration


@pytest.fixture
def players(users, user_client):
    """alice and bob, each with their own client: ``(alice_id, bob_id, alice, bob)``."""
    alice, bob = users("alice", "bob")
    return alice, bob, user_client(alice), user_client(bob)


@pytest.fixture
def match(players):
    """A game made the normal way: alice challenges as white, bob accepts."""
    alice_id, bob_id, alice, bob = players
    challenge = alice.challenge("bob", color="white")
    state = bob.accept_challenge(challenge.id)
    return Game.remote(state, client=alice), Game.remote(state.id, client=bob)


def piece_at(board, square):
    return board.piece_at(square)


def _mate(white, black):
    for game, move in ((white, "f3"), (black, "e5"), (white, "g4"), (black, "Qh4")):
        game.refresh()
        game.move(move)


# --- connecting --------------------------------------------------------------------


def test_connect_with_a_password(api_client, users):
    users("alice")
    client = connect("http://testserver", username="alice", password=TEST_PASSWORD, session=api_client)
    assert client.token.startswith("css_")
    me = client.me()
    assert isinstance(me, User) and me.username == "alice"
    with pytest.raises(GameError.AuthError):
        connect("http://testserver", username="alice", password="wrong-password", session=api_client)


def test_connect_finds_a_token_in_the_environment_or_the_stored_login(
    api_client, users, as_user, monkeypatch, tmp_path
):
    from chesssnake.remote import credentials

    (alice,) = users("alice")
    token = as_user(alice)["Authorization"].split()[1]
    monkeypatch.setenv("CHESSSNAKE_HOME", str(tmp_path))
    monkeypatch.delenv("CHESSSNAKE__CLIENT__TOKEN", raising=False)
    with pytest.raises(GameError.AuthError, match="chesssnake login"):
        connect("http://testserver", session=api_client)

    credentials.save("http://TESTSERVER/", token, "alice")
    assert connect("http://testserver", session=api_client).me().id == alice

    monkeypatch.setenv("CHESSSNAKE__CLIENT__TOKEN", "css_from-the-env-wins")
    assert connect("http://testserver", session=api_client).token == "css_from-the-env-wins"


def test_logout_revokes(api_client, users):
    users("alice")
    client = connect("http://testserver", username="alice", password=TEST_PASSWORD, session=api_client)
    token = client.token
    client.logout()
    client.token = token
    with pytest.raises(GameError.AuthError):
        client.me()


# --- the normal way to a game ----------------------------------------------------


def test_challenge_accept_play(players):
    alice_id, bob_id, alice, bob = players
    challenge = alice.challenge("bob", color="black")
    assert isinstance(challenge, Challenge) and challenge.challenged_name == "bob"
    assert [c.id for c in bob.challenges("incoming")] == [challenge.id]

    state = bob.accept_challenge(challenge)
    assert isinstance(state, GameState) and (state.white_id, state.black_id) == (bob_id, alice_id)
    as_bob = Game.remote(state, client=bob)
    as_alice = Game.remote(state.id, client=alice)
    assert (as_bob.white_name, as_bob.black_name, as_bob.id) == ("bob", "alice", state.id)

    result = as_bob.move("e4")
    assert isinstance(result, MoveResult) and result.state.version == 2
    as_alice.refresh()
    assert as_alice.to_move == Color.BLACK and piece_at(as_alice.board, "e4") is not None


def test_declining(players):
    _, _, alice, bob = players
    challenge = alice.challenge("bob")
    bob.decline_challenge(challenge)
    assert alice.challenges() == []
    with pytest.raises(GameError.ChallengeNotFoundError):
        bob.accept_challenge(challenge)


# --- playing ---------------------------------------------------------------------


def test_a_player_cannot_move_for_their_opponent(match):
    white, black = match
    white.move("e4")
    with pytest.raises(GameError.NotYourTurnError):
        white.move("e5")  # black's turn, and this client is white


def test_illegal_move_raises_chess_error(match):
    white, _ = match
    with pytest.raises(ChessError.InvalidNotationError):
        white.move("not-a-move")
    with pytest.raises(ChessError.PieceNotFoundError):
        white.move("e5")


def test_fen_accessors_mirror_from_wire(match):
    white, _ = match
    assert white.castling_rights == "KQkq" and white.en_passant is None
    white.move("e4")
    assert white.en_passant == "e3" and white.fen.split()[3] == "e3"


def test_resign_and_winner(match):
    white, black = match
    white.move("e4")
    black.refresh()
    black.resign()
    assert black.result == GameStatus.WHITE_WON and black.winner == Color.WHITE
    assert black.termination == Termination.RESIGNATION
    white.refresh()
    with pytest.raises(ChessError.GameOverError):
        white.move("d4")


def test_draw_by_agreement(match):
    white, black = match
    white.draw_offer()
    black.refresh()
    assert black.draw_offered_by == Color.WHITE
    black.draw_accept()
    assert black.result == GameStatus.DRAW


def test_reads_over_the_wire(match):
    white, black = match
    assert len(white.legal_moves()) == 20
    white.move("e4")
    black.refresh()
    black.move("e5")
    assert "1. e4 e5" in white.pgn() and '[White "alice"]' in white.pgn()
    assert [m["san"] for m in white.history()] == ["e4", "e5"]
    assert white.render().size == (1190, 644)


def test_lists_and_records(players, match):
    alice_id, bob_id, alice, bob = players
    white, black = match
    assert [g.id for g in alice.current_games()] == [white.id]
    _mate(white, black)
    assert alice.current_games() == []
    assert [g.id for g in bob.games_between("alice", "bob", status="finished")] == [white.id]
    assert alice.record("alice", "bob") == {
        "player1": alice_id,
        "player2": bob_id,
        "player1_wins": 0,
        "player2_wins": 1,
        "draws": 0,
    }


def test_a_finished_game_stays_readable_by_id(match):
    white, black = match
    _mate(white, black)
    again = Game.remote(white.id, client=white._client)
    assert again.is_over and again.result == GameStatus.BLACK_WON
    assert "Qh4#" in again.pgn()


def test_no_such_game(players):
    _, _, alice, _ = players
    with pytest.raises(GameError.GameNotFoundError):
        Game.remote(999999, client=alice)


# --- administrators --------------------------------------------------------------


def test_an_admin_creates_games_and_acts_for_players(remote_client, players):
    alice_id, bob_id, alice, _ = players
    state = remote_client.create_game("alice", "bob")
    with pytest.raises(GameError.ForbiddenError):
        alice.create_game("alice", "bob")
    as_bob = Game.remote(state.id, client=remote_client, player_id="bob")
    with pytest.raises(GameError.NotYourTurnError):
        as_bob.move("e4")  # it is white's move, and the admin is acting as bob
    as_alice = Game.remote(state.id, client=remote_client, player_id=alice_id)
    as_alice.move("e4")
    assert as_alice.version == 2


def test_a_bot_maps_its_own_ids_onto_users(remote_client):
    first = remote_client.get_or_create_user_by_identity("discord", "123456789012345678", "gabe")
    again = remote_client.get_or_create_user_by_identity("discord", "123456789012345678", "renamed-meanwhile")
    assert again.id == first.id and again.username == "gabe"
    other = remote_client.get_or_create_user_by_identity("discord", "42", "friend")
    challenge = remote_client.challenge(other.id, player_id=first.id)
    state = remote_client.accept_challenge(challenge.id)
    assert {state.white_id, state.black_id} == {first.id, other.id}
