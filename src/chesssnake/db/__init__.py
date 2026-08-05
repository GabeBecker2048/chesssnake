"""Persistence layer — the common database interface.

Queries are backend-agnostic SQLAlchemy Core expressions in
:mod:`chesssnake.db.operations`, built against the schema in
:mod:`chesssnake.db.schema`. The backend is chosen by the scheme of
``settings.database.url``: ``postgresql://…`` or ``sqlite:///…``. Only the
handful of things that genuinely differ between them — row locking, the upsert
construct, creating a database — live in :mod:`chesssnake.db.postgres` and
:mod:`chesssnake.db.sqlite`.

Everything is imported lazily except ``errors``, which is shared with the remote
client for error mapping (``remote/client.py``). The client extra installs neither
SQLAlchemy nor psycopg2, so importing them eagerly here would break
``pip install chesssnake[client]``.
"""

from typing import Any

from . import errors

#: Operations re-exported from :mod:`chesssnake.db.operations`.
_OPERATIONS = (
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
    "validate_ids",
)

_MODULES = ("engine", "operations", "postgres", "schema", "sqlite")


def __getattr__(name: str) -> Any:
    """Resolve operations and backend modules on first use."""
    if name in _OPERATIONS:
        from . import operations

        return getattr(operations, name)
    if name in _MODULES:
        import importlib

        return importlib.import_module(f".{name}", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "errors",
    *_MODULES,
    *_OPERATIONS,
]
