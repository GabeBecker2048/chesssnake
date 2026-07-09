"""Persistence layer — the common database interface.

The active backend is PostgreSQL (:mod:`chesssnake.db.postgres`, with connection
plumbing in :mod:`chesssnake.db.sql`). The operation functions are re-exported
here so callers depend on ``chesssnake.db`` rather than a specific backend; a
future ``chesssnake.db.sqlite`` can implement the same functions behind this
same interface.
"""

from . import errors, postgres, sql
from .postgres import (
    INITIAL_BOARD,
    apply_game_change,
    challenge,
    challenge_create,
    challenge_delete,
    challenge_exists,
    current_games,
    db_init,
    game_delete,
    game_exists,
    game_get,
    game_get_or_create,
)

__all__ = [
    "errors",
    "postgres",
    "sql",
    "INITIAL_BOARD",
    "db_init",
    "game_get_or_create",
    "game_get",
    "apply_game_change",
    "game_delete",
    "current_games",
    "game_exists",
    "challenge",
    "challenge_create",
    "challenge_delete",
    "challenge_exists",
]
