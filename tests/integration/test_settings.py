"""
Per-user settings (0.14.0): ``GET`` / ``PATCH /v1/auth/settings``, both backends.

The server only stores them, one JSON document per user; clients act on them
(the web UI's auto-queen). Names and types are checked against
``operations.USER_SETTING_DEFAULTS``.
"""

import threading

import pytest

pytestmark = pytest.mark.integration


def test_every_setting_has_its_default_until_changed(api_client, users, as_user):
    (alice,) = users("alice")
    resp = api_client.get("/v1/auth/settings", headers=as_user(alice))
    assert resp.status_code == 200
    assert resp.json() == {"auto_queen": False}


def test_a_change_is_kept_and_belongs_to_that_user_only(api_client, users, as_user):
    alice, bob = users("alice", "bob")
    resp = api_client.patch("/v1/auth/settings", json={"auto_queen": True}, headers=as_user(alice))
    assert resp.status_code == 200 and resp.json() == {"auto_queen": True}
    # A new login (another browser) sees it; another user does not.
    assert api_client.get("/v1/auth/settings", headers=as_user(alice)).json() == {"auto_queen": True}
    assert api_client.get("/v1/auth/settings", headers=as_user(bob)).json() == {"auto_queen": False}
    api_client.patch("/v1/auth/settings", json={"auto_queen": False}, headers=as_user(alice))
    assert api_client.get("/v1/auth/settings", headers=as_user(alice)).json() == {"auto_queen": False}


def test_an_empty_change_changes_nothing(api_client, users, as_user):
    (alice,) = users("alice")
    api_client.patch("/v1/auth/settings", json={"auto_queen": True}, headers=as_user(alice))
    assert api_client.patch("/v1/auth/settings", json={}, headers=as_user(alice)).json() == {"auto_queen": True}


@pytest.mark.parametrize(
    "body",
    [
        {"auto_queen": "yes"},
        {"auto_queen": 1},  # 1 is not a bool here
        {"auto_queen": None},
        {"no_such_setting": True},
        ["auto_queen"],
    ],
)
def test_unknown_settings_and_wrong_types_are_422(api_client, users, as_user, body):
    (alice,) = users("alice")
    resp = api_client.patch("/v1/auth/settings", json=body, headers=as_user(alice))
    assert resp.status_code == 422, resp.text
    assert api_client.get("/v1/auth/settings", headers=as_user(alice)).json() == {"auto_queen": False}


def test_the_python_client_reads_and_writes_them(users, user_client):
    (alice,) = users("alice")
    client = user_client(alice)
    assert client.settings() == {"auto_queen": False}
    assert client.update_settings(auto_queen=True) == {"auto_queen": True}
    assert client.settings() == {"auto_queen": True}


def test_concurrent_first_writes_do_not_collide(api_client, users, as_user):
    """The first change creates the row; two at once must both succeed (no duplicate-key error)."""
    (alice,) = users("alice")
    headers = as_user(alice)
    statuses = []

    def write():
        statuses.append(api_client.patch("/v1/auth/settings", json={"auto_queen": True}, headers=headers).status_code)

    threads = [threading.Thread(target=write) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses == [200] * 6
    assert api_client.get("/v1/auth/settings", headers=headers).json() == {"auto_queen": True}


def test_a_stored_setting_that_no_longer_exists_is_ignored(api_client, users, as_user):
    """Removing a setting from the code must not break users who had set it."""
    from sqlalchemy import update

    from chesssnake.db import engine, schema

    (alice,) = users("alice")
    api_client.patch("/v1/auth/settings", json={"auto_queen": True}, headers=as_user(alice))
    with engine.transaction() as conn:
        conn.execute(
            update(schema.user_settings)
            .where(schema.user_settings.c.user_id == alice)
            .values(settings='{"auto_queen": true, "retired": 5}')
        )
    assert api_client.get("/v1/auth/settings", headers=as_user(alice)).json() == {"auto_queen": True}
    assert api_client.patch("/v1/auth/settings", json={}, headers=as_user(alice)).json() == {"auto_queen": True}


def test_upgrading_a_013_database(api_client, monkeypatch, tmp_path):
    """
    A 0.13 database has every table but user_settings. With init_schema it is
    created and the data kept; without, the server refuses to start and says how
    to fix it, rather than answering 500 on the settings routes.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, inspect

    from chesssnake.api.server import create_app
    from chesssnake.config import Settings
    from chesssnake.db import engine as db_engine
    from chesssnake.db import errors, schema

    url = f"sqlite:///{tmp_path / 'old.db'}"
    old = create_engine(url)
    schema.metadata.create_all(old, tables=[t for t in schema.TABLES if t.name != "user_settings"])
    old.dispose()

    # As in test_threadpool's in-memory test: let the app under test own its engine.
    monkeypatch.setattr(db_engine, "_engine", None)
    with pytest.raises(errors.SQLError, match="chesssnake init-db"):
        with TestClient(create_app(Settings(database={"url": url}))):
            pass  # pragma: no cover - the lifespan raises first

    monkeypatch.setattr(db_engine, "_engine", None)
    with TestClient(create_app(Settings(database={"url": url, "init_schema": True}))) as client:
        assert client.get("/health").status_code == 200
    check = create_engine(url)
    assert "user_settings" in inspect(check).get_table_names()
    check.dispose()
