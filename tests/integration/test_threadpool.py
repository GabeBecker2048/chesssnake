"""
The api-endpoint serves requests in parallel, not one at a time.

Every route body here is blocking: synchronous SQLAlchemy, chess engine work,
PIL rendering. FastAPI only dispatches a route to its worker threadpool when the
route is a plain ``def``; an ``async def`` route runs directly on the event loop
and blocks every other request for its whole duration. All the routes used to be
``async def`` with no ``await`` anywhere, so the server handled one request at a
time. These tests are what keeps that from coming back.

Both tests deliberately use the session-scoped ``api_client``, and that is load
bearing rather than convenience: ``conftest`` enters ``TestClient`` as a context
manager, so every request goes through one portal and one event loop thread. An
``async def`` route therefore runs to completion without yielding and concurrent
requests serialize. A ``TestClient`` built *without* ``with`` gets a fresh portal
per request, which would satisfy the barrier below even with the bug present and
make the test prove nothing.
"""

import inspect
import threading

import pytest

from chesssnake.api import server
from chesssnake.db import operations as ops

pytestmark = pytest.mark.integration

#: Enough to prove overlap, comfortably under both ``pool_max_size`` (10) and
#: anyio's default 40-thread limit, so neither can confound the result.
CONCURRENCY = 3


def _all_routes(kind=None):
    """
    Every route in a built app, however it was included.

    FastAPI keeps included routers as wrappers rather than flattening them into
    ``app.routes``, and the public auth router is included on the app rather than
    into ``v1``; walking the route contexts finds them all. The app is built with
    websockets on, so ``/v1/ws`` is among them.
    """
    from fastapi.routing import APIRoute, iter_route_contexts

    from chesssnake.config import Settings

    kind = kind or APIRoute
    app = server.create_app(
        Settings(database={"url": "sqlite:////nonexistent/never-opened.db"}, websocket={"enabled": True})
    )
    return [c for c in iter_route_contexts(app.routes) if isinstance(c.route, kind)]


def test_health_is_the_only_route_on_the_event_loop():
    """
    Every ``/v1`` route must be ``def`` so Starlette runs it in the threadpool.

    ``/health`` is the one deliberate exception: it touches nothing, so leaving
    it on the event loop means it answers immediately even when every worker
    thread is busy. The container's HEALTHCHECK calls it with a 2 second
    timeout, and before this change it was measured at 325 ms while only eight
    board renders were in flight.
    """
    routes = _all_routes()
    on_the_loop = sorted(r.path for r in routes if inspect.iscoroutinefunction(r.route.endpoint))

    assert on_the_loop == ["/health"], (
        "These routes are `async def`, so they run on the event loop and block "
        f"every other request while they work: {on_the_loop}. Their bodies are "
        "blocking database and rendering calls, so they must be plain `def`."
    )
    # A new route that nobody thought about should trip this, not slip through.
    # (Websocket routes are not APIRoutes; /v1/ws is checked below.)
    assert len(routes) == 43, (
        f"expected 43 routes, found {len(routes)}; if you added one, confirm it is "
        "`def` and not `async def`, then update this count"
    )


def test_the_websocket_route_is_the_only_websocket_route():
    """
    ``/v1/ws`` is ``async def`` on purpose: it waits on sockets, and every blocking
    call it makes goes through ``anyio.to_thread`` on the broker's own limiter.
    """
    from fastapi.routing import APIWebSocketRoute

    sockets = _all_routes(APIWebSocketRoute)
    assert [(c.route.path, inspect.iscoroutinefunction(c.route.endpoint)) for c in sockets] == [("/v1/ws", True)]


def test_rest_stays_parallel_while_sockets_are_open(api_client, pair, monkeypatch):
    """Open, authenticated websockets hold no worker threads: REST still overlaps."""
    raw, _ = ops.token_create(pair[0], ops.TOKEN_API, name="threadpool")
    with api_client.websocket_connect("/v1/ws") as first, api_client.websocket_connect("/v1/ws") as second:
        for ws in (first, second):
            ws.send_json({"type": "auth", "token": raw})
            assert ws.receive_json()["type"] == "ready"
        test_requests_run_in_parallel(api_client, pair, monkeypatch)


def test_requests_run_in_parallel(api_client, pair, monkeypatch):
    """
    Three concurrent reads must be in flight at the same instant.

    A ``threading.Barrier`` proves overlap rather than measuring it: it can only
    be satisfied if all three requests reach it together. If the routes went
    back on the event loop the first request would block the other two, the
    barrier would break on its timeout, and this fails with a clear message
    instead of a slow test.
    """
    white, black = pair
    game_id = api_client.post("/v1/games", json={"white_id": white, "black_id": black}).json()["id"]

    barrier = threading.Barrier(CONCURRENCY, timeout=10)
    real_game_get = ops.game_get_by_id

    def gated(*args, **kwargs):
        # Delegate FIRST: game_get_by_id opens and closes its own transaction, so by
        # the time we wait, this thread holds no connection and no database
        # lock. Blocking inside a transaction instead would deadlock three
        # SQLite writers against each other and fail even with perfect
        # threading, which would make this test lie.
        row = real_game_get(*args, **kwargs)
        barrier.wait()
        return row

    monkeypatch.setattr(ops, "game_get_by_id", gated)

    statuses: list[int] = []
    failures: list[BaseException] = []
    lock = threading.Lock()

    def fetch():
        try:
            resp = api_client.get(f"/v1/games/{game_id}")
            with lock:
                statuses.append(resp.status_code)
        except BaseException as e:  # noqa: BLE001 - a broken barrier must not just print
            with lock:
                failures.append(e)

    threads = [threading.Thread(target=fetch) for _ in range(CONCURRENCY)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # A leaked thread would outlive the session engine and fail a later test
    # confusingly, possibly on the other backend.
    assert not any(t.is_alive() for t in threads), "a request thread never finished"
    assert not barrier.broken, (
        f"{CONCURRENCY} concurrent GETs never overlapped, so the route is being run on "
        "the event loop instead of the threadpool. Check it is `def`, not `async def`."
    )
    assert not failures, f"a request raised: {failures}"
    assert statuses == [200] * CONCURRENCY


def test_an_in_memory_database_is_refused(api_client, monkeypatch):
    """
    Serving an in-memory SQLite database is refused at startup.

    An in-memory URL gets a ``StaticPool``, which hands the same connection to
    every caller and does not serialize it. That survived while requests ran one
    at a time; with the routes in the threadpool two requests issue ``BEGIN`` on
    one connection and sqlite3 raises "cannot start a transaction within a
    transaction". It is not worth supporting rather than fixing: an in-memory
    database is discarded when the process exits, so it was never a way to run a
    game server.

    ``api_client`` is requested so this runs after the session engine exists;
    ``_engine`` is then cleared so the app under test owns engine creation and
    actually reaches the check (the lifespan skips it for a second app, whose
    database settings are ignored by design).
    """
    from fastapi.testclient import TestClient

    from chesssnake.api.server import create_app
    from chesssnake.config import Settings
    from chesssnake.db import engine as db_engine
    from chesssnake.db import errors

    monkeypatch.setattr(db_engine, "_engine", None)

    with pytest.raises(errors.SQLError, match="in-memory"):
        with TestClient(create_app(Settings(database={"url": "sqlite://"}))):
            pass  # pragma: no cover - the lifespan raises before the body runs


def test_a_saturated_pool_answers_503_not_500(api_client, pair, monkeypatch):
    """
    When every database connection is in use, the server says "busy", not "error".

    Requests share a pool of connections (``pool_max_size``, default 10). Now
    that they run concurrently they can all want one at once, and the one that
    cannot get a connection used to wait 30 seconds and then surface
    SQLAlchemy's internal timeout as a generic 500. That is both the wrong
    status (nothing is broken, the server is just saturated) and far too long
    to hold a request, since a worker thread running a sync route cannot be
    cancelled when the client gives up.

    Simulated by raising the timeout SQLAlchemy itself would raise, rather than
    by actually exhausting the pool, which would need enough concurrency to
    make the test slow and flaky.
    """
    from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

    from chesssnake.db import engine as db_engine

    white, black = pair
    game_id = api_client.post("/v1/games", json={"white_id": white, "black_id": black}).json()["id"]

    real_get_engine = db_engine.get_engine

    def exhausted():
        raise SQLAlchemyTimeoutError("QueuePool limit of size 1 overflow 9 reached, connection timed out")

    monkeypatch.setattr(db_engine, "get_engine", exhausted)
    try:
        resp = api_client.get(f"/v1/games/{game_id}")
    finally:
        monkeypatch.setattr(db_engine, "get_engine", real_get_engine)

    assert resp.status_code == 503, f"expected 503 Service Unavailable, got {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert body["error_type"] == "SQLBusyError"
    assert "busy" in body["detail"].lower()


def test_the_pool_gives_up_well_before_a_client_would():
    """SQLAlchemy's 30 second default is longer than any caller will wait."""
    from chesssnake.db import engine as db_engine

    assert db_engine.POOL_TIMEOUT_SECONDS <= 15
    engine = db_engine.create_engine("sqlite:////tmp/chesssnake-pool-timeout-check.db")
    try:
        assert engine.pool._timeout == db_engine.POOL_TIMEOUT_SECONDS
    finally:
        engine.dispose()
