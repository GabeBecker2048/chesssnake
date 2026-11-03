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


def make_game(remote_client, **kwargs):
    kwargs.setdefault("group_id", 70)
    return Game.remote(client=remote_client, **kwargs)


def test_moves_persist_to_the_server(remote_client):
    game = make_game(remote_client, white_id=1, black_id=2)
    _, out = play(["e4", "e5", "quit"], game)
    assert "played e4" in out
    assert "1. e4 e5" in game.pgn()

    # A second client sees them: the moves went to the database, not just the mirror.
    reloaded = make_game(remote_client, white_id=1, black_id=2)
    assert reloaded.fen == game.fen
    assert "1. e4 e5" in reloaded.pgn()


def test_version_is_tracked_across_the_session(remote_client):
    game = make_game(remote_client, white_id=3, black_id=4)
    assert game.version == 1
    play(["e4", "e5", "Nf3", "quit"], game)
    assert game.version == 4


def test_server_rejects_moving_out_of_turn(remote_client):
    """The server is the authority; its 403 must read as a line, not a traceback."""
    game = make_game(remote_client, white_id=5, black_id=6, player_id=5)
    _, out = play(["e4", "e5", "quit"], game, player_id=5)
    assert "NotYourTurnError" in out
    # A remote game keeps no local move_history — it proxies to the server, which
    # is also the only account of the game that matters here.
    assert "1. e4" in game.pgn()
    assert "e5" not in game.pgn()


def test_illegal_move_is_refused_by_the_server(remote_client):
    game = make_game(remote_client, white_id=7, black_id=8)
    _, out = play(["Qh9", "e4", "quit"], game)
    assert "Error" in out
    assert "1. e4" in game.pgn()


def test_refresh_picks_up_the_opponents_move(remote_client):
    """There is no push channel, so `refresh` is how the other side's move arrives."""
    mine = make_game(remote_client, white_id=9, black_id=10, player_id=9)
    theirs = make_game(remote_client, white_id=9, black_id=10, player_id=10)

    play(["e4", "quit"], mine, player_id=9)
    theirs.refresh()
    theirs.move("e5")

    # The local mirror is stale until asked: that is exactly why `refresh` exists.
    # Black is still to move in the mirror, though the server has already had e5.
    assert mine.fen.split()[1] == "b"
    _, out = play(["refresh", "pgn", "quit"], mine, player_id=9)
    assert "1. e4 e5" in out
    assert mine.fen.split()[1] == "w", "after refresh the mirror shows white to move"


def test_resign_through_the_session_is_persisted(remote_client):
    game = make_game(remote_client, white_id=11, black_id=12)
    _, out = play(["resign", "quit"], game)
    assert "by resignation" in out

    reloaded = Game.remote(11, 12, 70, generation=1, client=remote_client)
    assert reloaded.is_over
    assert reloaded.termination.value == "resignation"


def test_draw_agreement_through_the_session(remote_client):
    game = make_game(remote_client, white_id=13, black_id=14)
    _, out = play(["draw", "accept", "quit"], game)
    assert "DRAW" in out
    assert game.is_over


def test_new_starts_a_rematch_generation(remote_client):
    game = make_game(remote_client, white_id=15, black_id=16)
    _, out = play(["resign", "new", "quit"], game)
    assert "rematch - generation 2" in out

    archive = Game.archive(15, 16, 70, client=remote_client)
    assert len(archive) == 2


def test_session_reports_the_generation_for_remote_games(remote_client):
    game = make_game(remote_client, white_id=17, black_id=18)
    _, out = play(["board", "quit"], game)
    assert "gen 1" in out


def test_informational_commands_do_not_show_a_stale_position(remote_client):
    """
    Regression: the board and ``fen`` come from the local mirror while ``moves``
    and ``pgn`` are proxied to the server, so once the opponent moved the two
    disagreed — ``moves`` listed the legal moves of a position not on screen.
    Every informational command now syncs first.
    """
    mine = make_game(remote_client, white_id=19, black_id=20, player_id=19)
    theirs = make_game(remote_client, white_id=19, black_id=20, player_id=20)

    play(["e4", "quit"], mine, player_id=19)
    theirs.refresh()
    theirs.move("e5")  # mine is told nothing

    _, out = play(["moves", "quit"], mine, player_id=19)
    assert "the position changed on the server" in out
    # White is to move again, so the listed moves must be White's, and the board
    # that was redrawn alongside them must be the position they belong to.
    assert mine.fen.split()[1] == "w"
    assert "Bc4" in out, "the bishop moves only exist in the post-e5 position"


def test_fen_and_board_also_sync(remote_client):
    mine = make_game(remote_client, white_id=21, black_id=22, player_id=21)
    theirs = make_game(remote_client, white_id=21, black_id=22, player_id=22)

    play(["e4", "quit"], mine, player_id=21)
    theirs.refresh()
    theirs.move("c5")

    _, out = play(["fen", "quit"], mine, player_id=21)
    assert "2c5" not in out  # sanity: we are reading a FEN, not a move list
    assert mine.fen.split()[1] == "w"
    assert "the position changed on the server" in out


def test_refresh_says_so_when_there_is_nothing_new(remote_client):
    game = make_game(remote_client, white_id=23, black_id=24)
    _, out = play(["refresh", "quit"], game)
    assert "nothing new" in out


# --- the cross-generation hazard --------------------------------------------


def test_move_after_the_game_ends_says_so_plainly(remote_client):
    """Not a VersionConflictError, and not a traceback: a sentence and a way out."""
    game = make_game(remote_client, white_id=25, black_id=26)
    _, out = play(["resign", "e4", "quit"], game)
    assert "this game is over - `new` starts a rematch" in out
    assert "VersionConflict" not in out


def test_a_rematch_started_elsewhere_is_explained(remote_client):
    """
    Regression for the reported bug. A session sitting in a finished game while
    someone else re-opened the triple used to get
    ``VersionConflictError: Expected version 5 but the game is at version 1``.
    """
    mine = make_game(remote_client, white_id=27, black_id=28)
    mine.move("d4")
    mine.move("d5")
    mine.resign(28)

    # Someone else re-opens the finished triple, which starts generation 2.
    other = make_game(remote_client, white_id=27, black_id=28)
    assert other.generation == 2

    _, out = play(["e4", "quit"], mine)
    assert "a rematch has started elsewhere (generation 2)" in out
    assert "generation 1" in out
    assert "VersionConflict" not in out


def test_a_stale_session_cannot_write_into_the_rematch(remote_client):
    """
    The hazard behind that error, and the reason the guard refuses rather than
    merely explaining: the server's mutating routes ignore the generation and act
    on the *current* game, so a stale session's legal move lands in the rematch.
    Verified against a live endpoint before this guard existed.
    """
    stale = make_game(remote_client, white_id=29, black_id=30)
    stale.resign(29)  # generation 1 is over at version 2

    live = make_game(remote_client, white_id=29, black_id=30)  # generation 2
    live.move("d4")  # also version 2 -- so a version check alone would pass
    assert live.generation == 2 and live.version == stale.version

    # d5 is legal in generation 2. Without the guard this is applied there.
    _, out = play(["d5", "quit"], stale)
    assert "a rematch has started elsewhere" in out

    fresh = Game.remote(29, 30, 70, client=remote_client)
    assert "d5" not in fresh.pgn(), "the stale session must not reach the rematch"
    assert "1. d4 *" in fresh.pgn()


def test_new_joins_the_rematch_that_started_elsewhere(remote_client):
    """The guard names `new` as the way out, so `new` has to work from there."""
    mine = make_game(remote_client, white_id=31, black_id=32)
    mine.resign(31)
    make_game(remote_client, white_id=31, black_id=32)  # someone starts generation 2

    _, out = play(["e4", "new", "d4", "quit"], mine)
    assert "a rematch has started elsewhere" in out
    assert "rematch - generation 2" in out
    assert "played d4" in out


def test_informational_commands_report_the_rematch_too(remote_client):
    mine = make_game(remote_client, white_id=33, black_id=34)
    mine.resign(33)
    make_game(remote_client, white_id=33, black_id=34)

    _, out = play(["moves", "quit"], mine)
    assert "a rematch has started elsewhere" in out


def test_refresh_reports_the_rematch_rather_than_nothing_new(remote_client):
    """`refresh` is the command you reach for when confused; it must not mislead."""
    mine = make_game(remote_client, white_id=35, black_id=36)
    mine.resign(35)
    make_game(remote_client, white_id=35, black_id=36)

    _, out = play(["refresh", "quit"], mine)
    assert "a rematch has started elsewhere" in out
    assert "nothing new" not in out


# Explicit ids rather than a hash of the command: PYTHONHASHSEED is randomized,
# so a derived id would pick a different game on every run.
@pytest.mark.parametrize(
    ("command", "white_id"),
    [("draw", 37), ("accept", 38), ("decline", 39), ("resign", 40)],
)
def test_every_action_is_guarded_not_just_moves(remote_client, command, white_id):
    """All of the actions route through allow_action, so none can reach a dead game."""
    game = make_game(remote_client, white_id=white_id, black_id=99)
    game.resign(99)
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


def test_play_works_against_an_endpoint_that_requires_a_key(auth_app):
    from chesssnake.remote.client import ApiClient

    client = ApiClient("http://testserver", session=auth_app, api_key="s3cret")
    game = Game.remote(41, 42, 70, client=client)
    _, out = play(["d4", "pgn", "quit"], game)
    assert "played d4" in out
    assert "1. d4" in out


def test_play_without_the_key_fails_loudly_not_silently(auth_app):
    """A missing key must surface as an auth error, not an empty board."""
    from chesssnake.db.errors import GameError
    from chesssnake.remote.client import ApiClient

    client = ApiClient("http://testserver", session=auth_app)  # no api_key
    with pytest.raises(GameError, match="API key"):
        Game.remote(43, 44, 70, client=client)
