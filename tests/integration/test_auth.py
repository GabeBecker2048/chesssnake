"""
Logging in, tokens, and the account lifecycle, on both backends.

What a route allows each kind of caller is in ``test_permissions.py``; this file
is about the credentials themselves: that a token stops working the moment it
should, that a failed login says nothing about which usernames exist, and that
the slow parts (Argon2) cannot be raced or used to exhaust the server.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import TEST_PASSWORD

pytestmark = pytest.mark.integration


def _login(api_client, username, password=TEST_PASSWORD):
    return api_client.post(
        "/v1/auth/login", json={"username": username, "password": password}, headers={"Authorization": ""}
    )


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _me(api_client, token):
    return api_client.get("/v1/auth/me", headers=_bearer(token))


# --- logging in ----------------------------------------------------------------


def test_login_returns_a_session_token(api_client, users):
    (alice,) = users("Alice")
    resp = _login(api_client, "alice")  # usernames match ignoring case
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"].startswith("css_")
    assert body["token_info"]["kind"] == "session" and body["token_info"]["expires_at"]
    assert body["user"]["id"] == alice
    me = _me(api_client, body["token"])
    assert me.status_code == 200 and me.json()["username"] == "Alice"


def test_failed_logins_are_indistinguishable(api_client, users):
    """Wrong password, unknown user, and an account with no password all look the same."""
    users("alice")
    api_client.post("/v1/users", json={"username": "bot"})  # no password
    answers = {
        (r.status_code, r.json()["error_type"], r.json()["detail"])
        for r in (
            _login(api_client, "alice", "wrong-password"),
            _login(api_client, "nobody"),
            _login(api_client, "bot", ""),
        )
    }
    assert answers == {(401, "AuthError", "Invalid username or password")}


def test_a_disabled_user_is_told_so_only_with_the_right_password(api_client, users):
    (alice,) = users("alice")
    api_client.patch(f"/v1/users/{alice}", json={"disabled": True})
    assert _login(api_client, "alice", "wrong-password").status_code == 401
    right = _login(api_client, "alice")
    assert right.status_code == 403 and right.json()["error_type"] == "ForbiddenError"


def test_a_missing_or_bad_token_is_a_401_with_the_envelope(api_client):
    for headers in (
        {"Authorization": ""},
        {"Authorization": "Bearer css_not-a-real-token"},
        {"Authorization": "Basic abc"},
    ):
        resp = api_client.get("/v1/games", headers=headers)
        assert resp.status_code == 401
        assert resp.json()["error_type"] == "AuthError"
        assert resp.headers["www-authenticate"] == "Bearer"


def test_old_api_key_headers_do_nothing(api_client):
    assert api_client.get("/v1/games", headers={"Authorization": "", "X-API-Key": "anything"}).status_code == 401


# --- tokens stop working when they should -------------------------------------


def test_logout_revokes_the_token(api_client, users):
    users("alice")
    token = _login(api_client, "alice").json()["token"]
    assert api_client.post("/v1/auth/logout", headers=_bearer(token)).status_code == 204
    assert _me(api_client, token).status_code == 401


def test_an_expired_token_is_refused(api_client, users):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from chesssnake.db import engine, schema

    users("alice")
    body = _login(api_client, "alice").json()
    with engine.transaction() as conn:
        conn.execute(
            update(schema.auth_tokens)
            .where(schema.auth_tokens.c.id == body["token_info"]["id"])
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert _me(api_client, body["token"]).status_code == 401


def test_sessions_are_capped_per_user(api_client, users, monkeypatch):
    from chesssnake.db import operations as ops

    monkeypatch.setattr(ops, "MAX_SESSIONS_PER_USER", 2)
    users("alice")
    first, second, third = (_login(api_client, "alice").json()["token"] for _ in range(3))
    assert _me(api_client, first).status_code == 401, "the oldest session goes"
    assert _me(api_client, second).status_code == 200 and _me(api_client, third).status_code == 200


def test_changing_your_password_ends_your_other_sessions_only(api_client, users):
    users("alice")
    here = _login(api_client, "alice").json()["token"]
    elsewhere = _login(api_client, "alice").json()["token"]
    bot = api_client.post(
        "/v1/auth/tokens", json={"name": "bot", "current_password": TEST_PASSWORD}, headers=_bearer(here)
    ).json()["token"]

    wrong = api_client.post(
        "/v1/auth/password",
        json={"current_password": "not-it-at-all", "new_password": "brand-new-pass"},
        headers=_bearer(here),
    )
    assert wrong.status_code == 401
    short = api_client.post(
        "/v1/auth/password", json={"current_password": TEST_PASSWORD, "new_password": "short"}, headers=_bearer(here)
    )
    assert short.status_code == 422
    changed = api_client.post(
        "/v1/auth/password",
        json={"current_password": TEST_PASSWORD, "new_password": "brand-new-pass"},
        headers=_bearer(here),
    )
    assert changed.status_code == 204

    assert _me(api_client, here).status_code == 200, "the session that changed it stays"
    assert _me(api_client, elsewhere).status_code == 401, "other sessions end"
    assert _me(api_client, bot).status_code == 200, "api tokens are separate credentials and stay"
    assert _login(api_client, "alice").status_code == 401
    assert _login(api_client, "alice", "brand-new-pass").status_code == 200


def test_an_admin_password_reset_revokes_everything(api_client, users, as_user):
    (alice,) = users("alice")
    session = _login(api_client, "alice").json()["token"]
    api_token = as_user(alice)
    assert api_client.patch(f"/v1/users/{alice}", json={"password": "reset-by-admin"}).status_code == 200
    assert _me(api_client, session).status_code == 401
    assert api_client.get("/v1/auth/me", headers=api_token).status_code == 401
    assert _login(api_client, "alice", "reset-by-admin").status_code == 200


def test_disabling_revokes_and_enabling_does_not_restore(api_client, users):
    (alice,) = users("alice")
    token = _login(api_client, "alice").json()["token"]
    api_client.patch(f"/v1/users/{alice}", json={"disabled": True})
    assert _me(api_client, token).status_code == 401
    assert api_client.patch(f"/v1/users/{alice}", json={"disabled": False}).json()["disabled_at"] is None
    assert _me(api_client, token).status_code == 401, "re-enabling does not resurrect revoked tokens"
    assert _login(api_client, "alice").status_code == 200


# --- api tokens ------------------------------------------------------------------


def test_api_tokens(api_client, users):
    from sqlalchemy import select

    from chesssnake.db import engine, schema

    users("alice")
    session = _login(api_client, "alice").json()["token"]
    refused = api_client.post(
        "/v1/auth/tokens", json={"name": "bot", "current_password": "nope-not-it"}, headers=_bearer(session)
    )
    assert refused.status_code == 401, "a stolen session cannot mint itself a lasting token"
    for bad in (
        {"name": ""},
        {"name": "x" * 65},
        {"name": "ok", "expires_in_days": 0},
        {"name": "ok", "expires_in_days": 4000},
    ):
        body = {"current_password": TEST_PASSWORD, **bad}
        assert api_client.post("/v1/auth/tokens", json=body, headers=_bearer(session)).status_code == 422

    created = api_client.post(
        "/v1/auth/tokens",
        json={"name": "bot", "current_password": TEST_PASSWORD, "expires_in_days": 90},
        headers=_bearer(session),
    )
    assert created.status_code == 201
    secret, info = created.json()["token"], created.json()["token_info"]
    assert info["kind"] == "api" and info["name"] == "bot" and info["expires_at"]
    assert _me(api_client, secret).status_code == 200

    listed = api_client.get("/v1/auth/tokens", headers=_bearer(session)).json()["tokens"]
    assert {t["kind"] for t in listed} == {"session", "api"}
    assert secret not in str(listed), "the secret is shown once, never listed"
    with engine.transaction() as conn:
        stored = set(conn.execute(select(schema.auth_tokens.c.token_hash)).scalars())
    assert secret not in stored, "only the hash is stored"

    assert api_client.delete(f"/v1/auth/tokens/{info['id']}", headers=_bearer(session)).status_code == 204
    assert _me(api_client, secret).status_code == 401


# --- registration --------------------------------------------------------------


@pytest.fixture
def open_client(api_client, settings):
    """A second app with open registration, sharing the already-initialized pool."""
    from chesssnake.api.server import create_app
    from chesssnake.config import Settings

    with TestClient(create_app(Settings(api={"registration": "open"}, database={"url": settings.database.url}))) as c:
        yield c


def test_registration_when_open(open_client, users):
    resp = open_client.post("/v1/auth/register", json={"username": "newbie", "password": "long-enough-1"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["role"] == "user" and body["user"]["has_password"] is True
    assert open_client.get("/v1/auth/me", headers=_bearer(body["token"])).json()["username"] == "newbie"
    users("taken")
    assert (
        open_client.post("/v1/auth/register", json={"username": "TAKEN", "password": "long-enough-1"}).status_code
        == 409
    )
    assert open_client.post("/v1/auth/register", json={"username": "short", "password": "short"}).status_code == 422


def test_registration_is_closed_by_default(api_client):
    resp = api_client.post("/v1/auth/register", json={"username": "newbie", "password": "long-enough-1"})
    assert resp.status_code == 403 and "closed" in resp.json()["detail"]


# --- acting for someone else ---------------------------------------------------


@pytest.fixture
def game(api_client, pair):
    white, black = pair
    return api_client.post("/v1/games", json={"white_id": white, "black_id": black}).json()["id"]


def test_a_player_cannot_act_for_their_opponent(api_client, game, pair, as_user):
    white, black = pair
    resp = api_client.post(f"/v1/games/{game}/moves", json={"move": "e4", "player_id": white}, headers=as_user(black))
    assert resp.status_code == 403 and resp.json()["error_type"] == "ForbiddenError"
    # ...nor move out of turn by leaving player_id out: they always act as themselves.
    resp = api_client.post(f"/v1/games/{game}/moves", json={"move": "e4"}, headers=as_user(black))
    assert resp.status_code == 403 and resp.json()["error_type"] == "NotYourTurnError"
    assert api_client.post(f"/v1/games/{game}/moves", json={"move": "e4"}, headers=as_user(white)).status_code == 200


def test_an_admin_acts_for_a_player_and_not_for_a_disabled_one(api_client, game, pair):
    white, black = pair
    assert api_client.post(f"/v1/games/{game}/moves", json={"move": "e4", "player_id": white}).status_code == 200
    api_client.patch(f"/v1/users/{black}", json={"disabled": True})
    resp = api_client.post(f"/v1/games/{game}/moves", json={"move": "e5", "player_id": black})
    assert resp.status_code == 403 and "disabled" in resp.json()["detail"]


def test_an_admin_playing_their_own_game_acts_as_themselves(api_client, admin_id, users):
    (opponent,) = users("opponent")
    game = api_client.post("/v1/games", json={"white_id": admin_id, "black_id": opponent}).json()["id"]
    assert api_client.post(f"/v1/games/{game}/moves", json={"move": "e4"}).status_code == 200
    # Black to move: an admin who is white must not move black's pieces by default.
    resp = api_client.post(f"/v1/games/{game}/moves", json={"move": "e5"})
    assert resp.status_code == 403 and resp.json()["error_type"] == "NotYourTurnError"


def test_identities_are_private_to_the_user_and_admins(api_client, users, as_user):
    alice, bob = users("alice", "bob")
    api_client.put(f"/v1/users/{alice}/identities/discord/42")
    assert api_client.get(f"/v1/users/{alice}", headers=as_user(bob)).json()["identities"] == []
    assert api_client.get(f"/v1/users/{alice}", headers=as_user(alice)).json()["identities"] != []
    assert api_client.get(f"/v1/users/{alice}").json()["identities"] != []


# --- the slow parts --------------------------------------------------------------


def test_a_login_cannot_outlive_a_reset_it_raced(users, test_password_hash):
    """Verified against the old password, minted after a reset: the mint is refused."""
    from chesssnake.api.auth import hash_password
    from chesssnake.db import errors
    from chesssnake.db import operations as ops

    (alice,) = users("alice")
    verified_against = ops.user_credentials(username="alice")["password_hash"]
    ops.user_set_password(alice, hash_password("reset-meanwhile"), revoke="all")
    with pytest.raises(errors.AuthError, match="changed"):
        ops.token_create(alice, ops.TOKEN_SESSION, lifetime_days=1, expected_hash=verified_against)


def test_old_hashes_are_upgraded_at_login(api_client):
    from argon2 import PasswordHasher

    from chesssnake.api import auth
    from chesssnake.db import operations as ops

    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(TEST_PASSWORD)
    ops.user_create("oldtimer", ops.ROLE_USER, weak)
    assert auth.needs_rehash(weak)
    assert _login(api_client, "oldtimer").status_code == 200
    upgraded = ops.user_credentials(username="oldtimer")["password_hash"]
    assert upgraded != weak and not auth.needs_rehash(upgraded)


def test_password_hashing_is_capped_and_answers_503(api_client, users, monkeypatch):
    from chesssnake.api import auth

    users("alice")
    slots = threading.BoundedSemaphore(1)
    slots.acquire()  # every slot is busy
    monkeypatch.setattr(auth, "_hash_slots", slots)
    monkeypatch.setattr(auth, "HASH_SLOT_TIMEOUT_SECONDS", 0.05)
    resp = _login(api_client, "alice")
    assert resp.status_code == 503 and resp.json()["error_type"] == "SQLBusyError"


def test_a_saturated_pool_while_authenticating_is_503_not_401(api_client, monkeypatch):
    """A good token must not be told to log in again just because the server is busy."""
    from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

    from chesssnake.db import engine as db_engine

    def exhausted():
        raise SQLAlchemyTimeoutError("QueuePool limit reached")

    monkeypatch.setattr(db_engine, "get_engine", exhausted)
    resp = api_client.get("/v1/auth/me")
    assert resp.status_code == 503 and resp.json()["error_type"] == "SQLBusyError"
