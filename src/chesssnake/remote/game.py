"""
Remote-capable ``Game`` and challenge helpers.

Build games with the factory methods:

- ``Game.local(white_name, black_name)`` — a pure in-memory game (no network, no
  extra dependencies), where the engine runs in-process.
- ``Game.remote(white_id, black_id, group_id=..., api_url=..., player_id=...)`` — a
  game persisted through a ``chesssnake api-endpoint``. For remote games the
  **server** runs the engine: ``move``/``draw_*``/``resign`` send a request and the
  returned state is mirrored locally (for rendering and the read accessors). Illegal
  moves raise the same ``ChessError`` types you'd get locally.

If constructed with ``player_id=``, that player is sent (and validated server-side)
on every action, and the client sends its last-known ``version`` so a stale action
is rejected (``VersionConflictError``) rather than silently racing.
"""

import os

from ..dto import GameState, MoveResult
from ..engine import Board, Square
from ..engine.enums import Color
from ..engine.game import Game as BaseGame
from ..serialize import board_and_turn


class _MoveMarker:
    """Minimal last-move holder (prev/to squares) for render highlighting."""

    __slots__ = ("prev", "to")

    def __init__(self, prev, to):
        self.prev = prev
        self.to = to


# Environment fallbacks for remote games. These must equal
# ``config.env_name("client", ...)``; a test asserts it, because this module
# deliberately does not import ``chesssnake.config`` -- doing so would pull
# pydantic onto the local-game path, which has no dependencies beyond Pillow.
# Unlike the server, the client reads only the environment, never a config file:
# a library that read ./chesssnake.toml from the caller's working directory
# would be surprising.
API_URL_ENV = "CHESSSNAKE__CLIENT__API_URL"
API_KEY_ENV = "CHESSSNAKE__CLIENT__API_KEY"


def _make_client(api_url=None, client=None, api_key=None):
    """Build (or accept an injected) ApiClient for remote operations."""
    if client is not None:
        return client
    from .client import ApiClient

    url = api_url or os.getenv(API_URL_ENV)
    if not url:
        raise ValueError(f"A remote game requires an api_url argument or the {API_URL_ENV} environment variable.")
    return ApiClient(url, api_key=api_key or os.getenv(API_KEY_ENV))


class Game(BaseGame):
    """
    A chess game that is local by default and remote when built via :meth:`remote`.

    Construct with the factory methods rather than calling ``Game(...)`` directly:
    :meth:`local` for an in-memory game, :meth:`remote` for a persisted one whose
    moves are computed by the api-endpoint.
    """

    def __init__(self, *args, client=None, player_id=None, version=None, generation=None, **kwargs):
        # Low-level constructor. Prefer Game.local() / Game.remote().
        self._client = client
        self.player_id = player_id
        self.version = version
        self.generation = generation
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
        player_id: int | None = None,
        generation: int | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
        client=None,
    ) -> "Game":
        """
        Load-or-create a game on a chesssnake api-endpoint (the server runs the engine).

        :param player_id: if given, this player is asserted on every action (the
            server rejects out-of-turn / non-participant actions with 403).
        :param generation: load a specific past game (read-only) instead of the current
            one; ``None`` (default) loads/creates the current game.
        :param api_url: base URL of the api-endpoint (falls back to ``CHESSSNAKE__CLIENT__API_URL``).
        :param api_key: optional API key sent with every request.
        :param client: an injected ``ApiClient`` (mainly for testing).
        """
        client = _make_client(api_url, client, api_key)
        if generation is None:
            state = client.get_or_create_game(group_id, white_id, black_id, white_name, black_name)
        else:
            state = client.get_state(group_id, white_id, black_id, generation)
        board, turn = board_and_turn(state)
        game = cls(
            client=client,
            player_id=player_id,
            version=state.version,
            generation=state.generation,
            white_id=white_id,
            black_id=black_id,
            group_id=group_id,
            white_name=state.wname if state.wname is not None else white_name,
            black_name=state.bname if state.bname is not None else black_name,
            board=board,
            turn=turn,
            draw=state.draw,
        )
        return game

    @classmethod
    def archive(cls, white_id, black_id, group_id=0, *, api_url=None, api_key=None, client=None):
        """List all games (generations) for a triple — summaries, oldest first."""
        return _make_client(api_url, client, api_key).archive(group_id, white_id, black_id)

    @property
    def is_remote(self) -> bool:
        """Whether this game is backed by a remote api-endpoint."""
        return self._client is not None

    # --- local mirror of server state --------------------------------------

    def _apply_state(self, state: GameState):
        """Refresh the local board/turn/draw/version mirror from a server ``GameState``."""
        self.board, self.turn = board_and_turn(state)
        self.draw = Color(state.draw) if state.draw is not None else None
        self.version = state.version
        self.generation = state.generation
        if state.wname is not None:
            self.wname = state.wname
        if state.bname is not None:
            self.bname = state.bname

    def _move_result(self, engine_move) -> MoveResult:
        """Wrap an engine ``Move`` (from a local move) into a public ``MoveResult``."""
        from ..serialize import state_from_game

        return MoveResult(
            state=state_from_game(self, self.version or 0, self.generation or 1),
            from_square=engine_move.prev.c_notation,
            to_square=engine_move.to.c_notation,
            san=self.move_history[-1],
            check=self.board.check_for_check(self.turn),
            castle=engine_move.castle,
            promotion=engine_move.promotion,
            en=engine_move.en,
        )

    # --- gameplay (local runs the engine; remote delegates to the server) --

    def move(self, move) -> MoveResult:  # type: ignore[override]
        if not self.is_remote:
            return self._move_result(super().move(move))

        result = self._client.move(self.gid, self.wid, self.bid, move, self.player_id, self.version)
        self._apply_state(result.state)
        i1, j1 = Board.get_coords(result.from_square)
        i2, j2 = Board.get_coords(result.to_square)
        self.last_move = _MoveMarker(Square(i1, j1), Square(i2, j2))  # type: ignore[assignment]
        return result

    def resign(self, player_id=None):
        pid = player_id if player_id is not None else self.player_id
        if not self.is_remote:
            return super().resign(pid)
        self._apply_state(self._client.resign(self.gid, self.wid, self.bid, pid, self.version))

    def draw_offer(self, player_id=None):
        pid = player_id if player_id is not None else self.player_id
        if not self.is_remote:
            return super().draw_offer(pid)
        self._apply_state(self._client.offer_draw(self.gid, self.wid, self.bid, pid, self.version))

    def draw_accept(self, player_id=None):
        pid = player_id if player_id is not None else self.player_id
        if not self.is_remote:
            return super().draw_accept(pid)
        self._apply_state(self._client.accept_draw(self.gid, self.wid, self.bid, pid, self.version))

    def draw_decline(self, player_id=None):
        pid = player_id if player_id is not None else self.player_id
        if not self.is_remote:
            return super().draw_decline(pid)
        self._apply_state(self._client.decline_draw(self.gid, self.wid, self.bid, pid, self.version))

    # --- reads -------------------------------------------------------------

    def legal_moves(self):
        """The legal moves in the current position (from the server if remote)."""
        if not self.is_remote:
            return super().legal_moves()
        return self._client.legal_moves(self.gid, self.wid, self.bid, self.generation)

    def pgn(self):
        """The game's PGN (from the server if remote)."""
        if not self.is_remote:
            return super().pgn()
        return self._client.pgn(self.gid, self.wid, self.bid, self.generation)

    def history(self):
        """The played moves as ``[{ply, san}]`` (remote only; local: use move_history)."""
        if not self.is_remote:
            return [{"ply": i + 1, "san": san} for i, san in enumerate(self.move_history)]
        return self._client.history(self.gid, self.wid, self.bid, self.generation)

    def refresh(self):
        """Re-fetch this game's latest state from the server (e.g. after the opponent moved)."""
        if self.is_remote:
            self._apply_state(self._client.get_state(self.gid, self.wid, self.bid, self.generation))

    def end(self):
        """If the game is over, delete it from the remote database. Returns True if ended."""
        if self.is_over:
            if self.is_remote:
                self._client.delete_game(self.gid, self.wid, self.bid, self.generation)
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


def record(player1, player2, group_id=0, *, api_url=None, api_key=None, client=None):
    """Win/draw/loss record between two players across their finished games in a group."""
    return _make_client(api_url, client, api_key).record(player1, player2, group_id)
