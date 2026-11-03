"""
Where ``chesssnake login`` keeps tokens, and how they are read back.

Standard library only: ``chesssnake play`` and :func:`chesssnake.connect` read this,
and neither may import :mod:`chesssnake.config` (pydantic is not part of the
``client`` install).

The file is ``credentials.json`` in, in order:

1. ``$CHESSSNAKE_HOME``, if set (the same variable the config file honours);
2. ``$XDG_CONFIG_HOME/chesssnake``;
3. ``~/.config/chesssnake``.

Unlike config discovery it is **never** the working directory: a token written
next to whatever you happened to be in, such as a git checkout, is a token one
``git add -A`` away from being published. The directory is created ``0700`` and
the file is written ``0600`` and replaced atomically, so a reader never sees half
of it. Tokens are keyed by the endpoint's normalised URL, so one machine can be
logged in to several endpoints.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

#: Must equal the bootstrap variable :mod:`chesssnake.config` reads; a test keeps
#: the two in step, since this module cannot import that one.
HOME_ENV = "CHESSSNAKE_HOME"
FILENAME = "credentials.json"


def credentials_path(environ=None) -> Path:
    """Where the credentials file lives (whether or not it exists yet)."""
    environ = os.environ if environ is None else environ
    if environ.get(HOME_ENV):
        return Path(environ[HOME_ENV]).expanduser() / FILENAME
    base = environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "chesssnake" / FILENAME


def normalize_url(url: str) -> str:
    """``HTTPS://Chess.Example/`` and ``https://chess.example`` are the same endpoint."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load(url: str, environ=None) -> dict | None:
    """The stored ``{"token", "username"}`` for an endpoint, or ``None``."""
    entry = _read(credentials_path(environ)).get(normalize_url(url))
    return entry if isinstance(entry, dict) and entry.get("token") else None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".credentials-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def save(url: str, token: str, username: str, environ=None) -> Path:
    """Store a token for an endpoint, replacing any previous one. :return: The file's path."""
    path = credentials_path(environ)
    data = _read(path)
    data[normalize_url(url)] = {"token": token, "username": username}
    _write(path, data)
    return path


def forget(url: str, environ=None) -> bool:
    """Remove an endpoint's token. :return: Whether there was one."""
    path = credentials_path(environ)
    data = _read(path)
    if data.pop(normalize_url(url), None) is None:
        return False
    _write(path, data)
    return True
