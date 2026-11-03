"""
The ``chesssnake play`` session against the full stack: session -> client -> REST
API -> database.

:mod:`tests.unit.test_play` already covers the loop's behaviour on a local game.
What can only be checked here is that the same loop works when the engine lives
on the server — that moves persist, that the server's own refusals (out of turn,
stale version) surface as readable lines rather than tracebacks, and that
``refresh`` and ``new`` do what they claim.
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


def make_game(remote_client, pair, **kwargs):
    kwargs.setdefault("group_id", 70)
    return Game.remote(*pair, client=remote_client, **kwargs)


def test_moves_persist_to_the_server(remote_client, pair):
    W, B = pair
    game = make_game(remote_client, pair)
    _, out = play(["e4", "e5", "quit"], game)
    assert "played e4" in out
    assert "1. e4 e5" in game.pgn()

    # A second client sees them: the moves went to the database, not just the mirror.
    reloaded = make_game(remote_client, pair)
    assert reloaded.fen == game.fen
    assert "1. e4 e5" in reloaded.pgn()


def test_version_is_tracked_across_the_session(remote_client, pair):
    W, B = pair
    game = make_game(remote_client, pair)
    assert game.version == 1
    play(["e4", "e5", "Nf3", "quit"], game)
    assert game.version == 4


def test_server_rejects_moving_out_of_turn(remote_client, pair):
    """The server is the authority; its 403 must read as a line, not a traceback."""
    W, B = pair
    game = make_game(remote_client, pair, player_id=W)
    _, out = play(["e4", "e5", "quit"], game, player_id=W)
    assert "NotYourTurnError" in out
    # A remote game keeps no local move_history — it proxies to the server, which
    # is also the only account of the game that matters here.
    assert "1. e4" in game.pgn()
    assert "e5" not in game.pgn()


def test_illegal_move_is_refused_by_the_server(remote_client, pair):
    W, B = pair
    game = make_game(remote_client, pair)
    _, out = play(["Qh9", "e4", "quit"], game)
    assert "Error" in out
    assert "1. e4" in game.pgn()


def test_refresh_picks_up_the_opponents_move(remote_client, pair):
    """There is no push channel, so `refresh` is how the other side's move arrives."""
    W, B = pair
    mine = make_game(remote_client, pair, player_id=W)
    theirs = make_game(remote_client, pair, player_id=B)

    play(["e4", "quit"], mine, player_id=W)
    theirs.refresh()
    theirs.move("e5")

    # The local mirror is stale until asked: that is exactly why `refresh` exists.
    # Black is still to move in the mirror, though the server has already had e5.
    assert mine.fen.split()[1] == "b"
    _, out = play(["refresh", "pgn", "quit"], mine, player_id=W)
    assert "1. e4 e5" in out
    assert mine.fen.split()[1] == "w", "after refresh the mirror shows white to move"


def test_resign_through_the_session_is_persisted(remote_client, pair):
    W, B = pair
    game = make_game(remote_client, pair)
    _, out = play(["resign", "quit"], game)
    assert "by resignation" in out

    reloaded = Game.remote(W, B, 70, generation=1, client=remote_client)
    assert reloaded.is_over
    assert reloaded.termination.value == "resignation"


def test_draw_agreement_through_the_session(remote_client, pair):
    W, B = pair
    game = make_game(remote_client, pair)
    _, out = play(["draw", "accept", "quit"], game)
    assert "DRAW" in out
    assert game.is_over


def test_new_starts_a_rematch_generation(remote_client, pair):
    W, B = pair
    game = make_game(remote_client, pair)
    _, out = play(["resign", "new", "quit"], game)
    assert "rematch - generation 2" in out

    archive = Game.archive(W, B, 70, client=remote_client)
    assert len(archive) == 2


def test_session_reports_the_generation_for_remote_games(remote_client, pair):
    W, B = pair
    game = make_game(remote_client, pair)
    _, out = play(["board", "quit"], game)
    assert "gen 1" in out


def test_informational_commands_do_not_show_a_stale_position(remote_client, pair):
    """
    Regression: the board and ``fen`` come from the local mirror while ``moves``
    and ``pgn`` are proxied to the server, so once the opponent moved the two
    disagreed — ``moves`` listed the legal moves of a position not on screen.
    Every informational command now syncs first.
    """
    W, B = pair
    mine = make_game(remote_client, pair, player_id=W)
    theirs = make_game(remote_client, pair, player_id=B)

    play(["e4", "quit"], mine, player_id=W)
    theirs.refresh()
    theirs.move("e5")  # mine is told nothing

    _, out = play(["moves", "quit"], mine, player_id=W)
    assert "the position changed on the server" in out
    # White is to move again, so the listed moves must be White's, and the board
    # that was redrawn alongside them must be the position they belong to.
    assert mine.fen.split()[1] == "w"
    assert "Bc4" in out, "the bishop moves only exist in the post-e5 position"


def test_fen_and_board_also_sync(remote_client, pair):
    W, B = pair
    mine = make_game(remote_client, pair, player_id=W)
    theirs = make_game(remote_client, pair, player_id=B)

    play(["e4", "quit"], mine, player_id=W)
    theirs.refresh()
    theirs.move("c5")

    _, out = play(["fen", "quit"], mine, player_id=W)
    assert "2c5" not in out  # sanity: we are reading a FEN, not a move list
    assert mine.fen.split()[1] == "w"
    assert "the position changed on the server" in out


def test_refresh_says_so_when_there_is_nothing_new(remote_client, pair):
    W, B = pair
    game = make_game(remote_client, pair)
    _, out = play(["refresh", "quit"], game)
    assert "nothing new" in out


# --- the cross-generation hazard --------------------------------------------


def test_move_after_the_game_ends_says_so_plainly(remote_client, pair):
    """Not a VersionConflictError, and not a traceback: a sentence and a way out."""
    W, B = pair
    game = make_game(remote_client, pair)
    _, out = play(["resign", "e4", "quit"], game)
    assert "this game is over - `new` starts a rematch" in out
    assert "VersionConflict" not in out


def test_a_rematch_started_elsewhere_is_explained(remote_client, pair):
    """
    Regression for the reported bug. A session sitting in a finished game while
    someone else re-opened the triple used to get
    ``VersionConflictError: Expected version 5 but the game is at version 1``.
    """
    W, B = pair
    mine = make_game(remote_client, pair)
    mine.move("d4")
    mine.move("d5")
    mine.resign(B)

    # Someone else re-opens the finished triple, which starts generation 2.
    other = make_game(remote_client, pair)
    assert other.generation == 2

    _, out = play(["e4", "quit"], mine)
    assert "a rematch has started elsewhere (generation 2)" in out
    assert "generation 1" in out
    assert "VersionConflict" not in out


def test_a_stale_session_cannot_write_into_the_rematch(remote_client, pair):
    """
    The hazard behind that error. Before 0.11.0 the server's mutating routes
    ignored the generation and acted on the *current* game, so a stale session's
    legal move landed in the rematch. The server now refuses it too; the session
    still refuses first, with a sentence rather than an error.
    """
    W, B = pair
    stale = make_game(remote_client, pair)
    stale.resign(W)  # generation 1 is over at version 2

    live = make_game(remote_client, pair)  # generation 2
    live.move("d4")  # also version 2 -- so a version check alone would pass
    assert live.generation == 2 and live.version == stale.version

    # d5 is legal in generation 2. Without the guard this is applied there.
    _, out = play(["d5", "quit"], stale)
    assert "a rematch has started elsewhere" in out

    fresh = Game.remote(W, B, 70, client=remote_client)
    assert "d5" not in fresh.pgn(), "the stale session must not reach the rematch"
    assert "1. d4 *" in fresh.pgn()


def test_new_joins_the_rematch_that_started_elsewhere(remote_client, pair):
    """The guard names `new` as the way out, so `new` has to work from there."""
    W, B = pair
    mine = make_game(remote_client, pair)
    mine.resign(W)
    make_game(remote_client, pair)  # someone starts generation 2

    _, out = play(["e4", "new", "d4", "quit"], mine)
    assert "a rematch has started elsewhere" in out
    assert "rematch - generation 2" in out
    assert "played d4" in out


def test_informational_commands_report_the_rematch_too(remote_client, pair):
    W, B = pair
    mine = make_game(remote_client, pair)
    mine.resign(W)
    make_game(remote_client, pair)

    _, out = play(["moves", "quit"], mine)
    assert "a rematch has started elsewhere" in out


def test_refresh_reports_the_rematch_rather_than_nothing_new(remote_client, pair):
    """`refresh` is the command you reach for when confused; it must not mislead."""
    W, B = pair
    mine = make_game(remote_client, pair)
    mine.resign(W)
    make_game(remote_client, pair)

    _, out = play(["refresh", "quit"], mine)
    assert "a rematch has started elsewhere" in out
    assert "nothing new" not in out


@pytest.mark.parametrize("command", ["draw", "accept", "decline", "resign"])
def test_every_action_is_guarded_not_just_moves(remote_client, command, pair):
    """All of the actions route through allow_action, so none can reach a dead game."""
    game = make_game(remote_client, pair)
    game.resign(pair[1])
    _, out = play([command, "quit"], game)
    assert "this game is over - `new` starts a rematch" in out
    assert "VersionConflict" not in out


# --- auth -------------------------------------------------------------------


@pytest.fixture
def auth_app(api_client, settings):
    """
    A second app requiring an API key, sharing the already-initialized pool.

    Mirrors ``test_api.py::auth_client``: settings live on the app rather than in
    the environment, so two apps with different auth can coexist.
    """
    from fastapi.testclient import TestClient

    from chesssnake.api.server import create_app
    from chesssnake.config import Settings

    auth = Settings(
        api={"require_auth": True, "api_key": "s3cret"},
        database={"url": settings.database.url},
    )
    with TestClient(create_app(auth)) as client:
        yield client


def test_play_works_against_an_endpoint_that_requires_a_key(auth_app, pair):
    from chesssnake.remote.client import ApiClient

    client = ApiClient("http://testserver", session=auth_app, api_key="s3cret")
    game = Game.remote(*pair, 70, client=client)
    _, out = play(["d4", "pgn", "quit"], game)
    assert "played d4" in out
    assert "1. d4" in out


def test_play_without_the_key_fails_loudly_not_silently(auth_app, pair):
    """A missing key must surface as an auth error, not an empty board."""
    from chesssnake.db.errors import GameError
    from chesssnake.remote.client import ApiClient

    client = ApiClient("http://testserver", session=auth_app)  # no api_key
    with pytest.raises(GameError, match="API key"):
        Game.remote(*pair, 70, client=client)
