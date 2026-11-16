"""
HTTP clients for the chesssnake api-endpoint: :class:`ApiClient` (blocking, on
``requests``) and :class:`~chesssnake.remote.async_client.AsyncApiClient`
(``asyncio``, on ``httpx``).

**Every route is declared once**, in :class:`_Routes`, which both clients inherit.
A route method builds a :class:`_Call` (method, path, parameters, and how to read
the answer) and hands it to the client's ``_run``: :class:`ApiClient` sends it and
returns the result, :class:`AsyncApiClient` returns a coroutine that does. So
``client.move(...)`` and ``await async_client.move(...)`` are the same code, and a
route added here reaches both. A method that needs an earlier answer first (a
username to resolve to an id, say) chains through ``_then``, which applies a
function at once on the blocking client and after an ``await`` on the async one.

Each route method is tagged with :func:`route`, the ``(method, path)`` it calls,
which ``tests/config/test_client_coverage.py`` compares with the server's routes.

The session can be injected (the test-suite passes a Starlette ``TestClient``,
which is ``requests``-compatible), so the same client code drives both a real
server and an in-process app.

The server owns the chess engine: the client sends *moves* and receives new
state (or a structured error). Non-2xx responses are translated back into the
matching engine (``ChessError``) or persistence (``GameError``) exception types so
callers see the same exceptions they would from a local game.

All routes are served under the versioned ``/v1`` prefix, and all but logging in,
registering and :meth:`~_Routes.info` need a token, sent as ``Authorization:
Bearer <token>``. Get one with :meth:`~_Routes.login`, or use
:func:`chesssnake.connect`, which also finds a token stored by ``chesssnake login``
or set in the environment.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..db import errors as db_errors
from ..dto import Challenge, GameState, LoginResult, MoveResult, TokenInfo, User
from ..engine import errors as chess_errors

# All endpoints live under this version prefix.
API_PREFIX = "/v1"


def _build_error_registry():
    """Map exception class name -> class for every engine and persistence error."""
    registry = {}
    for module, base in ((chess_errors, chess_errors.ChessError), (db_errors, db_errors.GameError)):
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, base):
                registry[name] = obj
    return registry


_ERROR_REGISTRY = _build_error_registry()


def _id(value):
    """An id from an int or from something that has one (a ``User``, ``GameState``, ``Challenge``)."""
    return getattr(value, "id", value)


def raise_for_response(resp) -> None:
    """
    Raise the error a failed response describes, as its own class.

    Works for any response with ``status_code``, ``json()`` and ``text``
    (``requests`` and ``httpx`` both qualify).
    """
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    error_type = data.get("error_type", "GameError")
    detail = data.get("detail") or resp.text
    cls = _ERROR_REGISTRY.get(error_type, db_errors.GameError)
    # Many engine errors have custom constructors (they take a square, a piece
    # type, etc.), so bypass __init__ and set the message directly: this
    # preserves the exact type for `except PromotionError` while carrying the
    # server's detail message.
    exc = cls.__new__(cls)
    exc.args = (detail,)
    raise exc


def route(method: str, path: str):
    """Tag a client method with a ``/v1`` route it calls (path as the server declares it)."""

    def tag(fn):
        fn.__routes__ = [*getattr(fn, "__routes__", []), (method, path)]
        return fn

    return tag


@dataclass
class _Call:
    """One HTTP request and how to read its answer."""

    method: str
    path: str
    params: dict | None = None
    json: Any = None
    #: What to return: ``json`` (decoded, then ``parse``d), ``text``, ``bytes`` or ``none``.
    read: str = "json"
    parse: Callable[[Any], Any] | None = None
    #: Send no token even if the client has one (logging in as someone else).
    anonymous: bool = False

    def result(self, resp):
        if self.read == "none":
            return None
        if self.read == "text":
            return resp.text
        if self.read == "bytes":
            return resp.content
        data = resp.json() if resp.content else None
        return self.parse(data) if self.parse is not None else data


def _without_none(**values) -> dict:
    return {key: value for key, value in values.items() if value is not None}


class _Routes:
    """
    Every route, once. Subclasses provide ``_run(call)``, ``_then(value, fn)`` and
    ``_done(value)``; see the module docstring.
    """

    base_url: str
    token: str | None

    # --- transport hooks ------------------------------------------------------------

    def _run(self, call: _Call):  # pragma: no cover - abstract
        raise NotImplementedError

    def _then(self, value, fn):  # pragma: no cover - abstract
        raise NotImplementedError

    def _done(self, value):  # pragma: no cover - abstract
        raise NotImplementedError

    def _resolved(self, who, fn):
        """``fn(user_id)`` once ``who`` (an id, a ``User`` or a username) is an id."""
        if isinstance(who, bool):
            raise TypeError(f"A player is a user id or a username, not {who!r}")
        if isinstance(who, str):
            return self._then(self.get_user(who), lambda user: fn(user.id))
        return self._then(self._done(int(_id(who))), fn)

    def _resolved_pair(self, a, b, fn):
        return self._resolved(a, lambda first: self._resolved(b, lambda second: fn(first, second)))

    def _logged_in(self, data) -> LoginResult:
        result = LoginResult.from_dict(data)
        self.token = result.token
        return result

    # --- server -------------------------------------------------------------------

    @route("GET", "/v1/info")
    def info(self) -> dict:
        """What the server offers before logging in: ``version``, ``registration``, ``websocket``."""
        return self._run(_Call("GET", "/info", anonymous=True))

    # --- account -----------------------------------------------------------

    @route("POST", "/v1/auth/login")
    def login(self, username, password) -> LoginResult:
        """Log in; the session token is kept on this client for every later call."""
        body = {"username": username, "password": password}
        return self._run(_Call("POST", "/auth/login", json=body, parse=self._logged_in, anonymous=True))

    @route("POST", "/v1/auth/register")
    def register(self, username, password) -> LoginResult:
        """Create an account (only when the server allows registration) and log in as it."""
        body = {"username": username, "password": password}
        return self._run(_Call("POST", "/auth/register", json=body, parse=self._logged_in, anonymous=True))

    @route("POST", "/v1/auth/logout")
    def logout(self):
        """Revoke this client's token on the server and forget it."""

        def forget(_data):
            self.token = None

        return self._run(_Call("POST", "/auth/logout", parse=forget))

    @route("GET", "/v1/auth/me")
    def me(self) -> User:
        """The user this client is logged in as."""
        return self._run(_Call("GET", "/auth/me", parse=User.from_dict))

    @route("POST", "/v1/auth/password")
    def change_password(self, current_password, new_password):
        """Change your password; your other login sessions end, this one and api tokens stay."""
        body = {"current_password": current_password, "new_password": new_password}
        return self._run(_Call("POST", "/auth/password", json=body, read="none"))

    @route("POST", "/v1/auth/tokens")
    def create_token(self, name, current_password, expires_in_days=None) -> LoginResult:
        """Create a named api token (for a script or bot). Its secret is only ever shown here."""
        body = {"name": name, "current_password": current_password, "expires_in_days": expires_in_days}
        return self._run(_Call("POST", "/auth/tokens", json=body, parse=LoginResult.from_dict))

    @route("GET", "/v1/auth/tokens")
    def tokens(self, user_id=None) -> list[TokenInfo]:
        return self._run(
            _Call(
                "GET",
                "/auth/tokens",
                params=_without_none(user_id=user_id),
                parse=lambda data: [TokenInfo.from_dict(t) for t in data["tokens"]],
            )
        )

    @route("DELETE", "/v1/auth/tokens/{token_id}")
    def revoke_token(self, token_id):
        return self._run(_Call("DELETE", f"/auth/tokens/{_id(token_id)}", read="none"))

    @route("GET", "/v1/auth/settings")
    def settings(self) -> dict:
        """Your per-user settings, e.g. ``{"auto_queen": False}``, defaults filled in."""
        return self._run(_Call("GET", "/auth/settings"))

    @route("PATCH", "/v1/auth/settings")
    def update_settings(self, **changes) -> dict:
        """Change some of your settings (``update_settings(auto_queen=True)``); returns them all."""
        return self._run(_Call("PATCH", "/auth/settings", json=changes))

    @route("POST", "/v1/auth/link-code")
    def link_code(self) -> dict:
        """
        A one-time code (``{"code": "ABCD-EFGH", "expires_at": ...}``) that links an
        outside account, such as Discord, to yours: give it to the bot, which
        redeems it with :meth:`redeem_link_code`. A new code cancels the last one.
        """
        return self._run(_Call("POST", "/auth/link-code"))

    # --- users -------------------------------------------------------------

    @route("GET", "/v1/users")
    @route("GET", "/v1/users/{user_id}")
    def get_user(self, who) -> User:
        """A user by id (an int, or anything with an ``id``) or by username (a str; case
        does not matter)."""
        if isinstance(who, str):
            return self._run(_Call("GET", "/users", params={"username": who}, parse=User.from_dict))
        return self._run(_Call("GET", f"/users/{_id(who)}", parse=User.from_dict))

    def resolve(self, who) -> int:
        """A user id from an id, a username, or a ``User``."""
        return self._resolved(who, lambda user_id: user_id)

    @route("GET", "/v1/users/search")
    def search_users(self, query="", limit=20, offset=0) -> list[User]:
        """Users whose name starts with ``query`` (ignoring case), by name; ``""`` lists everyone."""
        params = {"q": query, "limit": limit, "offset": offset}
        return self._run(
            _Call("GET", "/users/search", params=params, parse=lambda d: [User.from_dict(u) for u in d["users"]])
        )

    @route("PATCH", "/v1/users/{user_id}")
    def update_user(self, user_id, *, username=None, role=None, disabled=None, password=None) -> User:
        """
        Change an account. Anyone may change their own ``username``; ``role``,
        ``disabled``, ``password`` and other people's accounts need an administrator.
        (Change your own password with :meth:`change_password`.)
        """
        body = _without_none(username=username, role=role, disabled=disabled, password=password)
        return self._run(_Call("PATCH", f"/users/{_id(user_id)}", json=body, parse=User.from_dict))

    # Administrator only:

    @route("POST", "/v1/users")
    def create_user(self, username, password=None, role="user") -> User:
        body = {"username": username, "password": password, "role": role}
        return self._run(_Call("POST", "/users", json=body, parse=User.from_dict))

    @route("GET", "/v1/identities/{provider}/{external_id}")
    def get_user_by_identity(self, provider, external_id) -> User:
        """The user linked to an external id, e.g. ``("discord", "1234")``."""
        return self._run(_Call("GET", f"/identities/{provider}/{external_id}", parse=User.from_dict))

    @route("POST", "/v1/identities/{provider}/{external_id}")
    def get_or_create_user_by_identity(self, provider, external_id, username, on_conflict="error") -> User:
        """
        The user linked to an external id, created (with ``username``) if there is none.

        :param on_conflict: ``"error"`` (default) refuses a taken or invalid
            username; ``"suffix"`` takes ``username_1``, ``username_2``, ... instead.
        """
        body = {"username": username, "on_conflict": on_conflict}
        return self._run(_Call("POST", f"/identities/{provider}/{external_id}", json=body, parse=User.from_dict))

    @route("POST", "/v1/identities/{provider}/{external_id}/redeem")
    def redeem_link_code(self, provider, external_id, code) -> tuple[User, int | None]:
        """
        Link an external id to the user who made ``code`` (see :meth:`link_code`).
        An id linked to someone else moves.

        :return: ``(user, previous_user_id)``: the user now linked, and who had the
            id before (``None`` if nobody did).
        :raises chesssnake.db.errors.LinkCodeError: For an unknown, used or expired code.
        """
        return self._run(
            _Call(
                "POST",
                f"/identities/{provider}/{external_id}/redeem",
                json={"code": code},
                parse=lambda data: (User.from_dict(data["user"]), data["previous_user_id"]),
            )
        )

    @route("PUT", "/v1/users/{user_id}/identities/{provider}/{external_id}")
    def link_identity(self, user_id, provider, external_id) -> User:
        return self._run(
            _Call("PUT", f"/users/{_id(user_id)}/identities/{provider}/{external_id}", parse=User.from_dict)
        )

    @route("DELETE", "/v1/users/{user_id}/identities/{provider}/{external_id}")
    def unlink_identity(self, user_id, provider, external_id) -> User:
        return self._run(
            _Call("DELETE", f"/users/{_id(user_id)}/identities/{provider}/{external_id}", parse=User.from_dict)
        )

    # --- group admins ------------------------------------------------------

    @route("GET", "/v1/groups/{group_id}/admins")
    def group_admins(self, group_id) -> list[User]:
        """Who administers a group's games (for admins and that group's admins)."""
        return self._run(
            _Call("GET", f"/groups/{group_id}/admins", parse=lambda d: [User.from_dict(u) for u in d["users"]])
        )

    @route("PUT", "/v1/groups/{group_id}/admins/{user_id}")
    def add_group_admin(self, group_id, user) -> User:
        """Administrator only: let ``user`` administer the games of ``group_id``."""
        return self._resolved(
            user, lambda uid: self._run(_Call("PUT", f"/groups/{group_id}/admins/{uid}", parse=User.from_dict))
        )

    @route("DELETE", "/v1/groups/{group_id}/admins/{user_id}")
    def remove_group_admin(self, group_id, user) -> User:
        return self._resolved(
            user, lambda uid: self._run(_Call("DELETE", f"/groups/{group_id}/admins/{uid}", parse=User.from_dict))
        )

    # --- challenges --------------------------------------------------------

    @route("POST", "/v1/challenges")
    def challenge(self, opponent, group_id=0, color="random", *, player_id=None) -> Challenge:
        """
        Challenge another user. ``opponent`` is an id or a username; ``color`` is the
        colour you want: ``"white"``, ``"black"`` or ``"random"``. Administrators
        (and the group's admins) may challenge on someone's behalf with ``player_id``.
        """

        def send(opponent_id):
            body = {"opponent_id": opponent_id, "group_id": group_id, "color": color, "player_id": player_id}
            return self._run(_Call("POST", "/challenges", json=body, parse=Challenge.from_dict))

        return self._resolved(opponent, send)

    @route("GET", "/v1/challenges")
    def challenges(self, direction="all", user_id=None) -> list[Challenge]:
        """Your pending challenges: ``"incoming"``, ``"outgoing"`` or ``"all"``."""
        params = _without_none(direction=direction, user_id=user_id)
        return self._run(
            _Call(
                "GET", "/challenges", params=params, parse=lambda d: [Challenge.from_dict(c) for c in d["challenges"]]
            )
        )

    @route("GET", "/v1/challenges/{challenge_id}")
    def get_challenge(self, challenge_id) -> Challenge:
        return self._run(_Call("GET", f"/challenges/{_id(challenge_id)}", parse=Challenge.from_dict))

    @route("POST", "/v1/challenges/{challenge_id}/accept")
    def accept_challenge(self, challenge_id, *, player_id=None) -> GameState:
        """Accept a challenge made to you; the game is created and returned."""
        body = {"player_id": player_id} if player_id is not None else None
        return self._run(_Call("POST", f"/challenges/{_id(challenge_id)}/accept", json=body, parse=GameState.from_dict))

    @route("DELETE", "/v1/challenges/{challenge_id}")
    def decline_challenge(self, challenge_id):
        """Decline a challenge made to you, or withdraw one you made."""
        return self._run(_Call("DELETE", f"/challenges/{_id(challenge_id)}", read="none"))

    withdraw_challenge = decline_challenge

    # --- games -------------------------------------------------------------

    @route("POST", "/v1/games")
    def create_game(self, white, black, group_id=0) -> GameState:
        """Administrators and the group's admins: start (or fetch) a game directly, without a challenge."""

        def send(white_id, black_id):
            body = {"group_id": group_id, "white_id": white_id, "black_id": black_id}
            return self._run(_Call("POST", "/games", json=body, parse=GameState.from_dict))

        return self._resolved_pair(white, black, send)

    @route("GET", "/v1/games/{game_id}")
    def get_game(self, game_id) -> GameState:
        """A game by its id, in progress or finished."""
        return self._run(_Call("GET", f"/games/{_id(game_id)}", parse=GameState.from_dict))

    @route("GET", "/v1/games")
    def current_games(self, player=None, group_id=None) -> list[GameState]:
        """Games in progress: yours, or ``player``'s; in every group unless ``group_id`` is given."""

        def send(player_id):
            params = _without_none(player_id=player_id, group_id=group_id)
            return self._run(_Call("GET", "/games", params=params, parse=_games))

        if player is None:
            return send(None)
        return self._resolved(player, send)

    @route("GET", "/v1/games/live")
    def live_games(self, limit=50, group_id=None) -> list[GameState]:
        """Every game in progress (in one group, with ``group_id``), most recently changed first."""
        params = _without_none(limit=limit, group_id=group_id)
        return self._run(_Call("GET", "/games/live", params=params, parse=_games))

    @route("GET", "/v1/games/finished")
    def finished_games(self, player=None, limit=50, before=None, group_id=None) -> list[GameState]:
        """
        Finished games, newest first: everyone's, or ``player``'s, in every group or
        ``group_id``'s. Pass the last game's id as ``before`` for the next page.
        """

        def send(player_id):
            params = _without_none(player_id=player_id, limit=limit, before=_id(before), group_id=group_id)
            return self._run(_Call("GET", "/games/finished", params=params, parse=_games))

        if player is None:
            return send(None)
        return self._resolved(player, send)

    @route("GET", "/v1/games/between")
    def games_between(self, player1, player2, group_id=0, status="all") -> list[GameState]:
        """Every game between two players in a group, either colour, oldest first."""

        def send(first, second):
            params = {"player1": first, "player2": second, "group_id": group_id, "status": status}
            return self._run(_Call("GET", "/games/between", params=params, parse=_games))

        return self._resolved_pair(player1, player2, send)

    @route("GET", "/v1/games/record")
    def record(self, player1, player2, group_id=0) -> dict:
        """Win/draw/loss record between two players in a group (finished games)."""

        def send(first, second):
            params = {"player1": first, "player2": second, "group_id": group_id}
            return self._run(_Call("GET", "/games/record", params=params))

        return self._resolved_pair(player1, player2, send)

    @route("DELETE", "/v1/games/{game_id}")
    def delete_game(self, game_id):
        """Administrators and the game's group's admins."""
        return self._run(_Call("DELETE", f"/games/{_id(game_id)}", read="none"))

    @route("POST", "/v1/games/{game_id}/moves")
    def move(self, game_id, move, player_id=None, expected_version=None) -> MoveResult:
        body = {"move": move, "player_id": player_id, "expected_version": expected_version}
        return self._run(_Call("POST", f"/games/{_id(game_id)}/moves", json=body, parse=MoveResult.from_dict))

    @route("POST", "/v1/games/{game_id}/resign")
    def resign(self, game_id, player_id=None, expected_version=None) -> GameState:
        return self._action(game_id, "resign", player_id, expected_version)

    @route("POST", "/v1/games/{game_id}/draw/offer")
    def offer_draw(self, game_id, player_id=None, expected_version=None) -> GameState:
        return self._action(game_id, "draw/offer", player_id, expected_version)

    @route("POST", "/v1/games/{game_id}/draw/accept")
    def accept_draw(self, game_id, player_id=None, expected_version=None) -> GameState:
        return self._action(game_id, "draw/accept", player_id, expected_version)

    @route("POST", "/v1/games/{game_id}/draw/decline")
    def decline_draw(self, game_id, player_id=None, expected_version=None) -> GameState:
        return self._action(game_id, "draw/decline", player_id, expected_version)

    def _action(self, game_id, action, player_id, expected_version):
        body = {"player_id": player_id, "expected_version": expected_version}
        return self._run(_Call("POST", f"/games/{_id(game_id)}/{action}", json=body, parse=GameState.from_dict))

    @route("GET", "/v1/games/{game_id}/legal-moves")
    def legal_moves(self, game_id) -> list[dict]:
        return self._run(_Call("GET", f"/games/{_id(game_id)}/legal-moves", parse=lambda d: d["moves"]))

    @route("GET", "/v1/games/{game_id}/history")
    def history(self, game_id) -> list[dict]:
        return self._run(_Call("GET", f"/games/{_id(game_id)}/history", parse=lambda d: d["moves"]))

    @route("GET", "/v1/games/{game_id}/pgn")
    def pgn(self, game_id) -> str:
        return self._run(_Call("GET", f"/games/{_id(game_id)}/pgn", read="text"))

    @route("GET", "/v1/games/{game_id}/fen")
    def fen(self, game_id) -> str:
        return self._run(_Call("GET", f"/games/{_id(game_id)}/fen", read="text"))

    @route("GET", "/v1/games/{game_id}/image")
    def image(self, game_id, perspective=None) -> bytes:
        """The board as PNG bytes, the last move highlighted (``perspective``: ``"white"``/``"black"``)."""
        params = _without_none(perspective=perspective)
        return self._run(_Call("GET", f"/games/{_id(game_id)}/image", params=params or None, read="bytes"))

    # --- acting as a player --------------------------------------------------

    def as_user(self, user):
        """
        This client acting as one player: a :class:`~chesssnake.remote.player.PlayerClient`
        that sends ``player_id`` with every action and defaults listings to that
        player. For administrators (and group admins, in their groups), such as a bot.

        :param user: An id, a ``User``, or a username (resolved on first use).
        """
        from .player import PlayerClient

        return PlayerClient(self, user=user)

    def as_identity(self, provider, external_id, *, create_as=None):
        """
        This client acting as the user linked to an outside id, e.g.
        ``as_identity("discord", member.id)``. Looked up on first use, then cached.

        :param create_as: A username: create the user (with ``on_conflict="suffix"``)
            if no user is linked yet. Without it, an unlinked id raises
            ``UserNotFoundError`` on first use.
        """
        from .player import PlayerClient

        return PlayerClient(self, identity=(provider, str(external_id)), create_as=create_as)


def _games(data) -> list[GameState]:
    return [GameState.from_dict(g) for g in data["games"]]


class ApiClient(_Routes):
    """
    Talks to a chesssnake api-endpoint over REST, as one user, blocking.

    :param base_url: The endpoint, e.g. ``https://chess.example``.
    :param session: A ``requests``-style session (default: a new ``requests.Session``).
    :param token: A bearer token; set later by :meth:`login`.
    """

    def __init__(self, base_url, session=None, token=None):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.token = token
        if session is None:
            try:
                import requests
            except ImportError as e:  # pragma: no cover - exercised via install extras
                raise ImportError(
                    "The 'requests' package is required for remote games. "
                    "Install it with: pip install chesssnake[client]"
                ) from e
            session = requests.Session()
        self._session = session

    # --- transport ---------------------------------------------------------

    def _headers(self, anonymous=False):
        return {"Authorization": f"Bearer {self.token}"} if self.token and not anonymous else None

    def _send(self, method, path, *, params=None, json=None, anonymous=False):
        resp = self._session.request(
            method, f"{self.base_url}{API_PREFIX}{path}", params=params, json=json, headers=self._headers(anonymous)
        )
        if resp.status_code >= 400:
            raise_for_response(resp)
        return resp

    def _request(self, method, path, *, params=None, json=None):
        resp = self._send(method, path, params=params, json=json)
        return resp.json() if resp.content else None

    _raise = staticmethod(raise_for_response)

    def _run(self, call: _Call):
        resp = self._send(call.method, call.path, params=call.params, json=call.json, anonymous=call.anonymous)
        return call.result(resp)

    def _then(self, value, fn):
        return fn(value)

    def _done(self, value):
        return value

    # --- live updates --------------------------------------------------------

    def events(self, games=()):
        """
        Live updates over the server's websocket, as an
        :class:`~chesssnake.remote.realtime.EventStream` following ``games``.
        Administrators can also :meth:`~chesssnake.remote.realtime.EventStream.follow`
        every game, and a group's admins that group's.

        :raises chesssnake.remote.realtime.RealtimeUnavailable: if the server does
            not offer them (they can be turned off); poll instead.
        """
        from .realtime import EventStream

        return EventStream(self, games=[_id(g) for g in games])
