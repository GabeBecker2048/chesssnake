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
SQLAlchemy nor psycopg, so importing them eagerly here would break
``pip install chesssnake[client]``.
"""

from typing import Any

from . import errors

#: Operations re-exported from :mod:`chesssnake.db.operations`.
_OPERATIONS = (
    "GameChange",
    "apply_game_change",
    "challenge_accept",
    "challenge_create",
    "challenge_delete",
    "challenge_get",
    "challenges_for",
    "current_games",
    "db_init",
    "game_delete",
    "game_get_by_id",
    "game_get_or_create",
    "game_history",
    "game_record",
    "games_between",
    "hash_token",
    "identity_get",
    "identity_link",
    "identity_unlink",
    "new_token",
    "token_create",
    "token_delete",
    "token_resolve",
    "tokens_list",
    "user_create",
    "user_credentials",
    "user_get",
    "user_get_by_name",
    "user_get_or_create_by_identity",
    "user_rehash_password",
    "user_rename",
    "user_set_disabled",
    "user_set_password",
    "user_set_role",
    "validate_ids",
    "validate_username",
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
