"""
Shared fixtures for the API/remote integration tests.

Spins up a throwaway PostgreSQL via ``pgserver`` (no Docker/system Postgres
needed), points the API server at it through ``CHESSDB_CONN_STR``, and drives the
FastAPI app in-process with a ``TestClient`` (whose lifespan initializes the pool
and schema). Tables are truncated between tests.
"""

import os
import tempfile

import pytest

pgserver = pytest.importorskip("pgserver")
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def api_client():
    with tempfile.TemporaryDirectory() as pgdata:
        server = pgserver.get_server(pgdata)
        os.environ["CHESSDB_CONN_STR"] = server.get_uri()
        os.environ["CHESSSNAKE_INIT_DB"] = "1"  # let the app init the schema on startup

        from chesssnake.api.server import app
        from chesssnake.postgres import sql

        # Entering the context runs the FastAPI lifespan (pool + schema init).
        with TestClient(app) as client:
            try:
                yield client
            finally:
                if sql.connection_pool is not None:
                    sql.connection_pool.closeall()
        server.cleanup()


@pytest.fixture(autouse=True)
def clean_tables(api_client):
    from chesssnake.postgres.sql import execute_psql
    execute_psql("TRUNCATE Games, Challenges")
    yield


@pytest.fixture
def remote_client(api_client):
    """An ApiClient wired to drive the in-process app through the TestClient."""
    from chesssnake.remote.client import ApiClient
    return ApiClient("", session=api_client)
