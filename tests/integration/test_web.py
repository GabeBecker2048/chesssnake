"""
The web UI (0.14.0): served at ``/`` by the api-endpoint, on by default.

These check what Python can: the page and every file it loads are served, with
the right types and the security headers, and turning it off removes it. The
scripts themselves are exercised in a real browser (see docs/browser.md).
"""

import posixpath
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

WEB = Path(__file__).resolve().parents[2] / "src" / "chesssnake" / "data" / "web"

#: Relative module imports: `import x from "./y.js"`, `import "./y.js"`, `export ... from "./y.js"`.
_IMPORT = re.compile(r"""(?:^|\n)\s*(?:import|export)\b[^;"']*?(?:from\s*)?["'](\.{1,2}/[^"']+)["']""")


def _headers_are_strict(resp):
    csp = resp.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    assert "connect-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cache-control"] == "no-cache"


def test_the_page_is_served_at_the_root_with_strict_headers(api_client):
    resp = api_client.get("/", headers={"Authorization": ""})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert '<script type="module" src="/assets/js/app.js">' in resp.text
    _headers_are_strict(resp)


def test_the_page_answers_head(api_client):
    resp = api_client.head("/", headers={"Authorization": ""})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    _headers_are_strict(resp)


def _referenced_assets():
    """Every file the page loads: from index.html, then every module's imports, recursively."""
    index = (WEB / "index.html").read_text()
    found = set(re.findall(r'(?:src|href)="(/assets/[^"]+)"', index))
    queue = [p for p in found if p.endswith(".js")]
    while queue:
        url = queue.pop()
        source = (WEB / url.removeprefix("/assets/")).read_text()
        for rel in _IMPORT.findall(source):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(url), rel))
            if target not in found:
                found.add(target)
                queue.append(target)
    return found


def test_every_file_the_page_loads_is_served_with_its_type(api_client):
    assets = _referenced_assets()
    # The entry point, every view, the stylesheet and the icon at least.
    assert {"/assets/js/app.js", "/assets/js/views/game.js", "/assets/js/views/admin.js", "/assets/style.css"} <= assets
    every_module = {f"/assets/{p.relative_to(WEB)}" for p in WEB.rglob("*.js")}
    assert every_module <= assets, f"modules nothing imports: {every_module - assets}"
    types = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png"}
    for url in sorted(assets):
        resp = api_client.get(url, headers={"Authorization": ""})
        assert resp.status_code == 200, url
        assert resp.headers["content-type"].startswith(types[Path(url).suffix]), (url, resp.headers["content-type"])
        _headers_are_strict(resp)


def test_scripts_never_write_markup():
    """Text reaches the page through textContent only; the CSP is the other half."""
    for path in WEB.rglob("*.js"):
        source = path.read_text()
        for pattern in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert pattern not in source, f"{path.name} uses {pattern}"


@pytest.mark.parametrize("piece", ["K0", "K1", "Q0", "N1", "P0", "P1"])
def test_pieces_are_the_rendered_boards_sprites(api_client, piece):
    resp = api_client.get(f"/assets/pieces/{piece}.png", headers={"Authorization": ""})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_nothing_outside_the_web_directory_is_reachable(api_client):
    for url in ("/assets/../chesssnake.toml", "/assets/%2e%2e/chesssnake.toml", "/assets/pieces/../web/index.html"):
        assert api_client.get(url).status_code == 404, url


def test_an_unknown_api_path_is_still_a_json_404(api_client):
    resp = api_client.get("/v1/no-such-thing")
    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/json"
    assert api_client.get("/no-such-page").status_code == 404


def test_turned_off_there_is_no_page_and_no_assets(settings):
    from fastapi.testclient import TestClient

    from chesssnake.api.server import create_app

    # No lifespan (no `with`): these paths never reach the database.
    client = TestClient(
        create_app(settings.model_copy(update={"web": settings.web.model_copy(update={"enabled": False})}))
    )
    assert client.get("/").status_code == 404
    assert client.get("/assets/js/app.js").status_code == 404
    assert client.get("/assets/pieces/K0.png").status_code == 404
    assert client.get("/v1/info").status_code == 200  # the API is unchanged


def test_it_is_on_by_default():
    from chesssnake.config import Settings

    assert Settings().web.enabled is True
