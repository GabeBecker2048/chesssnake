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

All routes are served under the versioned ``/v1`` prefix. If the server is
configured with an API key, pass ``api_key=`` and it is sent as ``X-API-Key``.
"""

from ..db import errors as db_errors
from ..dto import GameState, MoveResult
from ..engine import errors as chess_errors

# All endpoints live under this version prefix.
API_PREFIX = "/v1"

# Header carrying the optional API key.
API_KEY_HEADER = "X-API-Key"


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


def _gen(generation):
    """Query params for an optional ``generation`` selector (empty when current)."""
    return {"generation": generation} if generation is not None else {}


class ApiClient:
    """Talks to a chesssnake api-endpoint over REST."""

    def __init__(self, base_url, session=None, api_key=None):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
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
        return {API_KEY_HEADER: self.api_key} if self.api_key else None

    def _request(self, method, path, *, params=None, json=None):
        resp = self._session.request(
            method, f"{self.base_url}{API_PREFIX}{path}", params=params, json=json, headers=self._headers()
        )
        if resp.status_code >= 400:
            self._raise(resp)
        if resp.content:
            return resp.json()
        return None

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

    # --- games -------------------------------------------------------------

    def get_or_create_game(self, group_id, white_id, black_id, white_name="", black_name="") -> GameState:
        data = self._request(
            "POST",
            "/games",
            json={
                "group_id": group_id,
                "white_id": white_id,
                "black_id": black_id,
                "white_name": white_name,
                "black_name": black_name,
            },
        )
        return GameState(**data)

    def get_state(self, group_id, white_id, black_id, generation=None) -> GameState:
        data = self._request("GET", f"/games/{group_id}/{white_id}/{black_id}", params=_gen(generation))
        return GameState(**data)

    def archive(self, group_id, white_id, black_id):
        """List all games (generations) for a triple, oldest first."""
        return self._request("GET", f"/games/{group_id}/{white_id}/{black_id}/archive")["games"]

    def move(self, group_id, white_id, black_id, move, player_id=None, expected_version=None) -> MoveResult:
        data = self._request(
            "POST",
            f"/games/{group_id}/{white_id}/{black_id}/moves",
            json={"move": move, "player_id": player_id, "expected_version": expected_version},
        )
        return MoveResult.from_dict(data)

    def resign(self, group_id, white_id, black_id, player_id, expected_version=None) -> GameState:
        data = self._request(
            "POST",
            f"/games/{group_id}/{white_id}/{black_id}/resign",
            json={"player_id": player_id, "expected_version": expected_version},
        )
        return GameState(**data)

    def offer_draw(self, group_id, white_id, black_id, player_id, expected_version=None) -> GameState:
        return self._draw(group_id, white_id, black_id, player_id, "offer", expected_version)

    def accept_draw(self, group_id, white_id, black_id, player_id, expected_version=None) -> GameState:
        return self._draw(group_id, white_id, black_id, player_id, "accept", expected_version)

    def decline_draw(self, group_id, white_id, black_id, player_id, expected_version=None) -> GameState:
        return self._draw(group_id, white_id, black_id, player_id, "decline", expected_version)

    def _draw(self, group_id, white_id, black_id, player_id, action, expected_version) -> GameState:
        data = self._request(
            "POST",
            f"/games/{group_id}/{white_id}/{black_id}/draw/{action}",
            json={"player_id": player_id, "expected_version": expected_version},
        )
        return GameState(**data)

    def legal_moves(self, group_id, white_id, black_id, generation=None):
        return self._request("GET", f"/games/{group_id}/{white_id}/{black_id}/legal-moves", params=_gen(generation))[
            "moves"
        ]

    def history(self, group_id, white_id, black_id, generation=None):
        return self._request("GET", f"/games/{group_id}/{white_id}/{black_id}/history", params=_gen(generation))[
            "moves"
        ]

    def pgn(self, group_id, white_id, black_id, generation=None) -> str:
        return self._raw("GET", f"/games/{group_id}/{white_id}/{black_id}/pgn", params=_gen(generation)).text

    def fen(self, group_id, white_id, black_id, generation=None) -> str:
        return self._raw("GET", f"/games/{group_id}/{white_id}/{black_id}/fen", params=_gen(generation)).text

    def image(self, group_id, white_id, black_id, perspective=None, generation=None) -> bytes:
        params = _gen(generation)
        if perspective is not None:
            params["perspective"] = perspective
        return self._raw("GET", f"/games/{group_id}/{white_id}/{black_id}/image", params=params).content

    def _raw(self, method, path, params=None):
        """A request that returns the raw response (for non-JSON bodies: image/pgn/fen)."""
        resp = self._session.request(
            method, f"{self.base_url}{API_PREFIX}{path}", params=params, headers=self._headers()
        )
        if resp.status_code >= 400:
            self._raise(resp)
        return resp

    def delete_game(self, group_id, white_id, black_id, generation=None):
        return self._request("DELETE", f"/games/{group_id}/{white_id}/{black_id}", params=_gen(generation))

    def current_games(self, player_id, group_id=0):
        data = self._request("GET", "/games", params={"player_id": player_id, "group_id": group_id})
        return data["opponents"]

    def game_exists(self, player1, player2, group_id=0):
        data = self._request("GET", f"/games/{group_id}/exists", params={"player1": player1, "player2": player2})
        return data["game"]

    def record(self, player1, player2, group_id=0):
        """Win/draw/loss record between two players in a group (finished games)."""
        return self._request("GET", f"/games/{group_id}/record", params={"player1": player1, "player2": player2})

    # --- challenges --------------------------------------------------------

    def challenge(self, challenger, challenged, group_id=0):
        data = self._request(
            "POST",
            "/challenges",
            json={
                "group_id": group_id,
                "challenger": challenger,
                "challenged": challenged,
            },
        )
        return data["accepted"]

    def challenge_exists(self, player1, player2, group_id=0):
        data = self._request("GET", f"/challenges/{group_id}/exists", params={"player1": player1, "player2": player2})
        return data["challenge"]

    def delete_challenge(self, challenger, challenged, group_id=0):
        return self._request(
            "DELETE",
            "/challenges",
            json={
                "group_id": group_id,
                "challenger": challenger,
                "challenged": challenged,
            },
        )
