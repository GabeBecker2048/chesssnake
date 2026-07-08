"""
HTTP client for the chesssnake api-endpoint.

``ApiClient`` is a thin wrapper over a ``requests``-style session. The session can
be injected (the test-suite passes a Starlette ``TestClient``, which is request
compatible), so the same client code drives both a real server and an in-process
app. Non-2xx responses are translated back into the shared ``GameError`` types so
callers see the same exceptions they would from a local database.
"""

from ..postgres import errors

# Error-type name (sent by the server) -> exception class to raise. Types with
# custom constructors (SQLIdError, SQLAuthError) fall back to their SQLError base,
# which still preserves isinstance checks.
_ERROR_TYPES = {
    "ChallengeError": errors.ChallengeError,
    "SQLError": errors.SQLError,
    "SQLIdError": errors.SQLError,
    "SQLAuthError": errors.SQLError,
    "GameError": errors.GameError,
}


class ApiClient:
    """Talks to a chesssnake api-endpoint over REST."""

    def __init__(self, base_url, session=None):
        self.base_url = base_url.rstrip("/") if base_url else ""
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

    def _request(self, method, path, *, params=None, json=None):
        resp = self._session.request(method, f"{self.base_url}{path}", params=params, json=json)
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
        raise _ERROR_TYPES.get(error_type, errors.GameError)(detail)

    # --- games -------------------------------------------------------------

    def get_or_create_game(self, group_id, white_id, black_id, white_name="", black_name=""):
        return self._request("POST", "/games", json={
            "group_id": group_id, "white_id": white_id, "black_id": black_id,
            "white_name": white_name, "black_name": black_name,
        })

    def update_game(self, group_id, white_id, black_id, state):
        return self._request("PUT", f"/games/{group_id}/{white_id}/{black_id}", json=state)

    def update_draw(self, group_id, white_id, black_id, draw, status):
        return self._request(
            "PATCH", f"/games/{group_id}/{white_id}/{black_id}/draw",
            json={"draw": draw, "status": status},
        )

    def clear_draw(self, group_id, white_id, black_id):
        return self._request("DELETE", f"/games/{group_id}/{white_id}/{black_id}/draw")

    def delete_game(self, group_id, white_id, black_id):
        return self._request("DELETE", f"/games/{group_id}/{white_id}/{black_id}")

    def current_games(self, player_id, group_id=0):
        data = self._request("GET", "/games", params={"player_id": player_id, "group_id": group_id})
        return data["opponents"]

    def game_exists(self, player1, player2, group_id=0):
        data = self._request("GET", f"/games/{group_id}/exists", params={"player1": player1, "player2": player2})
        return data["game"]

    # --- challenges --------------------------------------------------------

    def challenge(self, challenger, challenged, group_id=0):
        data = self._request("POST", "/challenges", json={
            "group_id": group_id, "challenger": challenger, "challenged": challenged,
        })
        return data["accepted"]

    def challenge_exists(self, player1, player2, group_id=0):
        data = self._request("GET", f"/challenges/{group_id}/exists", params={"player1": player1, "player2": player2})
        return data["challenge"]

    def delete_challenge(self, challenger, challenged, group_id=0):
        return self._request("DELETE", "/challenges", json={
            "group_id": group_id, "challenger": challenger, "challenged": challenged,
        })
