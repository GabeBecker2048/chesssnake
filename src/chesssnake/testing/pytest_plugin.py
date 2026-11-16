"""
pytest fixtures for testing against a real chesssnake server.

Enable with ``pytest_plugins = ["chesssnake.testing.pytest_plugin"]`` in your
``conftest.py``:

- ``chesssnake_server``: one in-process :class:`~chesssnake.testing.TestServer`
  for the session, emptied (and given a fresh administrator) before each test
  that uses it.
- ``chesssnake_admin``: an :class:`~chesssnake.ApiClient` as that administrator.
- ``chesssnake_async_admin``: the same as an :class:`~chesssnake.AsyncApiClient`.

For websockets, start your own ``TestServer(live=True)`` instead.
"""

from __future__ import annotations

import pytest

from . import TestServer


@pytest.fixture(scope="session")
def _chesssnake_session_server():
    with TestServer() as server:
        yield server


@pytest.fixture
def chesssnake_server(_chesssnake_session_server):
    _chesssnake_session_server.reset()
    return _chesssnake_session_server


@pytest.fixture
def chesssnake_admin(chesssnake_server):
    return chesssnake_server.client()


@pytest.fixture
def chesssnake_async_admin(chesssnake_server):
    return chesssnake_server.client(asynchronous=True)
