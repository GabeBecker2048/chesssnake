"""
Who may call what: every route, for every kind of caller.

Most integration tests run as an administrator, which would hide a route that
forgot a user-level check. This file is the counterweight: a table with one row
per route in the app, giving the expected status for

- ``anon``: no token at all,
- ``outsider``: a plain user with nothing to do with the game or challenge,
- ``player``: a plain user who is white in the game, made the challenge, and owns
  the token being revoked,
- ``admin``: the test administrator (no password, so password-checking routes 401).

Each (route, caller) pair runs against a fresh database, so a mutating request
cannot change what the next one sees. ``test_every_route_is_classified`` fails
for any route missing from the table, so a new route has to be thought about
here before the suite passes.
"""

import pytest
from fastapi.routing import APIRoute, iter_route_contexts

from tests.integration.conftest import TEST_PASSWORD

pytestmark = pytest.mark.integration

OK = "2xx"


class World:
    """The fixtures every row refers to, built through ops (no Argon2 per test)."""

    def __init__(self, api_client, users, as_user):
        from chesssnake.db import operations as ops
        from chesssnake.engine import INITIAL_FEN

        self.admin = api_client.admin_id
        self.alice, self.bob, self.carol = users("alice", "bob", "carol")
        self.game = ops.game_get_or_create(0, self.alice, self.bob, INITIAL_FEN)["id"]
        self.challenge = ops.challenge_create(self.alice, self.bob, 5)["id"]
        _, token = ops.token_create(self.alice, ops.TOKEN_API, name="alices")
        self.alice_token = token["id"]
        ops.identity_link(self.alice, "discord", "1")
        self.headers = {
            "anon": {"Authorization": ""},
            "outsider": as_user(self.carol),
            "player": as_user(self.alice),
            "admin": {},  # api_client's default header is the admin's
        }
        self.me = {"anon": None, "outsider": self.carol, "player": self.alice, "admin": self.admin}


# (method, path template, body or callable(world, role) -> body, {role: status})
# Paths use {game}, {challenge}, {alice}, {token} from the World. Anonymous is
# 401 everywhere except where a row says otherwise.
ROUTES = [
    ("GET", "/health", None, {"anon": OK, "outsider": OK, "player": OK, "admin": OK}),
    # The web UI's page: a static file, and only a client of the routes below.
    ("GET", "/", None, {"anon": OK, "outsider": OK, "player": OK, "admin": OK}),
    ("HEAD", "/", None, {"anon": OK, "outsider": OK, "player": OK, "admin": OK}),
    # What a client must know before it has an account (can it register; is there a websocket).
    ("GET", "/v1/info", None, {"anon": OK, "outsider": OK, "player": OK, "admin": OK}),
    (
        "POST",
        "/v1/auth/login",
        {"username": "alice", "password": TEST_PASSWORD},
        {"anon": OK, "outsider": OK, "player": OK, "admin": OK},
    ),
    (
        "POST",
        "/v1/auth/register",
        {"username": "newbie", "password": "long-enough-1"},
        {"anon": 403, "outsider": 403, "player": 403, "admin": 403},  # registration is closed by default
    ),
    ("POST", "/v1/auth/logout", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/auth/me", None, {"outsider": OK, "player": OK, "admin": OK}),
    (
        "POST",
        "/v1/auth/password",
        {"current_password": TEST_PASSWORD, "new_password": "another-password"},
        {"outsider": OK, "player": OK, "admin": 401},
    ),
    (
        "POST",
        "/v1/auth/tokens",
        {"name": "bot", "current_password": TEST_PASSWORD},
        {"outsider": OK, "player": OK, "admin": 401},
    ),
    ("GET", "/v1/auth/tokens", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/auth/settings", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("PATCH", "/v1/auth/settings", {"auto_queen": True}, {"outsider": OK, "player": OK, "admin": OK}),
    ("DELETE", "/v1/auth/tokens/{token}", None, {"outsider": 404, "player": OK, "admin": OK}),
    ("POST", "/v1/users", {"username": "dee"}, {"outsider": 403, "player": 403, "admin": OK}),
    ("GET", "/v1/users?username=alice", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/users/search?q=al", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/users/{alice}", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("PATCH", "/v1/users/{alice}", {"username": "alice2"}, {"outsider": 403, "player": OK, "admin": OK}),
    ("GET", "/v1/users/discord/1", None, {"outsider": 403, "player": 403, "admin": OK}),
    ("POST", "/v1/users/discord/2", {"username": "dee"}, {"outsider": 403, "player": 403, "admin": OK}),
    ("PUT", "/v1/users/{alice}/identities/discord/3", None, {"outsider": 403, "player": 403, "admin": OK}),
    # Unlinking: your own (alice is the player), or anyone's as an admin. Linking stays admin-only.
    ("DELETE", "/v1/users/{alice}/identities/discord/1", None, {"outsider": 403, "player": OK, "admin": OK}),
    (
        "POST",
        "/v1/challenges",
        lambda w, role: {"opponent_id": w.alice if role == "outsider" else w.carol},
        {"outsider": OK, "player": OK, "admin": OK},
    ),
    ("GET", "/v1/challenges", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/challenges/{challenge}", None, {"outsider": 404, "player": OK, "admin": OK}),
    # alice made the challenge, so she cannot accept it; an admin accepts as bob.
    ("POST", "/v1/challenges/{challenge}/accept", None, {"outsider": 404, "player": 403, "admin": OK}),
    ("DELETE", "/v1/challenges/{challenge}", None, {"outsider": 404, "player": OK, "admin": OK}),
    (
        "POST",
        "/v1/games",
        lambda w, role: {"group_id": 9, "white_id": w.alice, "black_id": w.bob},
        {"outsider": 403, "player": 403, "admin": OK},
    ),
    ("GET", "/v1/games", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/games/between?player1={alice}&player2={alice}", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/games/live", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/games/finished?player_id={alice}", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/games/record?player1={alice}&player2={alice}", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/games/{game}", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("DELETE", "/v1/games/{game}", None, {"outsider": 403, "player": 403, "admin": OK}),
    # carol is not in the game; alice is white and to move; an admin not playing
    # moves for the side to move but must say who resigns or offers.
    ("POST", "/v1/games/{game}/moves", {"move": "e4"}, {"outsider": 403, "player": OK, "admin": OK}),
    ("POST", "/v1/games/{game}/resign", None, {"outsider": 403, "player": OK, "admin": 422}),
    ("POST", "/v1/games/{game}/draw/offer", None, {"outsider": 403, "player": OK, "admin": 422}),
    ("POST", "/v1/games/{game}/draw/accept", None, {"outsider": 403, "player": 400, "admin": 422}),
    ("POST", "/v1/games/{game}/draw/decline", None, {"outsider": 403, "player": 400, "admin": 422}),
    ("GET", "/v1/games/{game}/legal-moves", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/games/{game}/history", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/games/{game}/pgn", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/games/{game}/fen", None, {"outsider": OK, "player": OK, "admin": OK}),
    ("GET", "/v1/games/{game}/image", None, {"outsider": OK, "player": OK, "admin": OK}),
]

ROLES = ("anon", "outsider", "player", "admin")


def _template(path):
    """The route's path as the app declares it, from a row's concrete-ish template."""
    path = path.split("?")[0]
    for placeholder, param in (
        ("{game}", "{game_id}"),
        ("{challenge}", "{challenge_id}"),
        ("{alice}", "{user_id}"),
        ("{token}", "{token_id}"),
        ("discord/1", "{provider}/{external_id}"),
        ("discord/2", "{provider}/{external_id}"),
        ("discord/3", "{provider}/{external_id}"),
    ):
        path = path.replace(placeholder, param)
    return path


def test_every_route_is_classified():
    from chesssnake.api.server import create_app
    from chesssnake.config import Settings

    app = create_app(Settings(database={"url": "sqlite:////nonexistent/never-opened.db"}))
    declared = {
        (method, context.path)
        for context in iter_route_contexts(app.routes)
        if isinstance(context.route, APIRoute)
        for method in context.methods
    }
    classified = {(method, _template(path)) for method, path, _body, _expect in ROUTES}
    assert declared - classified == set(), "routes with no row in the permission table"
    assert classified - declared == set(), "rows for routes that no longer exist"


def test_only_health_info_login_register_and_the_page_are_open():
    public = {path for _m, path, _b, expect in ROUTES if expect.get("anon", 401) != 401}
    assert public == {"/", "/health", "/v1/info", "/v1/auth/login", "/v1/auth/register"}


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("method,path,body,expect", ROUTES, ids=[f"{m} {p}" for m, p, _b, _e in ROUTES])
def test_permission(api_client, users, as_user, method, path, body, expect, role):
    world = World(api_client, users, as_user)
    url = path.format(game=world.game, challenge=world.challenge, alice=world.alice, token=world.alice_token)
    payload = body(world, role) if callable(body) else body
    wanted = expect.get(role, 401)
    # No body when probing for a 401: a malformed body is a 422 that FastAPI
    # raises before authentication, which would hide what is being tested.
    resp = api_client.request(
        method, url, json=None if role == "anon" and wanted == 401 else payload, headers=world.headers[role]
    )
    if wanted == OK:
        assert 200 <= resp.status_code < 300, f"{role}: {resp.status_code} {resp.text[:200]}"
    else:
        assert resp.status_code == wanted, f"{role}: {resp.status_code} {resp.text[:200]}"
    if resp.status_code >= 400 and resp.headers.get("content-type", "").startswith("application/json"):
        assert "error_type" in resp.json(), "every refusal uses the {error_type, detail} envelope"
