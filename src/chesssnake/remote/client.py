"""
HTTP client for the chesssnake api-endpoint.

``ApiClient`` is a thin wrapper over a ``requests``-style session. The session can
be injected (the test-suite passes a Starlette ``TestClient``, which is request
compatible), so the same client code drives both a real server and an in-process
app.

The server owns the chess engine: the client sends *moves* and receives new
state (or a structured error). Non-2xx responses are translated back into the
matching engine (``ChessError``) or persistence (``GameError``) exception types so
callers see the same exceptions they would from a local game.

All routes are served under the versioned ``/v1`` prefix, and all but logging in
and registering need a token, sent as ``Authorization: Bearer <token>``. Get one
with :meth:`ApiClient.login`, or use :func:`chesssnake.connect`, which also finds
a token stored by ``chesssnake login`` or set in the environment.
"""

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


class ApiClient:
    """
    Talks to a chesssnake api-endpoint over REST, as one user.

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

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else None

    def _send(self, method, path, *, params=None, json=None):
        resp = self._session.request(
            method, f"{self.base_url}{API_PREFIX}{path}", params=params, json=json, headers=self._headers()
        )
        if resp.status_code >= 400:
            self._raise(resp)
        return resp

    def _request(self, method, path, *, params=None, json=None):
        resp = self._send(method, path, params=params, json=json)
        return resp.json() if resp.content else None

    @staticmethod
    def _raise(resp):
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
        # type, etc.), so bypass __init__ and set the message directly — this
        # preserves the exact type for `except PromotionError` while carrying the
        # server's detail message.
        exc = cls.__new__(cls)
        exc.args = (detail,)
        raise exc

    # --- account -----------------------------------------------------------

    def login(self, username, password) -> LoginResult:
        """Log in; the session token is kept on this client for every later call."""
        data = self._request("POST", "/auth/login", json={"username": username, "password": password})
        result = LoginResult.from_dict(data)
        self.token = result.token
        return result

    def register(self, username, password) -> LoginResult:
        """Create an account (only when the server allows registration) and log in as it."""
        data = self._request("POST", "/auth/register", json={"username": username, "password": password})
        result = LoginResult.from_dict(data)
        self.token = result.token
        return result

    def logout(self):
        """Revoke this client's token on the server and forget it."""
        self._request("POST", "/auth/logout")
        self.token = None

    def me(self) -> User:
        """The user this client is logged in as."""
        return User.from_dict(self._request("GET", "/auth/me"))

    def change_password(self, current_password, new_password):
        """Change your password; your other login sessions end, this one and api tokens stay."""
        self._request(
            "POST", "/auth/password", json={"current_password": current_password, "new_password": new_password}
        )

    def create_token(self, name, current_password, expires_in_days=None) -> LoginResult:
        """Create a named api token (for a script or bot). Its secret is only ever shown here."""
        body = {"name": name, "current_password": current_password, "expires_in_days": expires_in_days}
        return LoginResult.from_dict(self._request("POST", "/auth/tokens", json=body))

    def tokens(self, user_id=None) -> list[TokenInfo]:
        params = {"user_id": user_id} if user_id is not None else None
        return [TokenInfo.from_dict(t) for t in self._request("GET", "/auth/tokens", params=params)["tokens"]]

    def revoke_token(self, token_id):
        self._request("DELETE", f"/auth/tokens/{token_id}")

    def settings(self) -> dict:
        """Your per-user settings, e.g. ``{"auto_queen": False}``, defaults filled in."""
        return self._request("GET", "/auth/settings")

    def update_settings(self, **changes) -> dict:
        """Change some of your settings (``update_settings(auto_queen=True)``); returns them all."""
        return self._request("PATCH", "/auth/settings", json=changes)

    # --- live updates --------------------------------------------------------

    def events(self, games=()):
        """
        Live updates over the server's websocket, as an
        :class:`~chesssnake.remote.realtime.EventStream` following ``games``.

        :raises chesssnake.remote.realtime.RealtimeUnavailable: if the server does
            not offer them (they are off by default); poll instead.
        """
        from .realtime import EventStream

        return EventStream(self, games=[_id(g) for g in games])

    # --- users -------------------------------------------------------------

    def get_user(self, user_id) -> User:
        return User.from_dict(self._request("GET", f"/users/{_id(user_id)}"))

    def get_user_by_name(self, username) -> User:
        """Look a user up by username (case does not matter)."""
        return User.from_dict(self._request("GET", "/users", params={"username": username}))

    def user(self, who) -> User:
        """A user by id (an int) or username (a str)."""
        return self.get_user_by_name(who) if isinstance(who, str) else self.get_user(who)

    def resolve(self, who) -> int:
        """A user id from an id, a username, or a ``User``."""
        if isinstance(who, bool):
            raise TypeError(f"A player is a user id or a username, not {who!r}")
        if isinstance(who, str):
            return self.get_user_by_name(who).id
        return int(_id(who))

    def rename(self, user_id, username) -> User:
        return User.from_dict(self._request("PATCH", f"/users/{_id(user_id)}", json={"username": username}))

    # Administrator only:

    def create_user(self, username, password=None, role="user") -> User:
        body = {"username": username, "password": password, "role": role}
        return User.from_dict(self._request("POST", "/users", json=body))

    def update_user(self, user_id, *, username=None, role=None, disabled=None, password=None) -> User:
        body = {
            key: value
            for key, value in (("username", username), ("role", role), ("disabled", disabled), ("password", password))
            if value is not None
        }
        return User.from_dict(self._request("PATCH", f"/users/{_id(user_id)}", json=body))

    def get_user_by_identity(self, provider, external_id) -> User:
        """The user linked to an external id, e.g. ``("discord", "1234")``."""
        return User.from_dict(self._request("GET", f"/users/{provider}/{external_id}"))

    def get_or_create_user_by_identity(self, provider, external_id, username) -> User:
        """The user linked to an external id, created (with ``username``) if there is none."""
        data = self._request("POST", f"/users/{provider}/{external_id}", json={"username": username})
        return User.from_dict(data)

    def link_identity(self, user_id, provider, external_id) -> User:
        return User.from_dict(self._request("PUT", f"/users/{_id(user_id)}/identities/{provider}/{external_id}"))

    def unlink_identity(self, user_id, provider, external_id) -> User:
        return User.from_dict(self._request("DELETE", f"/users/{_id(user_id)}/identities/{provider}/{external_id}"))

    # --- challenges --------------------------------------------------------

    def challenge(self, opponent, group_id=0, color="random", *, player_id=None) -> Challenge:
        """
        Challenge another user. ``opponent`` is an id or a username; ``color`` is the
        colour you want: ``"white"``, ``"black"`` or ``"random"``. Administrators may
        challenge on someone's behalf with ``player_id``.
        """
        body = {"opponent_id": self.resolve(opponent), "group_id": group_id, "color": color, "player_id": player_id}
        return Challenge.from_dict(self._request("POST", "/challenges", json=body))

    def challenges(self, direction="all", user_id=None) -> list[Challenge]:
        """Your pending challenges: ``"incoming"``, ``"outgoing"`` or ``"all"``."""
        params = {"direction": direction}
        if user_id is not None:
            params["user_id"] = user_id
        return [Challenge.from_dict(c) for c in self._request("GET", "/challenges", params=params)["challenges"]]

    def get_challenge(self, challenge_id) -> Challenge:
        return Challenge.from_dict(self._request("GET", f"/challenges/{_id(challenge_id)}"))

    def accept_challenge(self, challenge_id, *, player_id=None) -> GameState:
        """Accept a challenge made to you; the game is created and returned."""
        body = {"player_id": player_id} if player_id is not None else None
        return GameState.from_dict(self._request("POST", f"/challenges/{_id(challenge_id)}/accept", json=body))

    def decline_challenge(self, challenge_id):
        """Decline a challenge made to you, or withdraw one you made."""
        self._request("DELETE", f"/challenges/{_id(challenge_id)}")

    withdraw_challenge = decline_challenge

    # --- games -------------------------------------------------------------

    def create_game(self, white, black, group_id=0) -> GameState:
        """Administrator only: start (or fetch) a game directly, without a challenge."""
        body = {"group_id": group_id, "white_id": self.resolve(white), "black_id": self.resolve(black)}
        return GameState.from_dict(self._request("POST", "/games", json=body))

    def get_game(self, game_id) -> GameState:
        """A game by its id, in progress or finished."""
        return GameState.from_dict(self._request("GET", f"/games/{_id(game_id)}"))

    def current_games(self, player=None, group_id=None) -> list[GameState]:
        """Games in progress: yours, or ``player``'s; in every group unless ``group_id`` is given."""
        params = {}
        if player is not None:
            params["player_id"] = self.resolve(player)
        if group_id is not None:
            params["group_id"] = group_id
        return [GameState.from_dict(g) for g in self._request("GET", "/games", params=params)["games"]]

    def games_between(self, player1, player2, group_id=0, status="all") -> list[GameState]:
        """Every game between two players in a group, either colour, oldest first."""
        params = {
            "player1": self.resolve(player1),
            "player2": self.resolve(player2),
            "group_id": group_id,
            "status": status,
        }
        return [GameState.from_dict(g) for g in self._request("GET", "/games/between", params=params)["games"]]

    def record(self, player1, player2, group_id=0) -> dict:
        """Win/draw/loss record between two players in a group (finished games)."""
        params = {"player1": self.resolve(player1), "player2": self.resolve(player2), "group_id": group_id}
        return self._request("GET", "/games/record", params=params)

    def delete_game(self, game_id):
        """Administrator only."""
        self._request("DELETE", f"/games/{_id(game_id)}")

    def move(self, game_id, move, player_id=None, expected_version=None) -> MoveResult:
        body = {"move": move, "player_id": player_id, "expected_version": expected_version}
        return MoveResult.from_dict(self._request("POST", f"/games/{_id(game_id)}/moves", json=body))

    def resign(self, game_id, player_id=None, expected_version=None) -> GameState:
        return self._action(game_id, "resign", player_id, expected_version)

    def offer_draw(self, game_id, player_id=None, expected_version=None) -> GameState:
        return self._action(game_id, "draw/offer", player_id, expected_version)

    def accept_draw(self, game_id, player_id=None, expected_version=None) -> GameState:
        return self._action(game_id, "draw/accept", player_id, expected_version)

    def decline_draw(self, game_id, player_id=None, expected_version=None) -> GameState:
        return self._action(game_id, "draw/decline", player_id, expected_version)

    def _action(self, game_id, action, player_id, expected_version) -> GameState:
        body = {"player_id": player_id, "expected_version": expected_version}
        return GameState.from_dict(self._request("POST", f"/games/{_id(game_id)}/{action}", json=body))

    def legal_moves(self, game_id):
        return self._request("GET", f"/games/{_id(game_id)}/legal-moves")["moves"]

    def history(self, game_id):
        return self._request("GET", f"/games/{_id(game_id)}/history")["moves"]

    def pgn(self, game_id) -> str:
        return self._send("GET", f"/games/{_id(game_id)}/pgn").text

    def fen(self, game_id) -> str:
        return self._send("GET", f"/games/{_id(game_id)}/fen").text

    def image(self, game_id, perspective=None) -> bytes:
        params = {"perspective": perspective} if perspective is not None else None
        return self._send("GET", f"/games/{_id(game_id)}/image", params=params).content
