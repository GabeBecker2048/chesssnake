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
    _, out, _ = play(["e4", "e5", "quit"], game=game, player_id=game.white_id)
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
    _, _, _ = play(["e4", "resign", "quit"], game=game, player_id=game.white_id)
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
    session = Session(game, player_id=game.black_id, stdin=io.StringIO(), stdout=io.StringIO())
    assert session.perspective == Color.BLACK


def test_board_faces_white_by_default():
    game = Game.local()
    session = Session(game, stdin=io.StringIO(), stdout=io.StringIO())
    assert session.perspective == Color.WHITE


def test_explicit_perspective_overrides_the_player():
    game = Game.local()
    session = Session(game, player_id=game.black_id, perspective=Color.WHITE, stdin=io.StringIO(), stdout=io.StringIO())
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
        self.id = 7
        self.white_id, self.black_id = 0, 1
        self.white_name, self.black_name = "W", "B"
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


def test_cli_token_env_name_matches_the_client():
    """Same hardcode-with-a-test pattern as the URL variable."""
    from chesssnake.cli import _TOKEN_ENV
    from chesssnake.remote.game import TOKEN_ENV

    assert _TOKEN_ENV == TOKEN_ENV


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
    """A rematch begun elsewhere has to surface while idle too, not only on command."""
    game = _FakeRemote()
    session, writer, out = _session_over_pipe(game, 0.01, monkeypatch)

    def stale():
        game.syncs += 1
        session.newer_game = 9
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
    printed = out.getvalue()
    assert "a rematch has started (game 9)" in printed
    assert printed.count("a rematch has started") == 1, "announced once, not on every poll"


# --- live updates (0.13) -------------------------------------------------------------
#
# A fake stream over a real os.pipe stands in for remote.realtime.EventStream: it
# has the same four methods and the same "readable fd whenever something is
# queued" contract, so the session's select branch runs for real, with no server.


class _FakeStream:
    def __init__(self):
        self._read, self._write = os.pipe()
        os.set_blocking(self._read, False)
        self._events, self._lock = [], threading.Lock()
        self.subscribed, self.unsubscribed = [], []

    def push(self, *events):
        with self._lock:
            self._events.extend(events)
        os.write(self._write, b"!")

    def fileno(self):
        return self._read

    def drain(self):
        try:
            while os.read(self._read, 4096):
                pass
        except BlockingIOError:
            pass
        with self._lock:
            events, self._events = self._events, []
        return events

    def subscribe(self, game_id):
        self.subscribed.append(game_id)

    def unsubscribe(self, game_id):
        self.unsubscribed.append(game_id)


class _CountingClient:
    """What a remote game's client is asked for; a live session should not ask."""

    def __init__(self, state):
        self.state, self.gets = state, 0

    def get_game(self, _game_id):
        self.gets += 1
        return self.state

    def games_between(self, *args, **kwargs):
        return []


ALICE, BOB, GAME = 1, 2, 7


def _state(sans=(), version=1, game_id=GAME):
    from chesssnake.engine.game import Game as EngineGame
    from chesssnake.serialize import state_from_game

    engine = EngineGame(white_id=ALICE, black_id=BOB, group_id=0, white_name="alice", black_name="bob")
    for san in sans:
        engine.move(san)
    return state_from_game(engine, version, id=game_id)


def _live_session(*, refresh_seconds=10.0, stdin=None):
    from chesssnake.remote.game import Game as RemoteGame

    client = _CountingClient(_state())
    game = RemoteGame.from_state(_state(), client=client)
    stream, out = _FakeStream(), io.StringIO()
    session = Session(
        game,
        player_id=BOB,
        stdin=stdin if stdin is not None else io.StringIO(""),
        stdout=out,
        color=False,
        refresh_seconds=refresh_seconds,
        events=stream,
    )
    return session, stream, out, client


def _move_event(sans, version, san):
    squares = {"e4": ("e2", "e4"), "Nf3": ("g1", "f3")}[san]
    return {
        "type": "game",
        "state": _state(sans, version).to_dict(),
        "move": {"san": san, "from": squares[0], "to": squares[1], "check": False},
    }


def _wait_for(predicate, what):
    deadline = time.monotonic() + 5
    while not predicate():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.005)


def test_a_live_move_shows_while_the_prompt_waits():
    """The point of 0.13: the opponent's move appears with no input and no polling."""
    read_fd, write_fd = os.pipe()
    session, stream, out, client = _live_session(stdin=os.fdopen(read_fd, "r"))
    result = {}
    reader = threading.Thread(target=lambda: result.update(line=session.wait_for_line()), daemon=True)
    reader.start()

    stream.push(_move_event(["e4"], 2, "e4"))
    _wait_for(lambda: "alice played e4" in out.getvalue(), "the live move")

    with os.fdopen(write_fd, "w") as writer:
        writer.write("quit\n")
    reader.join(timeout=5)
    assert result["line"].strip() == "quit"
    assert session.game.version == 2 and session.game.to_move == Color.BLACK
    assert out.getvalue().rstrip().endswith(">"), "the prompt is re-issued after the redraw"
    assert client.gets == 0, "nothing was polled while connected"


def test_stale_and_unrelated_game_events_are_ignored():
    session, _, out, _ = _live_session()
    printed = session.handle_events(
        [
            {"type": "game", "state": _state(version=1).to_dict(), "move": None},  # not newer
            {"type": "game", "state": _state(["e4"], 5, game_id=99).to_dict(), "move": None},  # another game
        ]
    )
    assert not printed and out.getvalue() == "" and session.game.version == 1


def test_a_snapshot_after_reconnecting_brings_the_board_up_to_date():
    session, _, out, _ = _live_session()
    session.handle_events([{"type": "subscribed", "game": GAME, "state": _state(["e4", "e5"], 3).to_dict()}])
    assert session.game.version == 3
    assert "the game changed on the server" in out.getvalue()


def test_a_rematch_between_the_same_players_is_announced():
    session, _, out, _ = _live_session()
    other = _state(game_id=GAME + 1).to_dict()
    unrelated = dict(other, id=GAME + 2, black_id=3)
    session.handle_events([{"type": "game_started", "state": unrelated}])
    assert session.newer_game is None
    session.handle_events([{"type": "game_started", "state": other}])
    assert session.newer_game == GAME + 1
    assert f"a rematch has started (game {GAME + 1})" in out.getvalue()


def test_the_opponents_challenge_is_announced():
    session, _, out, _ = _live_session()
    challenge = {"id": 3, "challenger_id": ALICE, "challenged_id": BOB, "group_id": 0, "challenger_name": "alice"}
    session.handle_events([{"type": "challenge", "event": "created", "challenge": challenge}])
    assert "alice challenged you to a rematch - `new` accepts" in out.getvalue()
    mine = dict(challenge, challenger_id=BOB, challenged_id=ALICE)
    assert not session.handle_events([{"type": "challenge", "event": "created", "challenge": mine}])


def test_while_disconnected_it_polls_and_says_so_when_back():
    read_fd, write_fd = os.pipe()
    session, stream, out, client = _live_session(refresh_seconds=0.01, stdin=os.fdopen(read_fd, "r"))
    reader = threading.Thread(target=session.wait_for_line, daemon=True)
    reader.start()

    stream.push({"type": "disconnected", "code": 1012})
    _wait_for(lambda: client.gets >= 2, "a poll while disconnected")
    assert "live updates lost; reconnecting (polling every 0.01 s meanwhile)" in out.getvalue()

    stream.push({"type": "reconnected"})
    _wait_for(lambda: "live updates are back" in out.getvalue(), "the reconnect note")
    assert session.connected
    with os.fdopen(write_fd, "w") as writer:
        writer.write("quit\n")
    reader.join(timeout=5)


def test_a_stream_that_ends_falls_back_to_polling():
    session, _, out, _ = _live_session()
    session.handle_events([{"type": "ended", "reason": "this origin is not allowed"}])
    assert session.events is None and not session.connected
    assert "live updates stopped: this origin is not allowed" in out.getvalue()


def test_a_revoked_token_ends_the_session():
    session, stream, out, _ = _live_session(stdin=io.StringIO("e5\n"))
    stream.push({"type": "auth_error", "detail": "the token is no longer valid; log in again"})
    assert session.run() == 1
    assert "chesssnake login" in out.getvalue()


def test_events_queued_during_a_command_show_before_the_next_prompt():
    """A stdin with no fd (a StringIO, or Windows) cannot be selected on: drain per prompt."""
    session, stream, out, _ = _live_session(stdin=io.StringIO("board\n"))
    stream.push(_move_event(["e4"], 2, "e4"))
    assert session.run() == 0
    assert "alice played e4" in out.getvalue()


def test_switching_games_moves_the_subscription():
    session, stream, _, client = _live_session()
    client.state = _state(game_id=GAME + 1)
    session._switch_to(GAME + 1)
    assert stream.unsubscribed == [GAME] and stream.subscribed == [GAME + 1]
