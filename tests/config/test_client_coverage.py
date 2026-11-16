"""
Every server route has a Python client method: the promise that a Python program
never needs to call the API by hand (0.15.4).

Advisory, not required to merge: marked ``client_coverage``, deselected by default
(``addopts``), and run by CI's ``client-coverage`` job, which may fail. Run it with
``uv run pytest -m client_coverage tests/config``.

Client methods declare the routes they call with ``@route(method, path)``
(``chesssnake.remote.client``); this compares those with the app's routes. A route
with no client method on purpose goes in ``NOT_FOR_CLIENTS`` with the reason.
"""

import inspect

import pytest

pytestmark = pytest.mark.client_coverage

#: Routes a Python client does not call, and why.
NOT_FOR_CLIENTS = {
    ("GET", "/health"): "a liveness probe for containers, not an API call",
    ("GET", "/"): "the web UI's page",
}


def _server_routes():
    from fastapi.routing import APIRoute, iter_route_contexts

    from chesssnake.api.server import create_app
    from chesssnake.config import Settings

    app = create_app(Settings(database={"url": "sqlite:////nonexistent/never-opened.db"}))
    return {
        (method, context.path)
        for context in iter_route_contexts(app.routes)
        if isinstance(context.route, APIRoute)
        for method in context.methods - {"HEAD"}
    }


def _client_routes(cls):
    routes = set()
    for _name, member in inspect.getmembers(cls, callable):
        routes.update(getattr(member, "__routes__", []))
    return routes


def test_every_route_has_a_client_method():
    from chesssnake import ApiClient

    missing = _server_routes() - _client_routes(ApiClient) - set(NOT_FOR_CLIENTS)
    assert not missing, f"server routes no ApiClient method calls: {sorted(missing)}"


def test_no_client_method_names_a_route_that_does_not_exist():
    from chesssnake import ApiClient

    stale = _client_routes(ApiClient) - _server_routes()
    assert not stale, f"client methods tagged with routes the server does not have: {sorted(stale)}"


def test_the_async_client_has_every_method():
    from chesssnake import ApiClient, AsyncApiClient

    def public(cls):
        return {n for n, m in inspect.getmembers(cls, callable) if not n.startswith("_") and not isinstance(m, type)}

    # Only the connection management differs: close vs aclose and the context managers.
    assert public(ApiClient) - public(AsyncApiClient) == set()
    assert public(AsyncApiClient) - public(ApiClient) == {"aclose"}
    assert _client_routes(AsyncApiClient) == _client_routes(ApiClient)
