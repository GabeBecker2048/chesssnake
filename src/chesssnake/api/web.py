"""
The web UI: a static page and its scripts, served next to the API.

The site is a plain client of ``/v1``. It logs in with ``/v1/auth/login``, keeps
the session token in the browser, sends it as ``Authorization: Bearer`` like any
other client, and follows games over ``/v1/ws`` when websockets are enabled (it
polls otherwise). So nothing here touches the database or the engine; this
module only serves files:

- ``GET /``: ``data/web/index.html``;
- ``/assets/...``: the rest of ``data/web`` (``style.css``, ``js/*.js``);
- ``/assets/pieces/...``: the piece images in ``data/img``, the same ones the
  API's rendered board uses.

Nothing is mounted at ``/`` itself, so an unknown ``/v1/...`` path still gets the
API's JSON 404 rather than a static-files one.

Every response carries a strict Content-Security-Policy. The session token lives
in ``localStorage``, where any script running on the page could read it, so the
policy allows scripts from this origin only, with no inline script, no
``eval`` and no third-party code. The scripts also put text on the page only
through ``textContent``.
"""

import mimetypes
import os

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from ..assets import asset_path

# The JS modules must be served as JavaScript, or browsers refuse to run them.
# Python's table comes from the OS (the Windows registry, /etc/mime.types), which
# has been seen to say text/plain; pin it.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")

#: Scripts, styles, images and connections (fetch and the websocket) from this
#: origin only. `connect-src 'self'` covers ws:/wss: to the same host in every
#: current browser (CSP Level 3).
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Revalidate every time (the ETag makes that a 304), so an upgraded server's
    # page and scripts are never mixed with a cached older version.
    "Cache-Control": "no-cache",
}


class _StaticFiles(StaticFiles):
    """StaticFiles with the security and caching headers on every file."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(SECURITY_HEADERS)
        return response


def web_root() -> str:
    """The directory the web UI's files are served from."""
    return asset_path("web")


def add_web_routes(app: FastAPI) -> None:
    """Serve the web UI on ``app``: the page at ``/`` and its files under ``/assets``."""
    root = web_root()
    index = os.path.join(root, "index.html")
    router = APIRouter()

    # A plain `def`, like every route but /health and /v1/ws: FileResponse stats
    # the file, which is blocking work (test_threadpool.py checks this).
    # HEAD too: uptime checks and `curl -I` use it, and a GET-only route answers 405.
    @router.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def web_index():
        return FileResponse(index, media_type="text/html; charset=utf-8", headers=SECURITY_HEADERS)

    app.include_router(router)
    # The more specific mount first: Starlette tries mounts in order, and
    # /assets would otherwise take /assets/pieces/... and 404 it.
    app.mount("/assets/pieces", _StaticFiles(directory=asset_path("img")), name="web-pieces")
    app.mount("/assets", _StaticFiles(directory=root), name="web-assets")
