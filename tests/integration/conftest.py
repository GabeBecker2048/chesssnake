"""
Shared fixtures for the API/remote integration tests.

Every test in this directory runs against **both** backends: a temporary SQLite
file and a throwaway PostgreSQL spun up via ``pgserver`` (no Docker or system
Postgres needed). That is the point of the 0.9.0 database work — the two backends
have to be behaviorally identical, and the way to know is to run the same suite
against each.

PostgreSQL is skipped when ``pgserver`` is unavailable, which is the normal case
outside CI's pinned interpreter: it publishes only cp311/cp312 wheels. SQLite has
no such constraint, so the suite still runs everywhere.

The app is built from an explicit ``Settings`` rather than configured through the
environment, so there is no ordering constraint between setting variables and
importing the server module.
"""

import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
from fastapi.testclient import TestClient

#: Which backends to exercise. CI narrows this to "sqlite" for the Python-matrix
#: job, where pgserver has no wheels; locally and in the PostgreSQL job it is both.
BACKENDS = tuple(os.environ.get("CHESSSNAKE_TEST_BACKENDS", "sqlite,postgresql").split(","))


def _postgres_url(stack):
    """A throwaway PostgreSQL cluster, or skip if pgserver isn't installed."""
    pgserver = pytest.importorskip("pgserver", reason="pgserver is unavailable (it ships only cp311/cp312 wheels)")
    pgdata = stack.enter_context(tempfile.TemporaryDirectory())
    server = pgserver.get_server(pgdata)
    stack.callback(server.cleanup)
    return server.get_uri()


@pytest.fixture(scope="session", params=BACKENDS)
def backend(request):
    """The backend under test. Every downstream fixture is per-backend."""
    return request.param


@pytest.fixture(scope="session")
def database_url(backend):
    from contextlib import ExitStack

    with ExitStack() as stack:
        if backend == "sqlite":
            tmp = stack.enter_context(tempfile.TemporaryDirectory())
            yield f"sqlite:///{Path(tmp) / 'chesssnake.db'}"
        else:
            yield _postgres_url(stack)


@pytest.fixture(scope="session")
def settings(database_url):
    from chesssnake.config import Settings

    # Websockets on, so every REST test also runs the publish path (a route that
    # broke while publishing would fail here, not only in test_websocket.py), and
    # the websocket tests drive REST and sockets through one app and one broker.
    return Settings(database={"url": database_url, "init_schema": True}, websocket={"enabled": True})


@pytest.fixture(scope="session")
def api_client(settings):
    from chesssnake.api.server import create_app
    from chesssnake.db import engine

    # A previous backend's engine must be gone before this one builds its own;
    # the engine handle is process-wide.
    engine.dispose_engine()
    # Entering the context runs the FastAPI lifespan (engine + schema creation).
    with TestClient(create_app(settings)) as client:
        try:
            yield client
        finally:
            engine.dispose_engine()


#: The password every test user has. Hashed once per session (Argon2 is slow on
#: purpose) and stored directly, so creating a user in a test costs nothing.
TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session")
def test_password_hash():
    from chesssnake.api.auth import hash_password

    return hash_password(TEST_PASSWORD)


@pytest.fixture(autouse=True)
def clean_tables(request):
    """
    Empty every table between tests, on whichever backend is active, and sign
    ``api_client`` in as a fresh administrator.

    Every ``/v1`` route needs a token, so each test starts with an admin account
    (``api_client.admin_id``) and an api token for it set as the client's default
    ``Authorization`` header. Both are minted through the operations layer, not
    the API, so no test pays for a password hash it does not exercise. Tests about
    what a *plain* user may do use :func:`as_user` / :func:`user_client`, which is
    what keeps admin-by-default from hiding a missing permission check (the
    permission table in ``test_permissions.py`` checks every route that way).

    Only for tests that actually use the app. Depending on ``api_client``
    unconditionally would drag a PostgreSQL cluster up for every test in this
    directory, including ones that only parse URLs or build their own engine.
    """
    if "api_client" not in request.fixturenames:
        yield
        return

    from sqlalchemy import delete

    from chesssnake.db import engine, schema
    from chesssnake.db import operations as ops

    client = request.getfixturevalue("api_client")
    with engine.transaction() as conn:
        # Children before parents, or the foreign keys refuse the delete.
        for table in reversed(schema.TABLES):
            conn.execute(delete(table))
    admin = ops.user_create("admin", ops.ROLE_ADMIN)
    raw, _ = ops.token_create(admin["id"], ops.TOKEN_API, name="tests")
    client.headers["Authorization"] = f"Bearer {raw}"
    client.admin_id = admin["id"]
    yield


@pytest.fixture
def admin_id(api_client):
    """The id of the administrator ``api_client`` is signed in as."""
    return api_client.admin_id


@pytest.fixture
def remote_client(api_client):
    """An ApiClient wired to the in-process app, acting as the test administrator."""
    from chesssnake.remote.client import ApiClient

    return ApiClient("", session=api_client)


@pytest.fixture
def users(api_client, test_password_hash):
    """
    Create plain users (password :data:`TEST_PASSWORD`) and return their ids, in order.

    Ids are assigned by the server and never reused, so tests take them from
    here rather than writing them down: ``white, black = users("alice", "bob")``.
    """
    from chesssnake.db import operations as ops

    def create(*names, role=0):
        return [ops.user_create(name, role, test_password_hash)["id"] for name in names]

    return create


@pytest.fixture
def pair(users):
    """Two fresh users, ``(white_id, black_id)``."""
    return tuple(users("white", "black"))


@pytest.fixture
def as_user(api_client):
    """``as_user(user_id)`` -> request headers authenticating as that user."""
    from chesssnake.db import operations as ops

    def headers(user_id):
        raw, _ = ops.token_create(user_id, ops.TOKEN_API, name="tests")
        return {"Authorization": f"Bearer {raw}"}

    return headers


@pytest.fixture
def user_client(api_client, as_user):
    """``user_client(user_id)`` -> an ApiClient acting as that (plain) user."""
    from chesssnake.remote.client import ApiClient

    def make(user_id):
        token = as_user(user_id)["Authorization"].split()[1]
        return ApiClient("", session=api_client, token=token)

    return make
