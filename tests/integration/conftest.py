"""
Shared fixtures for the API/remote integration tests.

Spins up a throwaway PostgreSQL via ``pgserver`` (no Docker/system Postgres
needed), builds the FastAPI app from an explicit :class:`~chesssnake.config.Settings`
pointed at it, and drives it in-process with a ``TestClient`` (whose lifespan
initializes the pool and schema). Tables are truncated between tests.

The app is constructed *from* settings rather than configured *through* the
environment, so there is no ordering constraint between setting variables and
importing the server module.
"""

import tempfile

import pytest

pgserver = pytest.importorskip("pgserver")
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def database_url():
    """A throwaway PostgreSQL instance, torn down at the end of the session."""
    with tempfile.TemporaryDirectory() as pgdata:
        server = pgserver.get_server(pgdata)
        try:
            yield server.get_uri()
        finally:
            server.cleanup()


@pytest.fixture(scope="session")
def settings(database_url):
    from chesssnake.config import Settings

    return Settings(database={"url": database_url, "init_schema": True})


@pytest.fixture(scope="session")
def api_client(settings):
    from chesssnake.api.server import create_app
    from chesssnake.db import sql

    # Entering the context runs the FastAPI lifespan (pool + schema init).
    with TestClient(create_app(settings)) as client:
        try:
            yield client
        finally:
            sql.close_connection_pool()


@pytest.fixture(autouse=True)
def clean_tables(api_client):
    from chesssnake.db.sql import execute_psql

    execute_psql("TRUNCATE Games, Challenges, Moves")
    yield


@pytest.fixture
def remote_client(api_client):
    """An ApiClient wired to drive the in-process app through the TestClient."""
    from chesssnake.remote.client import ApiClient

    return ApiClient("", session=api_client)
