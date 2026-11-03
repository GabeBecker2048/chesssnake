"""
Tests for the interactive session behind ``chesssnake play``.

The loop is driven by handing :class:`~chesssnake.play.Session` two streams, so
these run against a real :meth:`Game.local` game with **no server, no terminal
and no subprocess** — which is the reason the loop lives in its own module
rather than inside :mod:`chesssnake.cli`.
"""

import io
import os
import threading
import time

import pytest

from chesssnake import Game
from chesssnake.cli import _API_URL_ENV
from chesssnake.engine import Color
from chesssnake.play import Session, run_session
from chesssnake.remote.game import API_URL_ENV

SCHOLARS_MATE = ["e4", "e5", "Qh5", "Nc6", "Bc4", "Nf6", "Qxf7"]


def play(lines, game=None, **kwargs):
    """
    Run a session over ``lines`` and return ``(exit_status, output, game)``.

    :param lines: commands to feed, one per prompt.
    :param game: the game to drive; a fresh local game by default.
    :param kwargs: forwarded to :class:`Session` (``color`` defaults off so the
        assertions compare plain text).
    """
    game = game or Game.local(white_name="W", black_name="B")
    out = io.StringIO()
    kwargs.setdefault("color", False)
    status = run_session(game, stdin=io.StringIO("\n".join(lines) + "\n"), stdout=out, **kwargs)
    return status, out.getvalue(), game


# --- basic loop -------------------------------------------------------------


def test_quit_exits_cleanly():
    status, _, _ = play(["quit"])
    assert status == 0


def test_eof_exits_cleanly():
    """A closed stdin ends the session rather than raising."""
    game = Game.local()
    out = io.StringIO()
    assert run_session(game, stdin=io.StringIO(""), stdout=out, color=False) == 0


def test_blank_lines_are_ignored():
    status, out, game = play(["", "   ", "e4", "quit"])
    assert status == 0
    assert game.move_history == ["e4"]


def test_a_move_is_played_and_confirmed():
    _, out, game = play(["e4", "quit"])
    assert "played e4" in out
    assert game.fen.startswith("rnbqkbnr/pppppppp/8/8/4P3")


def test_moves_need_no_prefix_but_commands_win():
    """`fen` is a command; it must not be tried as a move."""
    _, out, game = play(["fen", "quit"])
    assert game.move_history == []
    assert "rnbqkbnr" in out


# --- errors keep the session alive -------------------------------------------


def test_illegal_move_reports_and_continues():
    _, out, game = play(["Qh9", "e4", "quit"])
    assert "InvalidNotationError" in out
    assert game.move_history == ["e4"], "the session must survive a bad move"


def test_moving_a_piece_that_cannot_go_there_reports_and_continues():
    _, out, game = play(["Nf6", "e4", "quit"])
    assert "Error" in out
    assert game.move_history == ["e4"]


def test_wrong_player_is_rejected_when_player_id_is_set():
    """
    With --me, acting out of turn is refused rather than silently accepted.

    The engine's ``move()`` takes no player id and a local game has no server to
    ask, so the session enforces this itself — otherwise ``--me`` would mean
    nothing offline while meaning something online.
    """
    game = Game.local()
    _, out, _ = play(["e4", "e5", "quit"], game=game, player_id=game.wid)
    assert game.move_history == ["e4"]
    assert "NotYourTurnError" in out


def test_turn_order_is_not_enforced_without_a_player_id():
    """One person at one keyboard plays both sides; that is the default."""
    _, _, game = play(["e4", "e5", "Nf3", "quit"])
    assert game.move_history == ["e4", "e5", "Nf3"]


# --- informational commands ---------------------------------------------------


def test_moves_lists_the_legal_moves():
    _, out, _ = play(["moves", "quit"])
    assert "20 legal moves" in out
    for san in ("e4", "Nf3", "h3"):
        assert san in out


def test_pgn_and_fen():
    _, out, _ = play(["e4", "e5", "pgn", "fen", "quit"])
    assert "1. e4 e5" in out
    assert "[White " in out
    assert " b KQkq " in out or " w KQkq " in out


def test_help_lists_every_command():
    _, out, _ = play(["help", "quit"])
    for name in ("moves", "resign", "flip", "save PATH"):
        assert name in out


def test_save_writes_a_png(tmp_path):
    target = tmp_path / "board.png"
    _, out, _ = play(["e4", f"save {target}", "quit"])
    assert target.is_file()
    assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert str(target) in out


def test_save_without_a_path_is_an_error_not_a_crash():
    _, out, _ = play(["save", "quit"])
    assert "usage: save PATH" in out


# --- endings -------------------------------------------------------------------


def test_checkmate_ends_the_game():
    _, out, game = play([*SCHOLARS_MATE, "quit"])
    assert game.is_over
    assert game.termination.value == "checkmate"
    assert "WHITE WON" in out


def test_resign_defaults_to_the_side_to_move():
    """With no --me, one player at one keyboard resigns as whoever is on move."""
    _, out, game = play(["resign", "quit"])
    assert game.is_over
    assert game.result == 2, "white was to move, so black wins"
    assert "by resignation" in out


def test_resign_uses_the_explicit_player_when_given():
    game = Game.local()
    _, _, _ = play(["e4", "resign", "quit"], game=game, player_id=game.wid)
    assert game.result == 2, "white resigned, so black wins"


def test_draw_offer_then_accept_ends_in_a_draw():
    """`accept` must act as the *opponent* of the offerer, not as the side to move."""
    _, out, game = play(["draw", "accept", "quit"])
    assert game.is_over
    assert game.result == 3
    assert "DRAW" in out


def test_draw_offer_can_be_declined_and_play_continues():
    _, out, game = play(["draw", "decline", "e4", "quit"])
    assert not game.is_over
    assert game.move_history == ["e4"]
    assert "draw offered by white" in out


def test_game_over_note_appears_once_not_after_every_command():
    """
    Regression: the note was printed after each command once the game ended,
    so `pgn` and `fen` each repeated it.
    """
    _, out, _ = play(["resign", "pgn", "fen", "board", "quit"])
    assert out.count("game over") == 1


# --- presentation ---------------------------------------------------------------


def test_no_escape_codes_when_colour_is_off():
    _, out, _ = play(["e4", "moves", "resign", "quit"], color=False)
    assert "\033" not in out


def test_escape_codes_when_colour_is_on():
    _, out, _ = play(["e4", "quit"], color=True)
    assert "\033" in out


def test_flip_changes_the_view():
    _, flipped, _ = play(["flip", "quit"])
    _, normal, _ = play(["board", "quit"])
    assert flipped != normal


def test_board_faces_the_players_own_side():
    game = Game.local()
    session = Session(game, player_id=game.bid, stdin=io.StringIO(), stdout=io.StringIO())
    assert session.perspective == Color.BLACK


def test_board_faces_white_by_default():
    game = Game.local()
    session = Session(game, stdin=io.StringIO(), stdout=io.StringIO())
    assert session.perspective == Color.WHITE


def test_explicit_perspective_overrides_the_player():
    game = Game.local()
    session = Session(game, player_id=game.bid, perspective=Color.WHITE, stdin=io.StringIO(), stdout=io.StringIO())
    assert session.perspective == Color.WHITE


def test_ascii_mode_uses_letters():
    _, out, _ = play(["quit"], figurines=False)
    assert "K" in out and "♔" not in out


# --- local-game limits -----------------------------------------------------------


def test_refresh_is_a_no_op_on_a_local_game():
    _, out, _ = play(["refresh", "quit"])
    assert "nothing to refresh" in out


def test_new_refuses_while_the_game_is_in_play():
    _, out, _ = play(["new", "quit"])
    assert "still in play" in out


def test_new_explains_itself_on_a_finished_local_game():
    _, out, _ = play(["resign", "new", "quit"])
    assert "--local" in out


# --- wiring ------------------------------------------------------------------------


def test_cli_env_name_matches_the_client():
    """
    cli.py hardcodes the variable name so argparse can show it without importing
    the engine. This is the test that keeps the copy honest.
    """
    assert _API_URL_ENV == API_URL_ENV


@pytest.mark.parametrize("command", ["quit", "exit", "q"])
def test_quit_aliases(command):
    assert play([command])[0] == 0


@pytest.mark.parametrize("command", ["refresh", "r"])
def test_refresh_aliases(command):
    assert "nothing to refresh" in play([command, "quit"])[1]


def test_moves_reports_none_once_the_game_is_over():
    """Checkmate leaves no legal move; `moves` must say so rather than print nothing."""
    _, out, game = play([*SCHOLARS_MATE, "moves", "quit"])
    assert game.is_over
    assert "(none)" in out


# --- idle refresh ---------------------------------------------------------------


class _FakeRemote:
    """
    A minimal stand-in for a remote game, to drive `wait_for_line`'s timeout
    branch deterministically. A real server cannot be made to move an opponent at
    a predictable moment, and a sleep-based test would be flaky.
    """

    is_remote = True
    is_over = False

    def __init__(self, syncs_before_change=1):
        self.syncs = 0
        self.syncs_before_change = syncs_before_change
        self.generation = 1
        self.version = 1
        self.wid, self.bid = 0, 1
        self.wname, self.bname = "W", "B"
        self.draw_offered_by = None
        self.board = Game.local().board
        self.to_move = Color.WHITE

    def refreshed(self):
        self.syncs += 1
        if self.syncs >= self.syncs_before_change:
            self.version += 1
            return True
        return False


def _session_over_pipe(game, refresh_seconds, monkeypatch):
    """A session whose stdin is a real pipe, so `select` has an fd to wait on."""
    read_fd, write_fd = os.pipe()
    stdin = os.fdopen(read_fd, "r")
    out = io.StringIO()
    session = Session(game, stdin=stdin, stdout=out, color=False, refresh_seconds=refresh_seconds)
    monkeypatch.setattr(session, "sync", game.refreshed)
    return session, os.fdopen(write_fd, "w"), out


def test_idle_refresh_notices_the_opponent_and_reprompts(monkeypatch):
    """
    The one thing the session does unasked: poll while idle.

    Deterministic rather than timing-based — the pipe is left empty so the wait
    *must* take the timeout branch, and the input is only written once a poll has
    actually happened.
    """
    game = _FakeRemote(syncs_before_change=1)
    session, writer, out = _session_over_pipe(game, 0.01, monkeypatch)

    result = {}

    def read():
        result["line"] = session.wait_for_line()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()

    deadline = time.monotonic() + 5
    while game.syncs < 1 and time.monotonic() < deadline:
        pass
    assert game.syncs >= 1, "the idle wait never polled the server"

    writer.write("quit\n")
    writer.flush()
    reader.join(timeout=5)
    assert not reader.is_alive()
    writer.close()

    assert result["line"].strip() == "quit"
    printed = out.getvalue()
    assert "the opponent moved" in printed
    assert printed.rstrip().endswith(">"), "the prompt must be re-issued after a redraw"


def test_idle_refresh_is_skipped_when_disabled(monkeypatch):
    game = _FakeRemote()
    session, writer, _ = _session_over_pipe(game, 0, monkeypatch)
    writer.write("quit\n")
    writer.flush()
    assert session.wait_for_line().strip() == "quit"
    assert game.syncs == 0, "--refresh 0 must not poll at all"
    writer.close()


def test_idle_refresh_is_skipped_for_a_local_game():
    """Nothing to poll, so it must not try."""
    game = Game.local()
    out = io.StringIO()
    session = Session(game, stdin=io.StringIO("quit\n"), stdout=out, color=False, refresh_seconds=5)
    assert session.wait_for_line().strip() == "quit"


def test_a_stream_without_a_file_descriptor_falls_back_to_blocking():
    """A StringIO cannot be selected on; the session must still work."""
    game = Game.local()
    session = Session(game, stdin=io.StringIO("e4\n"), stdout=io.StringIO(), color=False, refresh_seconds=5)
    assert session.wait_for_line().strip() == "e4"


def test_refresh_seconds_has_a_nonzero_default():
    """Polling on by default is the point; the exact number is a judgement call."""
    game = Game.local()
    assert Session(game, stdin=io.StringIO(), stdout=io.StringIO()).refresh_seconds == 10.0


# --- Ctrl+C ---------------------------------------------------------------------


class _InterruptingStream:
    """A stdin that raises KeyboardInterrupt, as Ctrl+C at the prompt does."""

    def __init__(self, raise_on=1):
        self.reads = 0
        self.raise_on = raise_on

    def readline(self):
        self.reads += 1
        if self.reads >= self.raise_on:
            raise KeyboardInterrupt
        return "board\n"


def test_ctrl_c_at_the_prompt_exits_quietly():
    """
    Regression: Ctrl+C used to propagate out of `select()` and print a traceback
    through cli.py, which tells the player nothing. 130 is the SIGINT convention.
    """
    out = io.StringIO()
    status = run_session(Game.local(), stdin=_InterruptingStream(), stdout=out, color=False)
    assert status == 130
    assert "Traceback" not in out.getvalue()
    assert "KeyboardInterrupt" not in out.getvalue()


def test_ctrl_c_after_some_input_still_exits_quietly():
    out = io.StringIO()
    stream = _InterruptingStream(raise_on=3)
    assert run_session(Game.local(), stdin=stream, stdout=out, color=False) == 130
    assert "KeyboardInterrupt" not in out.getvalue()


def test_ctrl_c_during_an_action_exits_quietly(monkeypatch):
    """Ctrl+C part-way through a move must not surface as a crash either."""
    game = Game.local()
    monkeypatch.setattr(game, "move", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt))
    out = io.StringIO()
    assert run_session(game, stdin=io.StringIO("e4\n"), stdout=out, color=False) == 130
    assert "KeyboardInterrupt" not in out.getvalue()


def test_cli_api_key_env_name_matches_the_client():
    """Same hardcode-with-a-test pattern as the URL variable."""
    from chesssnake.cli import _API_KEY_ENV
    from chesssnake.remote.game import API_KEY_ENV

    assert _API_KEY_ENV == API_KEY_ENV


def test_a_quiet_poll_prints_nothing(monkeypatch):
    """Polling must be invisible until something actually changes."""
    game = _FakeRemote(syncs_before_change=3)
    session, writer, out = _session_over_pipe(game, 0.01, monkeypatch)

    result = {}
    reader = threading.Thread(target=lambda: result.update(line=session.wait_for_line()), daemon=True)
    reader.start()
    deadline = time.monotonic() + 5
    while game.syncs < 2 and time.monotonic() < deadline:
        pass
    assert game.syncs >= 2, "expected several quiet polls"
    assert out.getvalue() == "", "a poll that found nothing must stay silent"

    writer.write("quit\n")
    writer.flush()
    reader.join(timeout=5)
    writer.close()
    assert result["line"].strip() == "quit"


def test_idle_poll_announces_a_rematch_started_elsewhere(monkeypatch):
    """The stale-generation case has to surface while idle too, not only on command."""
    game = _FakeRemote()
    session, writer, out = _session_over_pipe(game, 0.01, monkeypatch)

    def stale():
        game.syncs += 1
        session.stale_generation = 2
        return False

    monkeypatch.setattr(session, "sync", stale)

    result = {}
    reader = threading.Thread(target=lambda: result.update(line=session.wait_for_line()), daemon=True)
    reader.start()
    deadline = time.monotonic() + 5
    while game.syncs < 1 and time.monotonic() < deadline:
        pass

    writer.write("quit\n")
    writer.flush()
    reader.join(timeout=5)
    writer.close()
    assert "a rematch has started elsewhere (generation 2)" in out.getvalue()
