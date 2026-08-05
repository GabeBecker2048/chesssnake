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

    return Settings(database={"url": database_url, "init_schema": True})


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


@pytest.fixture(autouse=True)
def clean_tables(request):
    """
    Empty every table between tests, on whichever backend is active.

    Only for tests that actually use the app. Depending on ``api_client``
    unconditionally would drag a PostgreSQL cluster up for every test in this
    directory — including ones that only parse URLs or build their own engine —
    and would parametrize them over both backends for no reason.
    """
    if "api_client" not in request.fixturenames:
        yield
        return

    from sqlalchemy import delete

    from chesssnake.db import engine, schema

    request.getfixturevalue("api_client")
    with engine.transaction() as conn:
        for table in schema.TABLES:
            conn.execute(delete(table))
    yield


@pytest.fixture
def remote_client(api_client):
    """An ApiClient wired to drive the in-process app through the TestClient."""
    from chesssnake.remote.client import ApiClient

    return ApiClient("", session=api_client)
