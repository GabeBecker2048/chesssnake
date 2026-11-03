"""
Remote-capable ``Game`` and challenge helpers.

Build games with the factory methods:

- ``Game.local(white_name, black_name)`` — a pure in-memory game (no network, no
  extra dependencies), where the engine runs in-process.
- ``Game.remote(white, black, group_id=..., api_url=..., player_id=...)`` — a game
  persisted through a ``chesssnake api-endpoint``, between two users given by id or
  username. For remote games the **server** runs the engine:
  ``move``/``draw_*``/``resign`` send a request and the returned state is mirrored
  locally (for rendering and the read accessors). Illegal moves raise the same
  ``ChessError`` types you'd get locally.

Players are accounts on the api-endpoint: create them with :func:`create_user`, or
let an integration map its own ids onto them with :func:`user_for_identity`. Their
usernames are what the board and PGN show.

If constructed with ``player_id=``, that player is sent (and validated server-side)
on every action. Every action also carries the client's last-known ``version`` and
``generation``, so a stale action is rejected (``VersionConflictError``, or
``GenerationConflictError`` once the game it was aimed at is over) rather than
silently racing or landing in a rematch.
"""

import os

from ..dto import GameState, MoveResult, User
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
        white: "int | str",
        black: "int | str",
        group_id: int = 0,
        *,
        player_id: "int | str | None" = None,
        generation: int | None = None,
        api_url: str | None = None,
        api_key: str | None = None,
        client=None,
    ) -> "Game":
        """
        Load-or-create a game on a chesssnake api-endpoint (the server runs the engine).

        :param white: the white player, as a user id or a username.
        :param black: the black player, as a user id or a username.
        :param group_id: a namespace of your choosing; the same two players can
            have one game in progress per group.
        :param player_id: if given (an id or a username), this player is asserted
            on every action (the server rejects out-of-turn / non-participant
            actions with 403).
        :param generation: load a specific past game (read-only) instead of the current
            one; ``None`` (default) loads/creates the current game.
        :param api_url: base URL of the api-endpoint (falls back to ``CHESSSNAKE__CLIENT__API_URL``).
        :param api_key: optional API key sent with every request.
        :param client: an injected ``ApiClient`` (mainly for testing).
        :raises UserNotFoundError: if a player does not exist.
        """
        client = _make_client(api_url, client, api_key)
        white_id = _resolve_id(client, white)
        black_id = _resolve_id(client, black)
        if player_id is not None:
            player_id = _resolve_id(client, player_id)
        if generation is None:
            state = client.get_or_create_game(group_id, white_id, black_id)
        else:
            state = client.get_state(group_id, white_id, black_id, generation)
        board, turn = board_and_turn(state)
        return cls(
            client=client,
            player_id=player_id,
            version=state.version,
            generation=state.generation,
            game_id=state.id,
            white_id=white_id,
            black_id=black_id,
            group_id=group_id,
            white_name=state.white_name,
            black_name=state.black_name,
            board=board,
            turn=turn,
            draw=state.draw,
        )

    @classmethod
    def archive(cls, white, black, group_id=0, *, api_url=None, api_key=None, client=None) -> list[GameState]:
        """Every game (generation) between two players in a group, oldest first."""
        client = _make_client(api_url, client, api_key)
        return client.archive(group_id, _resolve_id(client, white), _resolve_id(client, black))

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

        result = self._client.move(self.gid, self.wid, self.bid, move, self.player_id, self.version, self.generation)
        self._apply_state(result.state)
        i1, j1 = Board.get_coords(result.from_square)
        i2, j2 = Board.get_coords(result.to_square)
        self.last_move = _MoveMarker(Square(i1, j1), Square(i2, j2))  # type: ignore[assignment]
        return result

    def resign(self, player_id=None):
        pid = player_id if player_id is not None else self.player_id
        if not self.is_remote:
            return super().resign(pid)
        self._apply_state(self._client.resign(self.gid, self.wid, self.bid, pid, self.version, self.generation))

    def draw_offer(self, player_id=None):
        pid = player_id if player_id is not None else self.player_id
        if not self.is_remote:
            return super().draw_offer(pid)
        self._apply_state(self._client.offer_draw(self.gid, self.wid, self.bid, pid, self.version, self.generation))

    def draw_accept(self, player_id=None):
        pid = player_id if player_id is not None else self.player_id
        if not self.is_remote:
            return super().draw_accept(pid)
        self._apply_state(self._client.accept_draw(self.gid, self.wid, self.bid, pid, self.version, self.generation))

    def draw_decline(self, player_id=None):
        pid = player_id if player_id is not None else self.player_id
        if not self.is_remote:
            return super().draw_decline(pid)
        self._apply_state(self._client.decline_draw(self.gid, self.wid, self.bid, pid, self.version, self.generation))

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


def _resolve_id(client, who) -> int:
    """A user id as given, or the id of the user with that username."""
    if isinstance(who, bool):
        raise TypeError(f"A player is a user id or a username, not {who!r}")
    if isinstance(who, int):
        return who
    if isinstance(who, str):
        return client.get_user_by_name(who).id
    raise TypeError(f"A player is a user id or a username, not {who!r}")


# --- user helpers (module-level functions) ---------------------------------


def create_user(username, *, api_url=None, api_key=None, client=None) -> User:
    """Create a user on the api-endpoint. The server assigns the id."""
    return _make_client(api_url, client, api_key).create_user(username)


def get_user(user, *, api_url=None, api_key=None, client=None) -> User:
    """Look a user up by id (an int) or username (a str)."""
    client = _make_client(api_url, client, api_key)
    if isinstance(user, str):
        return client.get_user_by_name(user)
    return client.get_user(user)


def user_for_identity(provider, external_id, username, *, api_url=None, api_key=None, client=None) -> User:
    """
    The user linked to an id from another system, created on first use.

    This is the one call an integration needs: a Discord bot, say, passes
    ``("discord", str(member.id), member.name)`` and gets back the same user
    every time, with a chesssnake id to play games under. ``username`` is used
    only when the user is created.
    """
    return _make_client(api_url, client, api_key).get_or_create_user_by_identity(provider, str(external_id), username)


# --- challenge helpers (module-level functions) ----------------------------
#
# Players are user ids or usernames here too, like Game.remote.


def challenge(challenger, opponent, group_id=0, *, api_url=None, api_key=None, client=None):
    """Issue or accept a challenge. Returns ``True`` if an existing challenge was accepted."""
    client = _make_client(api_url, client, api_key)
    return client.challenge(_resolve_id(client, challenger), _resolve_id(client, opponent), group_id)


def challenge_exists(player1, player2, group_id=0, *, api_url=None, api_key=None, client=None):
    """Return the pending challenge between two players, or ``None``."""
    client = _make_client(api_url, client, api_key)
    return client.challenge_exists(_resolve_id(client, player1), _resolve_id(client, player2), group_id)


def delete_challenge(challenger, challenged, group_id=0, *, api_url=None, api_key=None, client=None):
    """Delete a pending challenge."""
    client = _make_client(api_url, client, api_key)
    client.delete_challenge(_resolve_id(client, challenger), _resolve_id(client, challenged), group_id)


def record(player1, player2, group_id=0, *, api_url=None, api_key=None, client=None):
    """Win/draw/loss record between two players across their finished games in a group."""
    client = _make_client(api_url, client, api_key)
    return client.record(_resolve_id(client, player1), _resolve_id(client, player2), group_id)
