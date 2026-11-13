"""
Remote-capable ``Game``, and :func:`connect` for talking to an api-endpoint.

Build games with the factory methods:

- ``Game.local(white_name, black_name)`` — a pure in-memory game (no network, no
  extra dependencies), where the engine runs in-process.
- ``Game.remote(game_id, client=...)`` — a game persisted on a ``chesssnake
  api-endpoint``, by its id. The **server** runs the engine: ``move``/``draw_*``/
  ``resign`` send a request and the returned state is mirrored locally (for
  rendering and the read accessors). Illegal moves raise the same ``ChessError``
  types you'd get locally.

Everything remote happens as a logged-in user, through an
:class:`~chesssnake.remote.client.ApiClient`. :func:`connect` builds one::

    client = connect("https://chess.example", username="alice", password="...")
    challenge = client.challenge("bob")              # bob accepts it...
    game = Game.remote(client.current_games()[0].id, client=client)
    game.move("e4")

Games are created by accepting a challenge (or by an administrator). Every action
carries the client's last-known ``version``, so a stale action is rejected
(``VersionConflictError``) rather than silently racing.
"""

import os

from ..db import errors
from ..dto import GameState, MoveResult
from ..engine.enums import Color
from ..engine.game import Game as BaseGame
from ..serialize import board_and_turn
from . import credentials

# Environment fallbacks for remote games. These must equal
# ``config.env_name("client", ...)``; a test asserts it, because this module
# deliberately does not import ``chesssnake.config`` -- doing so would pull
# pydantic onto the local-game path, which has no dependencies beyond Pillow.
# Unlike the server, the client reads only the environment, never a config file:
# a library that read ./chesssnake.toml from the caller's working directory
# would be surprising.
API_URL_ENV = "CHESSSNAKE__CLIENT__API_URL"
TOKEN_ENV = "CHESSSNAKE__CLIENT__TOKEN"


def connect(api_url=None, *, token=None, username=None, password=None, session=None):
    """
    An authenticated :class:`~chesssnake.remote.client.ApiClient`.

    The endpoint is ``api_url``, else ``$CHESSSNAKE__CLIENT__API_URL``. The
    credentials are, in order: ``username`` and ``password`` (logs in now), an
    explicit ``token``, ``$CHESSSNAKE__CLIENT__TOKEN``, or the token
    ``chesssnake login`` stored for that endpoint.

    :param session: a ``requests``-style session to use (mainly for testing).
    :raises ValueError: If no endpoint is given.
    :raises chesssnake.db.errors.AuthError: If no credentials can be found, or the
        login fails. Never prompts: this is a library.
    """
    from .client import ApiClient

    url = api_url or os.getenv(API_URL_ENV)
    if not url:
        raise ValueError(f"No api-endpoint: pass api_url or set {API_URL_ENV}.")
    client = ApiClient(url, session=session)
    if username is not None or password is not None:
        if username is None or password is None:
            raise ValueError("Pass both username and password, or neither.")
        client.login(username, password)
        return client
    stored = credentials.load(url)
    client.token = token or os.getenv(TOKEN_ENV) or (stored["token"] if stored else None)
    if not client.token:
        raise errors.AuthError(
            f"Not logged in to {url}: run `chesssnake login --api-url {url}`, set {TOKEN_ENV}, "
            "or pass token= or username= and password=."
        )
    return client


class Game(BaseGame):
    """
    A chess game that is local by default and remote when built via :meth:`remote`.

    Construct with the factory methods rather than calling ``Game(...)`` directly:
    :meth:`local` for an in-memory game, :meth:`remote` for a persisted one whose
    moves are computed by the api-endpoint.
    """

    def __init__(self, *args, client=None, player_id=None, version=None, generation=None, game_id=None, **kwargs):
        # Low-level constructor. Prefer Game.local() / Game.remote().
        self._client = client
        self.player_id = player_id
        self.version = version
        self.generation = generation
        #: The game's id on the server (``None`` for a local game). Stable for
        #: the game's whole life, archived or not: ``GET /v1/games/{id}``.
        self.id = game_id
        super().__init__(*args, **kwargs)

    # --- factories ---------------------------------------------------------

    @classmethod
    def local(cls, white_name: str = "", black_name: str = "") -> "Game":
        """Create a purely local, in-memory game (engine runs in-process)."""
        return cls(white_name=white_name, black_name=black_name)

    @classmethod
    def remote(
        cls,
        game_id,
        *,
        client=None,
        api_url: str | None = None,
        token: str | None = None,
        player_id: "int | str | None" = None,
    ) -> "Game":
        """
        Open a game on a chesssnake api-endpoint by its id (the server runs the engine).

        :param game_id: the game's id, or a ``GameState`` (e.g. from accepting a challenge).
        :param client: an :class:`~chesssnake.remote.client.ApiClient`; otherwise one is
            built with :func:`connect` from ``api_url``/``token`` or the environment.
        :param player_id: administrators only: the player (id or username) to act as.
            Everyone else always acts as themselves, which is the default.
        :raises chesssnake.db.errors.GameNotFoundError: If there is no such game.
        """
        client = client if client is not None else connect(api_url, token=token)
        if player_id is not None:
            player_id = client.resolve(player_id)
        state = client.get_game(getattr(game_id, "id", game_id))
        return cls.from_state(state, client=client, player_id=player_id)

    @classmethod
    def from_state(cls, state: GameState, *, client, player_id=None) -> "Game":
        """A remote game mirroring a ``GameState`` the server returned."""
        board, turn = board_and_turn(state)
        return cls(
            client=client,
            player_id=player_id,
            version=state.version,
            generation=state.generation,
            game_id=state.id,
            white_id=state.white_id,
            black_id=state.black_id,
            group_id=state.group_id,
            white_name=state.white_name,
            black_name=state.black_name,
            board=board,
            turn=turn,
            draw=state.draw,
        )

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
        self.id = state.id
        self.wname = state.white_name
        self.bname = state.black_name

    def _move_result(self, engine_move) -> MoveResult:
        """Wrap an engine ``Move`` (from a local move) into a public ``MoveResult``."""
        from ..serialize import state_from_game

        return MoveResult(
            state=state_from_game(self, self.version or 0, self.generation or 1, id=self.id),
            from_square=engine_move.from_square,
            to_square=engine_move.to_square,
            san=self.move_history[-1],
            check=self.board.is_check(),
            castle=engine_move.castle,
            promotion=engine_move.promotion.value if engine_move.promotion is not None else None,
            en=engine_move.en_passant,
            legal_moves=[] if self.is_over else self.legal_moves(),
        )

    # --- gameplay (local runs the engine; remote delegates to the server) --

    def move(self, move) -> MoveResult:  # type: ignore[override]
        if not self.is_remote:
            return self._move_result(super().move(move))

        result = self._client.move(self.id, move, self.player_id, self.version)
        self._apply_state(result.state)
        self.last_move = result  # its from_square/to_square drive the render highlight
        return result

    def _remote_action(self, method, player_id):
        pid = player_id if player_id is not None else self.player_id
        self._apply_state(getattr(self._client, method)(self.id, pid, self.version))

    def resign(self, player_id=None):
        if not self.is_remote:
            return super().resign(player_id if player_id is not None else self.player_id)
        self._remote_action("resign", player_id)

    def draw_offer(self, player_id=None):
        if not self.is_remote:
            return super().draw_offer(player_id if player_id is not None else self.player_id)
        self._remote_action("offer_draw", player_id)

    def draw_accept(self, player_id=None):
        if not self.is_remote:
            return super().draw_accept(player_id if player_id is not None else self.player_id)
        self._remote_action("accept_draw", player_id)

    def draw_decline(self, player_id=None):
        if not self.is_remote:
            return super().draw_decline(player_id if player_id is not None else self.player_id)
        self._remote_action("decline_draw", player_id)

    # --- reads -------------------------------------------------------------

    def legal_moves(self):
        """The legal moves in the current position (from the server if remote)."""
        if not self.is_remote:
            return super().legal_moves()
        return self._client.legal_moves(self.id)

    def pgn(self):
        """The game's PGN (from the server if remote)."""
        if not self.is_remote:
            return super().pgn()
        return self._client.pgn(self.id)

    def history(self):
        """The played moves as ``[{ply, san}]``."""
        if not self.is_remote:
            return [{"ply": i + 1, "san": san} for i, san in enumerate(self.move_history)]
        return self._client.history(self.id)

    def refresh(self):
        """Re-fetch this game's latest state from the server (e.g. after the opponent moved)."""
        if self.is_remote:
            self._apply_state(self._client.get_game(self.id))
