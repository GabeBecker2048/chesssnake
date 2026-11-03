"""Unit tests for the public ``chesssnake.Game`` (local mode, no server)."""

from chesssnake import Color, Game, GameStatus, MoveResult


def test_local_move_returns_move_result():
    g = Game.local("Bob", "Phil")
    result = g.move("e4")
    assert isinstance(result, MoveResult)
    assert (result.from_square, result.to_square) == ("e2", "e4")
    assert result.check is False
    assert g.to_move == Color.BLACK


def test_local_game_accessors_and_render():
    g = Game.local("A", "B")
    assert g.is_remote is False
    assert g.result == GameStatus.IN_PLAY
    g.move("e4")
    img = g.render()  # local render works with last-move highlight
    assert img.size == (1190, 644)


def test_local_checkmate_reports_winner():
    g = Game.local()
    for mv in ["f3", "e5", "g4", "Qh4"]:  # fool's mate
        g.move(mv)
    assert g.is_over is True
    assert g.result == GameStatus.BLACK_WON
    assert g.winner == Color.BLACK


def test_local_state_has_names_but_no_server_id():
    result = Game.local("Bob", "Phil").move("e4")
    assert result.state.id is None
    assert (result.state.white_name, result.state.black_name) == ("Bob", "Phil")
    assert result.state.started_at is None


def test_wire_payloads_ignore_fields_they_do_not_know():
    """A field added to the server later must not break an older client."""
    from chesssnake import GameState, User

    state = GameState.from_dict({"fen": "x", "status": 0, "version": 1, "added_in_a_later_version": True})
    assert state.fen == "x" and state.id is None
    user = User.from_dict({"id": 1, "username": "ann", "role": "admin", "avatar": "later"})
    assert (user.id, user.role, user.identities) == (1, "admin", [])
