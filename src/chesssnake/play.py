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

from .db.errors import GameError, NotYourTurnError
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
    ("new", "start a rematch once the game is over"),
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
    :param player_id: the id actions are sent as. When given, a remote server
        enforces turn order against it. When ``None``, the session acts as
        whichever side is to move, which is what a single player at one
        keyboard wants.
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
    ):
        self.game = game
        self.player_id = player_id
        self.stdin = stdin
        self.stdout = stdout
        self.color = color
        self.figurines = figurines
        if perspective is not None:
            self.perspective = Color(perspective)
        elif player_id is not None and player_id == getattr(game, "bid", None):
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
        return self.game.wid if Color(color) == Color.WHITE else self.game.bid

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
        white = game.wname or "white"
        black = game.bname or "black"
        bits = [f"{white} (white) vs {black} (black)"]
        if game.is_remote:
            bits.append(f"gen {game.generation}")
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

    def do_moves(self, _arg):
        """List the legal moves for the side to move."""
        moves = self.game.legal_moves()
        if not moves:
            self.write("(none)")
            return
        self.write("  ".join(sorted(m["san"] for m in moves)))
        self.note(f"{len(moves)} legal moves")

    def do_board(self, _arg):
        """Redraw the board."""
        self.show()

    def do_flip(self, _arg):
        """Swap which side faces the reader."""
        self.perspective = Color(self.perspective).opponent
        self.show()

    def do_fen(self, _arg):
        """Print the position as FEN."""
        self.write(self.game.fen)

    def do_pgn(self, _arg):
        """Print the game so far as PGN."""
        self.write(self.game.pgn().strip())

    def do_draw(self, _arg):
        """Offer a draw."""
        self.game.draw_offer(self.actor())
        self.show()

    def do_accept(self, _arg):
        """Accept the outstanding draw offer."""
        self.game.draw_accept(self.actor(responding=True))
        self.show()

    def do_decline(self, _arg):
        """Decline the outstanding draw offer."""
        self.game.draw_decline(self.actor(responding=True))
        self.show()

    def do_resign(self, _arg):
        """Resign the game."""
        self.game.resign(self.actor())
        self.show()

    def do_refresh(self, _arg):
        """Re-fetch the game from the server."""
        if not self.game.is_remote:
            self.note("local game - nothing to refresh")
            return
        self.game.refresh()
        self.show()

    def do_save(self, arg):
        """Write a PNG of the current board to ``arg``."""
        if not arg:
            self.error("usage: save PATH")
            return
        self.game.save(arg)
        self.note(f"wrote {arg}")

    def do_new(self, _arg):
        """Start a rematch. Only meaningful once the current game is over."""
        if not self.game.is_over:
            self.error("the current game is still in play - resign or finish it first")
            return
        if not self.game.is_remote:
            self.error("a local game cannot be restarted in place - rerun `chesssnake play --local`")
            return
        # Re-opening a finished triple is what starts a new generation server-side.
        from .remote.game import Game

        self.game = Game.remote(
            self.game.wid,
            self.game.bid,
            self.game.gid,
            white_name=self.game.wname,
            black_name=self.game.bname,
            player_id=self.player_id,
            client=self.game._client,
        )
        self.note(f"rematch - generation {self.game.generation}")
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
        if self.player_id is not None and not self.game.is_remote and not self.game.is_players_turn(self.player_id):
            raise NotYourTurnError(f"It is not player {self.player_id}'s turn to move")
        result = self.game.move(line.strip())
        san = getattr(result, "san", None) or line.strip()
        self.note(f"played {san}")
        self.show()

    def run(self) -> int:
        """
        Read commands until EOF or ``quit``.

        :return: a process exit status — always 0; a failure to *reach* the
            server raises out of the session instead, because that is a setup
            problem rather than a move the player got wrong.
        """
        self.show()
        self.note("type `help` for commands")
        while True:
            self.stdout.write("\n> ")
            self.stdout.flush()
            line = self.stdin.readline()
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
            except (ChessError, GameError, ValueError) as e:
                # Expected: an illegal move, acting out of turn, a stale version.
                # Keep playing — the player simply types something else.
                self.error(f"{type(e).__name__}: {e}")
            # Only on the transition. Printing it after every command — `pgn`
            # and `fen` included — turns the one line that matters into noise.
            if self.game.is_over and not was_over:
                self.note("game over - `new` starts a rematch" if self.game.is_remote else "game over")


def run_session(game, **kwargs) -> int:
    """
    Build a :class:`Session` and run it.

    :param game: the :class:`chesssnake.Game` to play.
    :param kwargs: forwarded to :class:`Session`.
    :return: the process exit status.
    """
    return Session(game, **kwargs).run()
