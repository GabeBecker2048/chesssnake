"""
Remote-capable ``Game`` and challenge helpers.

Build games with the factory methods:

- ``Game.local(white_name, black_name)`` — a pure in-memory game (no network, no
  extra dependencies), where the engine runs in-process.
- ``Game.remote(white_id, black_id, group_id=..., api_url=...)`` — a game persisted
  through a ``chesssnake api-endpoint``. For remote games the **server** runs the
  engine: ``move`` and the draw actions send a request and the returned state is
  mirrored locally (for rendering and the read accessors). Illegal moves raise the
  same ``ChessError`` types you'd get locally.
"""

import os

from ..dto import GameState, MoveResult
from ..engine import Board, Square
from ..engine.enums import Color
from ..engine.game import Game as BaseGame
from ..serialize import board_from_state, state_from_game


class _MoveMarker:
    """Minimal last-move holder (prev/to squares) for render highlighting."""

    __slots__ = ("prev", "to")

    def __init__(self, prev, to):
        self.prev = prev
        self.to = to


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
    :meth:`local` for an in-memory game, :meth:`remote` for a persisted one whose
    moves are computed by the api-endpoint.
    """

    def __init__(self, *args, client=None, **kwargs):
        # Low-level constructor. Prefer Game.local() / Game.remote().
        self._client = client
        super().__init__(*args, **kwargs)

    # --- factories ---------------------------------------------------------

    @classmethod
    def local(cls, white_name: str = "", black_name: str = "") -> "Game":
        """Create a purely local, in-memory game (engine runs in-process)."""
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
    ) -> "Game":
        """
        Load-or-create a game on a chesssnake api-endpoint (the server runs the engine).

        Games are keyed by ``(group_id, white_id, black_id)``. If a matching game
        exists it is loaded; otherwise a new one is created.

        :param api_url: Base URL of the api-endpoint (falls back to ``CHESSSNAKE_API_URL``).
        :param api_key: Optional API key sent with every request.
        :param client: An injected ``ApiClient`` (mainly for testing).
        """
        client = _make_client(api_url, client, api_key)
        state = client.get_or_create_game(group_id, white_id, black_id, white_name, black_name)
        return cls(
            client=client,
            white_id=white_id,
            black_id=black_id,
            group_id=group_id,
            white_name=state.wname if state.wname is not None else white_name,
            black_name=state.bname if state.bname is not None else black_name,
            board=board_from_state(state),
            turn=state.turn,
            draw=state.draw,
        )

    @property
    def is_remote(self) -> bool:
        """Whether this game is backed by a remote api-endpoint."""
        return self._client is not None

    # --- local mirror of server state --------------------------------------

    def _apply_state(self, state: GameState):
        """Refresh the local board/turn/draw mirror from a server ``GameState``."""
        self.board = board_from_state(state)  # also restores board.status
        self.turn = Color(state.turn)
        self.draw = Color(state.draw) if state.draw is not None else None
        if state.wname is not None:
            self.wname = state.wname
        if state.bname is not None:
            self.bname = state.bname

    def _move_result(self, engine_move) -> MoveResult:
        """Wrap an engine ``Move`` (from a local move) into a public ``MoveResult``."""
        return MoveResult(
            state=state_from_game(self),
            from_square=engine_move.prev.c_notation,
            to_square=engine_move.to.c_notation,
            check=self.board.check_for_check(self.turn),
            castle=engine_move.castle,
            promotion=engine_move.promotion,
            en=engine_move.en,
        )

    # --- gameplay (local runs the engine; remote delegates to the server) --

    # The public Game deliberately returns the richer MoveResult (not the engine's
    # bare Move); last_move likewise holds a lightweight render marker for remote games.
    def move(self, move) -> MoveResult:  # type: ignore[override]
        if not self.is_remote:
            return self._move_result(super().move(move))

        result = self._client.move(self.gid, self.wid, self.bid, move)
        self._apply_state(result.state)
        i1, j1 = Board.get_coords(result.from_square)
        i2, j2 = Board.get_coords(result.to_square)
        self.last_move = _MoveMarker(Square(i1, j1), Square(i2, j2))  # type: ignore[assignment]
        return result

    def draw_offer(self, player_id):
        if not self.is_remote:
            return super().draw_offer(player_id)
        self._apply_state(self._client.offer_draw(self.gid, self.wid, self.bid, player_id))

    def draw_accept(self, player_id):
        if not self.is_remote:
            return super().draw_accept(player_id)
        self._apply_state(self._client.accept_draw(self.gid, self.wid, self.bid, player_id))

    def draw_decline(self, player_id):
        if not self.is_remote:
            return super().draw_decline(player_id)
        self._apply_state(self._client.decline_draw(self.gid, self.wid, self.bid, player_id))

    # --- remote lifecycle --------------------------------------------------

    def refresh(self):
        """Re-fetch the latest state from the server (e.g. after the opponent moved)."""
        if self.is_remote:
            self._apply_state(self._client.get_state(self.gid, self.wid, self.bid))

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
