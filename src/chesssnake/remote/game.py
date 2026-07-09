"""
Remote-capable ``Game`` and challenge helpers.

Build games with the factory methods:

- ``Game.local(white_name, black_name)`` — a pure in-memory game (no network, no
  extra dependencies), identical to the raw engine.
- ``Game.remote(white_id, black_id, group_id=..., api_url=...)`` — load-or-create
  and persist the game through a ``chesssnake api-endpoint`` REST server. The chess
  engine still runs locally; only serialized state crosses the wire, so many
  clients can share one database.

Remote games default to ``auto_sync=True`` (every move/draw is pushed to the
server). They are also context managers that sync on exit, so state is never
silently dropped even with ``auto_sync=False``.
"""

import os

from ..dto import GameState
from ..engine import Board, Square
from ..engine.enums import GameStatus
from ..engine.game import Game as BaseGame


def _make_client(api_url=None, client=None, api_key=None):
    """Build (or accept an injected) ApiClient for remote operations."""
    if client is not None:
        return client
    from .client import ApiClient

    url = api_url or os.getenv("CHESSSNAKE_API_URL")
    if not url:
        raise ValueError("A remote game requires an api_url argument or the CHESSSNAKE_API_URL environment variable.")
    return ApiClient(url, api_key=api_key)


class Game(BaseGame):
    """
    A chess game that is local by default and remote when built via :meth:`remote`.

    Construct with the factory methods rather than calling ``Game(...)`` directly:
    :meth:`local` for an in-memory game, :meth:`remote` for a persisted one.
    """

    def __init__(self, *args, client=None, auto_sync=False, **kwargs):
        # Low-level constructor. Prefer Game.local() / Game.remote().
        self._client = client
        self.auto_sync = bool(auto_sync and client is not None)
        super().__init__(*args, **kwargs)

    # --- factories ---------------------------------------------------------

    @classmethod
    def local(cls, white_name: str = "", black_name: str = "") -> "Game":
        """Create a purely local, in-memory game (no server, no persistence)."""
        return cls(white_name=white_name, black_name=black_name)

    @classmethod
    def remote(
        cls,
        white_id: int,
        black_id: int,
        group_id: int = 0,
        *,
        white_name: str = "",
        black_name: str = "",
        api_url: str | None = None,
        api_key: str | None = None,
        client=None,
        auto_sync: bool = True,
    ) -> "Game":
        """
        Load-or-create a persisted game via a chesssnake api-endpoint.

        Games are keyed by ``(group_id, white_id, black_id)``. If a matching game
        exists it is loaded; otherwise a new one is created.

        :param api_url: Base URL of the api-endpoint (falls back to ``CHESSSNAKE_API_URL``).
        :param api_key: Optional API key sent with every request.
        :param client: An injected ``ApiClient`` (mainly for testing).
        :param auto_sync: Push state to the server after every move/draw (default ``True``).
        """
        client = _make_client(api_url, client, api_key)
        state = client.get_or_create_game(group_id, white_id, black_id, white_name, black_name)
        return cls(
            client=client,
            auto_sync=auto_sync,
            white_id=white_id,
            black_id=black_id,
            group_id=group_id,
            white_name=state.wname if state.wname is not None else white_name,
            black_name=state.bname if state.bname is not None else black_name,
            board=cls._board_from_state(state),
            turn=state.turn,
            draw=state.draw,
        )

    @property
    def is_remote(self) -> bool:
        """Whether this game is backed by a remote api-endpoint."""
        return self._client is not None

    # --- context manager (syncs on exit) -----------------------------------

    def __enter__(self) -> "Game":
        return self

    def __exit__(self, *exc):
        # Push the latest state on a clean exit so a forgotten sync() can't drop moves.
        if exc[0] is None:
            self.sync()
        return False

    # --- state (de)serialization ------------------------------------------

    @staticmethod
    def _board_from_state(state: GameState) -> Board:
        if state.pawnmove is not None:
            i, j = Board.get_coords(state.pawnmove)
            pawnmove = Square(i, j)
        else:
            pawnmove = None
        board = Board(
            board=Board.assemble_board(state.board, state.moved),
            two_moveP=pawnmove,
        )
        board.status = GameStatus(int(state.status))
        return board

    def _state_payload(self) -> GameState:
        boardstring, moved = Board.disassemble_board(self.board)
        return GameState(
            board=boardstring,
            turn=int(self.turn),
            moved=moved,
            status=int(self.board.status),
            pawnmove=self.board.two_moveP.c_notation if self.board.two_moveP else None,
            draw=int(self.draw) if self.draw is not None else None,
            wname=self.wname,
            bname=self.bname,
        )

    # --- persistence -------------------------------------------------------

    def sync(self):
        """Push the current full game state to the api-endpoint (no-op for local games)."""
        if self.is_remote:
            self._client.update_game(self.gid, self.wid, self.bid, self._state_payload())

    def move(self, move):
        result = super().move(move)
        if self.auto_sync:
            self.sync()
        return result

    def draw_offer(self, player_id):
        super().draw_offer(player_id)
        if self.auto_sync:
            self._client.update_draw(
                self.gid, self.wid, self.bid, int(self.draw) if self.draw is not None else None, int(self.board.status)
            )

    def draw_accept(self, player_id):
        super().draw_accept(player_id)
        if self.auto_sync:
            self._client.update_draw(
                self.gid, self.wid, self.bid, int(self.draw) if self.draw is not None else None, int(self.board.status)
            )

    def draw_decline(self, player_id):
        super().draw_decline(player_id)
        if self.auto_sync:
            self._client.clear_draw(self.gid, self.wid, self.bid)

    def end(self):
        """If the game is over, delete it from the remote database. Returns True if ended."""
        if self.is_over:
            if self.is_remote:
                self._client.delete_game(self.gid, self.wid, self.bid)
            return True
        return False


# --- challenge helpers (module-level functions) ----------------------------


def challenge(challenger, opponent, group_id=0, *, api_url=None, api_key=None, client=None):
    """Issue or accept a challenge. Returns ``True`` if an existing challenge was accepted."""
    return _make_client(api_url, client, api_key).challenge(challenger, opponent, group_id)


def challenge_exists(player1, player2, group_id=0, *, api_url=None, api_key=None, client=None):
    """Return the pending challenge between two players, or ``None``."""
    return _make_client(api_url, client, api_key).challenge_exists(player1, player2, group_id)


def delete_challenge(challenger, challenged, group_id=0, *, api_url=None, api_key=None, client=None):
    """Delete a pending challenge."""
    _make_client(api_url, client, api_key).delete_challenge(challenger, challenged, group_id)
