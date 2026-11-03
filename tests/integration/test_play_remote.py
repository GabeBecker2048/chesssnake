"""
The ``chesssnake play`` session against the full stack: session -> client -> REST
API -> database, each player logged in as themselves.

:mod:`tests.unit.test_play` already covers the loop's behaviour on a local game.
What can only be checked here is that the same loop works when the engine lives
on the server: that moves persist, that the server's own refusals (out of turn,
a finished game) surface as readable lines rather than tracebacks, that
``refresh`` and ``new`` do what they claim, and that an expired login ends the
session instead of failing on every line.
"""

import io

import pytest

from chesssnake.play import run_session
from chesssnake.remote.game import Game

pytestmark = pytest.mark.integration


def play(lines, game, **kwargs):
    """Run a session over ``lines`` against ``game``; return ``(status, output)``."""
    out = io.StringIO()
    kwargs.setdefault("color", False)
    status = run_session(game, stdin=io.StringIO("\n".join(lines) + "\n"), stdout=out, **kwargs)
    return status, out.getvalue()


@pytest.fixture
def table(users, user_client, remote_client):
    """
    A game between alice (white) and bob, and a way to open it as either.

    ``table.open("alice")`` returns ``(game, player_id)`` ready for ``play``.
    """

    class Table:
        def __init__(self):
            self.ids = dict(zip(("alice", "bob"), users("alice", "bob"), strict=True))
            self.clients = {name: user_client(uid) for name, uid in self.ids.items()}
            self.game_id = remote_client.create_game("alice", "bob").id

        def open(self, name, game_id=None):
            game = Game.remote(game_id or self.game_id, client=self.clients[name])
            return game, self.ids[name]

    return Table()


def test_moves_persist_to_the_server(table):
    game, me = table.open("alice")
    _, out = play(["e4", "quit"], game, player_id=me)
    assert "played e4" in out
    theirs, them = table.open("bob")
    _, out = play(["e5", "pgn", "quit"], theirs, player_id=them)
    assert "1. e4 e5" in out


def test_version_is_tracked_across_the_session(table):
    game, me = table.open("alice")
    assert game.version == 1
    play(["e4", "quit"], game, player_id=me)
    assert game.version == 2


def test_the_server_refuses_moving_out_of_turn(table):
    """The server is the authority; its 403 must read as a line, not a traceback."""
    game, me = table.open("alice")
    _, out = play(["e4", "e5", "quit"], game, player_id=me)
    assert "NotYourTurnError" in out
    assert "e5" not in game.pgn()


def test_illegal_move_is_refused_by_the_server(table):
    game, me = table.open("alice")
    _, out = play(["Qh9", "e4", "quit"], game, player_id=me)
    assert "Error" in out and "1. e4" in game.pgn()


def test_refresh_picks_up_the_opponents_move(table):
    mine, me = table.open("alice")
    theirs, _ = table.open("bob")
    play(["e4", "quit"], mine, player_id=me)
    theirs.refresh()
    theirs.move("e5")
    assert mine.fen.split()[1] == "b", "the mirror is stale until asked"
    _, out = play(["refresh", "pgn", "quit"], mine, player_id=me)
    assert "1. e4 e5" in out and mine.fen.split()[1] == "w"


def test_informational_commands_do_not_show_a_stale_position(table):
    mine, me = table.open("alice")
    theirs, _ = table.open("bob")
    play(["e4", "quit"], mine, player_id=me)
    theirs.refresh()
    theirs.move("e5")
    _, out = play(["moves", "quit"], mine, player_id=me)
    assert "the position changed on the server" in out
    assert "Bc4" in out, "the bishop moves only exist in the post-e5 position"


def test_refresh_says_so_when_there_is_nothing_new(table):
    game, me = table.open("alice")
    _, out = play(["refresh", "quit"], game, player_id=me)
    assert "nothing new" in out


def test_the_header_names_the_game(table):
    game, me = table.open("alice")
    _, out = play(["board", "quit"], game, player_id=me)
    assert f"game {table.game_id}" in out and "alice (white) vs bob (black)" in out


def test_resign_through_the_session_is_persisted(table):
    game, me = table.open("bob")
    _, out = play(["resign", "quit"], game, player_id=me)
    assert "by resignation" in out
    reloaded, _ = table.open("alice")
    assert reloaded.is_over and reloaded.termination.value == "resignation"


def test_draw_agreement_through_two_sessions(table):
    mine, me = table.open("alice")
    play(["draw", "quit"], mine, player_id=me)
    theirs, them = table.open("bob")
    _, out = play(["accept", "quit"], theirs, player_id=them)
    assert "DRAW" in out


def test_after_the_game_actions_say_so_plainly(table):
    game, me = table.open("alice")
    _, out = play(["resign", "e4", "draw", "quit"], game, player_id=me)
    assert out.count("this game is over - `new` challenges your opponent to a rematch") == 2


# --- rematches go through challenges -----------------------------------------------


def test_new_challenges_and_the_opponents_new_accepts(table):
    mine, me = table.open("alice")
    _, out = play(["resign", "new", "quit"], mine, player_id=me)
    assert "rematch challenge" in out and "you play black" in out, "colours swap"

    theirs, them = table.open("bob")
    _, out = play(["new", "e4", "quit"], theirs, player_id=them)
    assert "rematch - game" in out and "bob (white) vs alice (black)" in out
    assert "played e4" in out


def test_new_twice_does_not_send_two_challenges(table):
    game, me = table.open("alice")
    _, out = play(["resign", "new", "new", "quit"], game, player_id=me)
    assert "already sent" in out


def test_a_rematch_started_elsewhere_is_noticed_and_joined(table):
    mine, me = table.open("alice")
    play(["resign", "quit"], mine, player_id=me)
    # The rematch starts without this session: bob challenges, alice accepts elsewhere.
    challenge = table.clients["bob"].challenge("alice")
    table.clients["alice"].accept_challenge(challenge)

    _, out = play(["e4", "new", "d4", "quit"], mine, player_id=me)
    assert "a rematch has started" in out
    assert "rematch - game" in out


def test_an_expired_login_ends_the_session(table):
    game, me = table.open("alice")
    game._client.logout()  # the token is revoked, as an expiry or a logout elsewhere would
    game._client.token = "css_revoked"
    status, out = play(["e4", "e5", "quit"], game, player_id=me)
    assert status == 1
    assert "chesssnake login" in out
    assert out.count("AuthError") == 1, "it stops at the first refusal instead of repeating it"
