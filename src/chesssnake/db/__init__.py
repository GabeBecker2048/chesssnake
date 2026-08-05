"""Persistence layer — the common database interface.

The active backend is PostgreSQL (:mod:`chesssnake.db.postgres`, with connection
plumbing in :mod:`chesssnake.db.sql`). The operation functions are re-exported
here so callers depend on ``chesssnake.db`` rather than a specific backend; a
future ``chesssnake.db.sqlite`` can implement the same functions behind this
same interface.

The backend modules are imported lazily, because ``errors`` is shared with the
remote client for error mapping (``remote/client.py``) while ``postgres``/``sql``
pull in psycopg2 — which the ``client`` extra does not install. Importing them
eagerly made ``pip install chesssnake[client]`` fail on ``Game.remote(...)``.
"""

from typing import Any

from . import errors

_LAZY = (
    "apply_game_change",
    "challenge",
    "challenge_create",
    "challenge_delete",
    "challenge_exists",
    "current_games",
    "db_init",
    "game_archive",
    "game_delete",
    "game_exists",
    "game_get",
    "game_get_or_create",
    "game_history",
    "game_record",
)


def __getattr__(name: str) -> Any:
    """Resolve backend operations (and the ``postgres``/``sql`` modules) on first use."""
    if name in _LAZY:
        from . import postgres

        return getattr(postgres, name)
    if name in ("postgres", "sql"):
        import importlib

        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "errors",
    "postgres",
    "sql",
    "db_init",
    "game_get_or_create",
    "game_get",
    "game_archive",
    "game_history",
    "game_record",
    "apply_game_change",
    "game_delete",
    "current_games",
    "game_exists",
    "challenge",
    "challenge_create",
    "challenge_delete",
    "challenge_exists",
]
