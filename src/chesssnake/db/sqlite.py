"""
SQLite-specific behavior.

Everything here exists because SQLite differs from PostgreSQL in a way the shared
query layer cannot paper over. The queries themselves live in
:mod:`chesssnake.db.operations` and are backend-agnostic.

SQLite is a good fit for a single api-endpoint process serving many clients, which
is what this configuration targets. It is not a fit for multiple worker processes
writing concurrently, and it must not be placed on a network filesystem — its
locking depends on POSIX advisory locks that NFS does not implement reliably.
"""

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.dialects.sqlite import insert as _insert

from . import errors

#: SQLite has no row-level locking. Writers serialize on the whole database, taken
#: at transaction start; see :func:`configure_engine`.
SUPPORTS_ROW_LOCKS = False

#: What ``chesssnake init-db --create-database`` means here.
CREATES_DATABASES = True

insert = _insert


def lock_current_game(conn, stmt):
    """
    Read the current game inside an already-exclusive transaction.

    Deliberately *not* ``stmt.with_for_update()``. SQLite does not support
    ``FOR UPDATE``, and SQLAlchemy compiles it away silently rather than raising —
    so using it here would look correct while leaving the read-modify-write
    unprotected. The exclusive lock was already acquired by ``BEGIN IMMEDIATE``
    when this transaction opened.

    :param conn: An open connection inside a :func:`~chesssnake.db.engine.locked_transaction`.
    :param stmt: The select for the current game row.
    :return: The executed result.
    """
    from .engine import require_write_transaction

    require_write_transaction()
    return conn.execute(stmt)


def configure_engine(engine, busy_timeout: int = 5000) -> None:
    """
    Attach the connect and begin hooks that make concurrent writers safe.

    :param engine: The engine to configure.
    :param busy_timeout: Milliseconds a blocked writer waits before giving up.
    """

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        # pysqlite opens transactions implicitly and at the wrong moments. Turning
        # its legacy handling off is what lets us issue BEGIN IMMEDIATE ourselves.
        dbapi_conn.isolation_level = None
        cursor = dbapi_conn.cursor()
        try:
            # WAL lets readers continue while a writer holds the lock, which is
            # what makes concurrent HTTP requests workable at all.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout)}")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        # IMMEDIATE takes the write lock as the transaction opens rather than on
        # the first write. With a deferred BEGIN two read-modify-write sequences
        # both start as readers, both read the same version, and the second either
        # fails upgrading the lock or clobbers the first -- exactly what
        # apply_game_change must prevent. Plain reads keep the deferred BEGIN so
        # they don't serialize against each other.
        from .engine import WRITE_TRANSACTION

        conn.exec_driver_sql("BEGIN IMMEDIATE" if WRITE_TRANSACTION.get() else "BEGIN")


def create_database(url) -> str:
    """
    Ensure the database file's directory exists.

    SQLite creates the file itself on first connection; only the parent directory
    has to exist, and a missing one is a confusing "unable to open database file"
    error otherwise.

    :param url: The parsed SQLAlchemy URL.
    :return: A human-readable description of what happened.
    :raises errors.SQLError: If the directory cannot be created.
    """
    if url.database in (None, "", ":memory:"):
        return "In-memory SQLite database; nothing to create."

    path = Path(url.database)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise errors.SQLError(f"Could not create the directory for {path}: {e}") from e

    if path.exists():
        return f"SQLite database '{path}' already exists."
    return f"SQLite database '{path}' will be created on first connection."
