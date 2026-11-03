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
