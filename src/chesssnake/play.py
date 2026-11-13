"""
The interactive terminal session behind ``chesssnake play``.

This is the third way to drive chesssnake, alongside the REST API and the
Python client — and it is deliberately built *on* the client rather than beside
it: :func:`run_session` talks to a :class:`chesssnake.Game` and never to HTTP,
so the same loop plays a local in-memory game and a game persisted through an
api-endpoint. Anything it can do, the client could already do; this only puts a
board and a prompt around it.

Separated from :mod:`chesssnake.cli` so the loop can be tested by handing it two
streams, with no terminal, no server and no subprocess.
"""

import io
import select

from .db.errors import AuthError, GameError, NotYourTurnError
from .engine import Color, GameStatus, render_text
from .engine.errors import ChessError

#: Printed by ``help``. Two columns, formatted on use so the pairs stay readable
#: here and the widths stay consistent there.
COMMANDS = [
    ("<move>", "play a move in algebraic notation (e4, Nf3, O-O, exd5, e8=Q)"),
    ("moves", "list every legal move for the side to move"),
    ("board", "redraw the board"),
    ("flip", "view from the other side"),
    ("fen", "the position as FEN"),
    ("pgn", "the game so far as PGN"),
    ("draw", "offer a draw"),
    ("accept", "accept a draw offer"),
    ("decline", "decline a draw offer"),
    ("resign", "resign the game"),
    ("refresh", "re-fetch from the server (see the opponent's move)"),
    ("new", "once the game is over: challenge your opponent to a rematch, or accept theirs"),
    ("save PATH", "write a PNG of the board"),
    ("help", "this list"),
    ("quit", "leave (a remote game is saved; a local one is not)"),
]

_STATUS_TEXT = {
    GameStatus.IN_PLAY: "in play",
    GameStatus.WHITE_WON: "white won",
    GameStatus.BLACK_WON: "black won",
    GameStatus.DRAW: "draw",
}

_DIM = "\033[2m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_RESET = "\033[0m"


class Quit(Exception):
    """Raised by the ``quit`` command to unwind the loop."""


class Session:
    """
    One interactive game at a terminal.

    :param game: the :class:`chesssnake.Game` to drive — local or remote; the
        loop does not care which, beyond labelling the header.
    :param player_id: the id actions are sent as. For a remote game this is the
        logged-in user when they are one of the players, and the server enforces
        turn order against it. When ``None``, the session acts as whichever side
        is to move: one player at one keyboard locally, or an administrator
        driving someone else's game remotely.
    :param stdin: stream read for commands.
    :param stdout: stream written to.
    :param color: emit ANSI colour. When false, **no** escape sequence is
        written at all, so the output pipes cleanly.
    :param figurines: draw pieces as ``♞`` rather than the letter ``N``.
    :param perspective: which side faces the reader; defaults to the player's
        own side when ``player_id`` identifies one, else white.
    """

    def __init__(
        self,
        game,
        *,
        player_id=None,
        stdin,
        stdout,
        color: bool = True,
        figurines: bool = True,
        perspective=None,
        refresh_seconds: float = 10.0,
        events=None,
    ):
        self.game = game
        self.player_id = player_id
        self.stdin = stdin
        self.stdout = stdout
        self.color = color
        self.figurines = figurines
        self.refresh_seconds = refresh_seconds
        #: Live updates (a :class:`chesssnake.remote.realtime.EventStream`, or
        #: anything with ``fileno()``/``drain()``/``subscribe()``/``unsubscribe()``),
        #: or ``None`` to poll every ``refresh_seconds`` as before 0.13.
        self.events = events
        #: Whether the live connection is up; while it is down, poll instead.
        self.connected = events is not None
        #: Set by :meth:`sync` to the id of a newer game between the same two
        #: players, once this session's game is over and a rematch has begun.
        self.newer_game = None
        if perspective is not None:
            self.perspective = Color(perspective)
        elif player_id is not None and player_id == getattr(game, "black_id", None):
            self.perspective = Color.BLACK
        else:
            self.perspective = Color.WHITE

    # --- output ------------------------------------------------------------

    def write(self, text: str = "") -> None:
        """Write one line to the output stream."""
        self.stdout.write(text + "\n")

    def _style(self, text: str, code: str) -> str:
        """Wrap ``text`` in an ANSI code, or return it untouched when colour is off."""
        return f"{code}{text}{_RESET}" if self.color else text

    def note(self, text: str) -> None:
        """Write a de-emphasized line (hints, confirmations)."""
        self.write(self._style(text, _DIM))

    def error(self, text: str) -> None:
        """Write an error line. Errors are expected here — an illegal move is normal input."""
        self.write(self._style(text, _RED))

    # --- state ---------------------------------------------------------------

    def _id_of(self, color):
        """The player id for ``color`` in this game."""
        return self.game.white_id if Color(color) == Color.WHITE else self.game.black_id

    def actor(self, *, responding: bool = False):
        """
        The player id an action should be sent as.

        :param responding: when true the action answers an existing draw offer,
            so the actor defaults to the player who did *not* make it — the side
            to move may well be the offerer.
        """
        if self.player_id is not None:
            return self.player_id
        offered_by = self.game.draw_offered_by
        if responding and offered_by is not None:
            return self._id_of(Color(offered_by).opponent)
        return self._id_of(self.game.to_move)

    def header(self) -> str:
        """The one-line status under the board."""
        game = self.game
        white = game.white_name or "white"
        black = game.black_name or "black"
        bits = [f"{white} (white) vs {black} (black)"]
        if game.is_remote:
            bits.append(f"game {game.id}")
        if game.is_over:
            bits.append(self._style(_STATUS_TEXT[game.result].upper(), _BOLD))
            if game.termination is not None:
                bits.append(f"by {game.termination.value}")
        else:
            bits.append(f"{'white' if game.to_move == Color.WHITE else 'black'} to move")
            offered_by = game.draw_offered_by
            if offered_by is not None:
                side = "white" if Color(offered_by) == Color.WHITE else "black"
                bits.append(f"draw offered by {side}")
        return "  |  ".join(bits)

    def show(self) -> None:
        """Draw the board followed by the status line."""
        self.write()
        self.write(
            render_text(
                self.game.board,
                self.perspective,
                figurines=self.figurines,
                color=self.color,
                move=getattr(self.game, "last_move", None),
            )
        )
        self.write()
        self.write(self.header())

    # --- commands ------------------------------------------------------------

    def do_help(self, _arg):
        """List the available commands."""
        width = max(len(name) for name, _ in COMMANDS)
        for name, blurb in COMMANDS:
            self.write(f"  {name.ljust(width)}  {blurb}")

    def sync(self) -> bool:
        """
        Pull the latest server state into the mirror, for a remote game.

        Called before every informational command and every action, because
        several reads (``legal_moves``, ``pgn``, ``history``) are *proxied to the
        server* while the board and ``fen`` come from the local mirror. Without
        this the two disagree the moment the opponent moves: the board would show
        your last position while ``moves`` listed the legal moves of a position
        you cannot see.

        Once the game is over it also looks for a **newer game between the same
        two players** in the same group: a rematch started from somewhere else.
        Found, it sets :attr:`newer_game` and does *not* switch to it; joining is
        the player's decision (``new``), not a surprise. Newer is decided by game
        id, which only ever increases, not by generation, which is counted per
        colour arrangement and so restarts when a rematch swaps colours.

        :return: whether the position moved on, so the caller can redraw and say
            so rather than silently changing the board.
        """
        if not self.game.is_remote:
            return False
        before = self.game.version
        self.game.refresh()
        if self.game.is_over and self.newer_game is None:
            client = self.game._client  # play.py and remote/game.py ship together
            active = client.games_between(self.game.white_id, self.game.black_id, self.game.group_id, status="active")
            newer = [state.id for state in active if state.id > self.game.id]
            self.newer_game = max(newer) if newer else None
        return self.game.version != before

    def _sync_and_announce(self) -> None:
        """Sync, and redraw with a note if the opponent has been and gone."""
        changed = self.sync()
        if self.newer_game is not None:
            self.note(self._rematch_notice())
            return
        if changed:
            self.note("the position changed on the server")
            self.show()

    def _rematch_notice(self) -> str:
        """Explain that this session is looking at a superseded game."""
        return f"a rematch has started (game {self.newer_game}); this game is over. `new` joins it."

    def allow_action(self) -> bool:
        """
        Sync, then report whether an action may be sent.

        Every action goes through here, so :meth:`blocked_reason` is checked once
        rather than at seven call sites.

        :return: ``True`` when it is safe to act.
        """
        self.sync()
        reason = self.blocked_reason()
        if reason is None:
            return True
        self.error(reason)
        return False

    def blocked_reason(self):
        """
        Why an action must not be sent, or ``None`` when it is safe.

        A session addresses its game by id, so an action can never land in a
        rematch (before 0.11.0 one could, and did). What this adds is a sentence
        the player can act on, ``new``, in place of the server's ``GameOverError``.

        :return: a message to show, or ``None``.
        """
        if not self.game.is_remote:
            return None
        if self.newer_game is not None:
            return self._rematch_notice()
        if self.game.is_over:
            return "this game is over - `new` challenges your opponent to a rematch"
        return None

    def do_moves(self, _arg):
        """List the legal moves for the side to move."""
        self._sync_and_announce()
        moves = self.game.legal_moves()
        if not moves:
            self.write("(none)")
            return
        self.write("  ".join(sorted(m["san"] for m in moves)))
        self.note(f"{len(moves)} legal moves")

    def do_board(self, _arg):
        """Redraw the board, from current server state when remote."""
        self.sync()
        self.show()

    def do_flip(self, _arg):
        """Swap which side faces the reader."""
        self.perspective = Color(self.perspective).opponent
        self.show()

    def do_fen(self, _arg):
        """Print the position as FEN."""
        self._sync_and_announce()
        self.write(self.game.fen)

    def do_pgn(self, _arg):
        """Print the game so far as PGN."""
        self._sync_and_announce()
        self.write(self.game.pgn().strip())

    def do_draw(self, _arg):
        """Offer a draw."""
        if not self.allow_action():
            return
        self.game.draw_offer(self.actor())
        self.show()

    def do_accept(self, _arg):
        """Accept the outstanding draw offer."""
        if not self.allow_action():
            return
        self.game.draw_accept(self.actor(responding=True))
        self.show()

    def do_decline(self, _arg):
        """Decline the outstanding draw offer."""
        if not self.allow_action():
            return
        self.game.draw_decline(self.actor(responding=True))
        self.show()

    def do_resign(self, _arg):
        """Resign the game."""
        if not self.allow_action():
            return
        self.game.resign(self.actor())
        self.show()

    def do_refresh(self, _arg):
        """Re-fetch the game from the server."""
        if not self.game.is_remote:
            self.note("local game - nothing to refresh")
            return
        changed = self.sync()
        if self.newer_game is not None:
            self.note(self._rematch_notice())
        elif changed:
            self.show()
        else:
            self.note("nothing new")

    def do_save(self, arg):
        """Write a PNG of the current board to ``arg``."""
        if not arg:
            self.error("usage: save PATH")
            return
        self.game.save(arg)
        self.note(f"wrote {arg}")

    def do_new(self, _arg):
        """
        After a game: join the rematch if one has started, else accept the
        opponent's rematch challenge if they sent one, else send them one with
        the colours swapped. Games are only ever created by an accepted challenge,
        so a rematch takes both players' say-so.
        """
        if not self.game.is_remote:
            if not self.game.is_over:
                self.error("the current game is still in play - resign or finish it first")
            else:
                self.error("a local game cannot be restarted in place - rerun `chesssnake play --local`")
            return
        self.sync()
        if self.newer_game is None and not self.game.is_over:
            self.error("the current game is still in play - resign or finish it first")
            return
        if self.newer_game is not None:
            self._switch_to(self.newer_game)
            return
        me = self.player_id
        if me not in (self.game.white_id, self.game.black_id):
            self.error("only one of the players can start a rematch")
            return
        opponent = self.game.black_id if me == self.game.white_id else self.game.white_id
        client = self.game._client
        for challenge in client.challenges("all"):
            if challenge.group_id != self.game.group_id or opponent not in (
                challenge.challenger_id,
                challenge.challenged_id,
            ):
                continue
            if challenge.challenger_id == opponent:
                self._switch_to(client.accept_challenge(challenge.id).id)
            else:
                self.note(f"rematch challenge {challenge.id} already sent - waiting for them to accept")
            return
        # Swap colours: whoever had white asks for black this time.
        color = "black" if me == self.game.white_id else "white"
        challenge = client.challenge(opponent, self.game.group_id, color)
        self.note(
            f"rematch challenge {challenge.id} sent to {challenge.challenged_name} (you play {color}); "
            "when they accept, `new` joins the game"
        )

    def _switch_to(self, game_id):
        """Point the session at another game (the rematch) and draw it."""
        from .remote.game import Game

        old = self.game.id
        self.game = Game.remote(game_id, client=self.game._client, player_id=self.game.player_id)
        self.newer_game = None
        if self.events is not None:
            self.events.unsubscribe(old)
            self.events.subscribe(self.game.id)
        if self.player_id is not None:
            self.perspective = Color.BLACK if self.player_id == self.game.black_id else Color.WHITE
        self.note(f"rematch - game {self.game.id}")
        self.show()

    def do_quit(self, _arg):
        """Leave the session."""
        raise Quit()

    #: Command name -> handler. Aliases point at the same bound method name.
    DISPATCH = {
        "help": "do_help",
        "?": "do_help",
        "moves": "do_moves",
        "board": "do_board",
        "flip": "do_flip",
        "fen": "do_fen",
        "pgn": "do_pgn",
        "draw": "do_draw",
        "offer": "do_draw",
        "accept": "do_accept",
        "decline": "do_decline",
        "resign": "do_resign",
        "refresh": "do_refresh",
        "r": "do_refresh",
        "save": "do_save",
        "new": "do_new",
        "quit": "do_quit",
        "exit": "do_quit",
        "q": "do_quit",
    }

    def dispatch(self, line: str) -> None:
        """
        Run one line of input: a command, or otherwise a move.

        Anything not in :attr:`DISPATCH` is treated as a move, so moves need no
        prefix. That is the right default — it is the only thing typed often —
        and it is why commands are lowercase words that cannot collide with
        algebraic notation.
        """
        word, _, rest = line.strip().partition(" ")
        handler = self.DISPATCH.get(word.lower())
        if handler is not None:
            getattr(self, handler)(rest.strip())
            return
        # A remote server checks this itself and is the authority, so the client
        # must not duplicate the rule. A local game has no server to ask, and
        # the engine's move() takes no player id — so without this check `--me`
        # would silently mean nothing offline, which is worse than not offering it.
        if not self.allow_action():
            return
        if self.player_id is not None and not self.game.is_remote and not self.game.is_players_turn(self.player_id):
            raise NotYourTurnError(f"It is not player {self.player_id}'s turn to move")
        result = self.game.move(line.strip())
        san = getattr(result, "san", None) or line.strip()
        self.note(f"played {san}")
        self.show()

    # --- live updates ---------------------------------------------------------

    def _name_of(self, color) -> str:
        return (self.game.white_name if Color(color) == Color.WHITE else self.game.black_name) or (
            "white" if Color(color) == Color.WHITE else "black"
        )

    def handle_events(self, events) -> bool:
        """
        Apply what the live stream delivered; return whether anything was printed.

        Runs on the session's own thread (the stream's thread only queues), so the
        game and the output are still touched by one thread alone.
        """
        from .dto import GameState

        printed = False
        for event in events:
            kind = event.get("type")
            if kind in ("game", "subscribed"):
                state = GameState.from_dict(event["state"])
                if state.id != self.game.id or (self.game.version or 0) >= state.version:
                    continue  # another game, or nothing newer than what is on screen
                was_over = self.game.is_over
                self.game._apply_state(state)
                move = event.get("move")
                self.write()
                if move:
                    self._mark_move(move)
                    mover = Color(self.game.to_move).opponent
                    self.note(f"{self._name_of(mover)} played {move['san']}")
                else:
                    self.note("the game changed on the server")
                self.show()
                if self.game.is_over and not was_over:
                    self.note("game over - `new` for a rematch")
                printed = True
            elif kind == "game_removed" and event.get("game") == self.game.id:
                self.write()
                self.error("an administrator deleted this game")
                printed = True
            elif kind == "game_started":
                state = event["state"]
                players = {self.game.white_id, self.game.black_id}
                if (
                    state["id"] > (self.game.id or 0)
                    and {state["white_id"], state["black_id"]} == players
                    and state["group_id"] == self.game.group_id
                    and self.newer_game != state["id"]
                ):
                    self.newer_game = state["id"]
                    self.write()
                    self.note(self._rematch_notice())
                    printed = True
            elif kind == "challenge" and event.get("event") == "created":
                challenge = event["challenge"]
                opponent = self.game.black_id if self.player_id == self.game.white_id else self.game.white_id
                if (
                    self.player_id is not None
                    and challenge["challenger_id"] == opponent
                    and challenge["challenged_id"] == self.player_id
                    and challenge["group_id"] == self.game.group_id
                ):
                    self.write()
                    self.note(f"{challenge['challenger_name']} challenged you to a rematch - `new` accepts")
                    printed = True
            elif kind == "disconnected":
                if self.connected:
                    self.connected = False
                    self.write()
                    polling = f"polling every {self.refresh_seconds:g} s" if self.refresh_seconds > 0 else "not polling"
                    self.note(f"live updates lost; reconnecting ({polling} meanwhile)")
                    printed = True
            elif kind == "reconnected":
                self.connected = True
                self.write()
                self.note("live updates are back")
                printed = True
            elif kind == "ended":
                self.events, self.connected = None, False
                self.write()
                self.note(f"live updates stopped: {event.get('reason')}")
                printed = True
            elif kind == "auth_error":
                raise AuthError(event.get("detail") or "the token is no longer valid")
        return printed

    def _mark_move(self, move) -> None:
        """Highlight the move the stream announced, as a local move would be."""
        # the renderers read a {"from", "to"} mapping directly (castling's "to" is None)
        self.game.last_move = move if isinstance(move, dict) else None

    def _wait_live(self, fd):
        """
        Wait on stdin and the live stream together, with no timeout while connected.

        An opponent's move is shown the moment it arrives; nothing is polled. While
        the connection is down, wakes every ``refresh_seconds`` to poll instead.
        """
        while True:
            live = self.events is not None
            fds = [fd, self.events.fileno()] if live else [fd]
            timeout = (
                None if (live and self.connected) else (self.refresh_seconds if self.refresh_seconds > 0 else None)
            )
            try:
                ready, _, _ = select.select(fds, [], [], timeout)
            except (OSError, ValueError):
                return self.stdin.readline()
            if fd in ready:
                return self.stdin.readline()
            if live and self.events is not None and self.events.fileno() in ready:
                printed = self.handle_events(self.events.drain())
            else:
                had_newer = self.newer_game is not None
                changed = self.sync()
                printed = changed or (self.newer_game is not None and not had_newer)
                if changed:
                    self.write()
                    self.note("the opponent moved")
                    self.show()
                elif printed:
                    self.write()
                    self.note(self._rematch_notice())
            if printed:
                self.stdout.write("\n> ")
                self.stdout.flush()

    def wait_for_line(self):
        """
        Read one line, showing what happens on the server meanwhile.

        This is the only place the session acts without being asked. With a live
        stream it waits on stdin and the stream together and shows an opponent's
        move as it happens; without one it re-reads the server every
        ``refresh_seconds``. ``select`` is used rather than a background thread
        touching the game, so there is exactly one thread touching the game and
        the output stream, and nothing to shut down on exit.

        Falls back to a plain blocking read whenever waiting is not possible — a
        local game (nothing to poll), ``--refresh 0``, a stdin with no real file
        descriptor (a ``StringIO``, as the tests use), or a platform where
        ``select`` will not take one. The session still works; it just will not
        notice the opponent on its own.

        :return: the line read, or ``""`` at EOF.
        """
        if self.events is not None and self.game.is_remote:
            try:
                fd = self.stdin.fileno()
            except (AttributeError, io.UnsupportedOperation, ValueError):
                # No fd to select on (a StringIO, or stdin on Windows): events are
                # drained before each prompt instead, so they show on the next line.
                return self.stdin.readline()
            return self._wait_live(fd)
        if self.refresh_seconds <= 0 or not self.game.is_remote:
            return self.stdin.readline()
        try:
            fd = self.stdin.fileno()
        except (AttributeError, io.UnsupportedOperation, ValueError):
            return self.stdin.readline()
        while True:
            try:
                ready, _, _ = select.select([fd], [], [], self.refresh_seconds)
            except (OSError, ValueError):
                # Windows select() takes sockets only; nothing to do but block.
                return self.stdin.readline()
            if ready:
                return self.stdin.readline()
            had_newer = self.newer_game is not None
            changed = self.sync()
            if self.newer_game is not None and not had_newer:
                self.write()
                self.note(self._rematch_notice())
            elif changed:
                self.write()
                self.note("the opponent moved")
                self.show()
            else:
                continue
            # Re-issue the prompt: whatever the player had half-typed is still in
            # the terminal's buffer, but the prompt itself has scrolled away.
            self.stdout.write("\n> ")
            self.stdout.flush()

    def run(self) -> int:
        """
        Read commands until EOF or ``quit``.

        :return: a process exit status — 0 on ``quit``/EOF, 130 on Ctrl+C. A
            failure to *reach* the server raises out of the session instead,
            because that is a setup problem rather than a move the player got
            wrong.
        """
        self.show()
        self.note("type `help` for commands")
        while True:
            try:
                # Anything that arrived while a command ran, or that could not
                # wake the prompt (a stdin that cannot be selected on), shows now.
                if self.events is not None:
                    self.handle_events(self.events.drain())
            except AuthError as e:
                return self._logged_out(e)
            self.stdout.write("\n> ")
            self.stdout.flush()
            try:
                line = self.wait_for_line()
            except AuthError as e:
                return self._logged_out(e)
            except KeyboardInterrupt:
                # Ctrl+C at the prompt is how people leave a REPL. It is not a
                # crash, and a traceback through select() tells the player
                # nothing. 130 is the conventional status for SIGINT.
                self.write()
                return 130
            if not line:  # EOF
                self.write()
                return 0
            if not line.strip():
                continue
            was_over = self.game.is_over
            try:
                self.dispatch(line)
            except Quit:
                return 0
            except AuthError as e:
                # Not an input mistake: the token expired or was revoked, and every
                # further line (and every poll) would fail the same way.
                return self._logged_out(e)
            except KeyboardInterrupt:
                # Ctrl+C part-way through a request: the action may or may not
                # have reached the server, so say nothing about it and leave.
                # Re-reading on the next run is what resolves it.
                self.write()
                return 130
            except (ChessError, GameError, ValueError) as e:
                # Expected: an illegal move, acting out of turn, a stale version.
                # Keep playing — the player simply types something else.
                self.error(f"{type(e).__name__}: {e}")
            # Only on the transition. Printing it after every command — `pgn`
            # and `fen` included — turns the one line that matters into noise.
            if self.game.is_over and not was_over:
                self.note("game over - `new` for a rematch" if self.game.is_remote else "game over")

    def _logged_out(self, exc) -> int:
        self.write()
        self.error(f"{type(exc).__name__}: {exc}")
        self.write("Log in again with `chesssnake login`, then rerun `chesssnake play`.")
        return 1


def run_session(game, **kwargs) -> int:
    """
    Build a :class:`Session` and run it.

    :param game: the :class:`chesssnake.Game` to play.
    :param kwargs: forwarded to :class:`Session`.
    :return: the process exit status.
    """
    return Session(game, **kwargs).run()
