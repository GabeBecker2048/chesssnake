"""Check the built docs site: every internal link and #anchor resolves.

    python scripts/check_docs.py _site /chesssnake

CI runs it on the site GitHub Pages' own builder made from docs/.
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        for key in ("href", "src"):
            if a.get(key):
                self.links.append(a[key])


def main(site: Path, baseurl: str) -> int:
    pages: dict[str, Page] = {}
    for f in site.rglob("*.html"):
        p = Page()
        p.feed(f.read_text(encoding="utf-8"))
        pages["/" + f.relative_to(site).as_posix()] = p

    def target(path: str) -> str | None:
        """A site path (baseurl removed) to the file that serves it."""
        if not path.startswith(baseurl + "/") and path != baseurl:
            return None
        rel = path[len(baseurl) :] or "/"
        if rel.endswith("/"):
            rel += "index.html"
        return rel

    errors = []
    for name, page in sorted(pages.items()):
        here = baseurl + name
        for link in page.links:
            if urlsplit(link).scheme or link.startswith(("//", "mailto:", "data:")):
                continue
            url, frag = urldefrag(urljoin(here, link))
            rel = target(urlsplit(url).path)
            if rel is None:
                errors.append(f"{name}: {link} is outside {baseurl}/")
            elif not (site / rel.lstrip("/")).exists():
                errors.append(f"{name}: {link} -> {rel} does not exist")
            elif frag and rel in pages and frag not in pages[rel].ids:
                errors.append(f"{name}: {link} -> no #{frag} on {rel}")
    for e in errors:
        print(e)
    print(f"{len(pages)} pages, {len(errors)} broken links")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2].rstrip("/")))
