"""
A real chesssnake server for your tests: :class:`TestServer`.

For anyone writing a bot or client: run your code against the actual api-endpoint,
in-process, on a temporary SQLite database, with no network and no setup.

.. code-block:: python

    from chesssnake.testing import TestServer

    with TestServer() as server:
        admin = server.client()                      # an ApiClient, as an administrator
        alice, bob = server.user("alice"), server.user("bob")
        game = admin.create_game(alice, bob)
        admin.as_user(alice).move(game, "e4")

Or, with pytest, add ``pytest_plugins = ["chesssnake.testing.pytest_plugin"]`` to
your ``conftest.py`` and use the ``chesssnake_server`` fixture (one server per test
session, emptied before each test) and ``chesssnake_admin`` (an admin client).

``TestServer(live=True)`` also serves it over real HTTP with uvicorn on a free
port (``server.url``), for websocket live updates, which the in-process transport
cannot carry.

Needs the ``api`` extra (``pip install chesssnake[api,client]``). The server's
database handle is per process, so run one ``TestServer`` at a time.
"""

from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

try:
    from fastapi.testclient import TestClient
except ImportError as e:  # pragma: no cover - exercised via install extras
    raise ImportError("chesssnake.testing needs the server: pip install 'chesssnake[api,client]'") from e

from ..dto import User

__all__ = ["TestServer"]

#: The password :meth:`TestServer.user` gives accounts when asked for one.
DEFAULT_PASSWORD = "test-password-1"


class TestServer:
    """
    A chesssnake api-endpoint on a throwaway SQLite database, with an administrator.

    :param live: Also serve over HTTP (uvicorn on 127.0.0.1, a free port) so that
        websockets work; ``url`` is then its address.
    :param settings: Extra settings, as ``Settings`` takes them, e.g.
        ``{"api": {"registration": "open"}}``. Websockets are on.
    """

    __test__ = False  # not a pytest test class, despite the name

    def __init__(self, *, live: bool = False, settings: dict | None = None):
        self.live = live
        self._extra: dict[str, dict[str, Any]] = settings or {}
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._http: TestClient | None = None
        self._uvicorn: Any = None
        self._thread: threading.Thread | None = None
        self.app: Any = None
        self.url: str | None = None
        self.admin: User | None = None
        self._admin_token: str | None = None

    # --- starting and stopping ------------------------------------------------------

    def start(self) -> TestServer:
        from ..api.server import create_app
        from ..config import Settings
        from ..db import engine

        self._tmp = tmp = tempfile.TemporaryDirectory(prefix="chesssnake-test-")
        sections: dict[str, Any] = {
            "database": {"url": f"sqlite:///{Path(tmp.name) / 'chesssnake.db'}", "init_schema": True},
            "websocket": {"enabled": True},
        }
        for name, values in self._extra.items():
            sections[name] = {**sections.get(name, {}), **values}
        engine.dispose_engine()
        self.app = create_app(Settings(**sections))
        # Entering the TestClient runs the app's lifespan: the engine and the schema.
        self._http = http = TestClient(self.app)
        http.__enter__()
        if self.live:
            self._serve()
        self.reset()
        return self

    def stop(self) -> None:
        from ..db import engine

        if self._uvicorn is not None and self._thread is not None:
            self._uvicorn.should_exit = True
            self._thread.join(timeout=10)
            self._uvicorn = self._thread = None
        if self._http is not None:
            self._http.__exit__(None, None, None)
            self._http = None
        engine.dispose_engine()
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *_exc):
        self.stop()

    def _serve(self):
        import uvicorn

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        config = uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
        self._uvicorn = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._uvicorn.run, name="chesssnake-test-server", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._uvicorn.started:
            if time.monotonic() > deadline or not self._thread.is_alive():
                raise RuntimeError("the test server did not start")
            time.sleep(0.02)
        self.url = f"http://127.0.0.1:{port}"

    # --- data ---------------------------------------------------------------------

    def reset(self) -> None:
        """Empty every table and make a fresh administrator (``self.admin``)."""
        from sqlalchemy import delete

        from ..db import engine, schema
        from ..db import operations as ops

        with engine.transaction() as conn:
            for table in reversed(schema.TABLES):  # children before parents
                conn.execute(delete(table))
        admin = ops.user_create("admin", ops.ROLE_ADMIN)
        self._admin_token, _ = ops.token_create(admin["id"], ops.TOKEN_API, name="tests")
        self.admin = User.from_row(ops.user_get(admin["id"]))

    def user(self, username: str, *, password: str | None = None, admin: bool = False) -> User:
        """
        Create an account straight in the database (no Argon2 cost unless a
        ``password`` is given) and return it.
        """
        from ..api.auth import hash_password
        from ..db import operations as ops

        password_hash = hash_password(password) if password is not None else None
        row = ops.user_create(username, ops.ROLE_ADMIN if admin else ops.ROLE_USER, password_hash)
        return User.from_row(row)

    def token(self, user=None) -> str:
        """An api token for ``user`` (an id or ``User``), or the administrator's."""
        from ..db import operations as ops

        if user is None:
            assert self._admin_token is not None, "start the server first"
            return self._admin_token
        raw, _ = ops.token_create(int(getattr(user, "id", user)), ops.TOKEN_API, name="tests")
        return raw

    # --- clients --------------------------------------------------------------------

    def client(self, user=None, *, asynchronous: bool = False):
        """
        A client logged in as ``user`` (an id or ``User``), or as the administrator.

        In-process unless the server is ``live``. ``asynchronous=True`` gives an
        :class:`~chesssnake.remote.async_client.AsyncApiClient` (close it with
        ``await client.aclose()`` when the server is live).
        """
        token = self.token(user)
        if asynchronous:
            from ..remote.async_client import AsyncApiClient

            if self.url is not None:
                return AsyncApiClient(self.url, token=token)
            import httpx

            transport = httpx.ASGITransport(app=self.app)
            return AsyncApiClient("http://testserver", token=token, http=httpx.AsyncClient(transport=transport))
        from ..remote.client import ApiClient

        if self.url is not None:
            return ApiClient(self.url, token=token)
        return ApiClient("", session=self._http, token=token)
