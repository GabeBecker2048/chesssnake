"""
PostgreSQL-specific behavior.

Before 0.9.0 this module held every query as hand-written SQL. Those queries now
live in :mod:`chesssnake.db.operations` as backend-agnostic SQLAlchemy Core
expressions; what remains here is only what genuinely differs from SQLite: row
locking, the dialect's upsert construct, and creating a database on a server that
already exists.
"""

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as _insert
from sqlalchemy.exc import SQLAlchemyError

from . import errors

#: PostgreSQL locks the individual game row with ``SELECT … FOR UPDATE``.
SUPPORTS_ROW_LOCKS = True

#: ``chesssnake init-db --create-database`` can issue ``CREATE DATABASE`` here.
CREATES_DATABASES = True

#: Database connected to in order to create another one, since a connection must
#: target *some* database. Every PostgreSQL cluster has this one.
MAINTENANCE_DB = "postgres"

insert = _insert


def lock_current_game(conn, stmt, of=None):
    """
    Read the current game row and hold a lock on it for the transaction.

    :param conn: An open connection inside a :func:`~chesssnake.db.engine.locked_transaction`.
    :param stmt: The select for the current game row.
    :param of: The table whose rows to lock (``FOR UPDATE OF``). The game select
        joins ``users`` twice for the players' names, and a bare ``FOR UPDATE``
        would lock those two user rows as well, serialising every game either
        player is in behind this one.
    :return: The executed result.
    """
    from .engine import require_write_transaction

    require_write_transaction()
    return conn.execute(stmt.with_for_update(of=of))


def lock_pair(conn, group_id, a, b):
    """
    Serialise every write that depends on "is there already a game or challenge
    between these two players in this group".

    Those checks are plain reads, so on their own two transactions could both see
    nothing and both create (A challenges B while B challenges A; an accept racing
    an admin creating the game with the colours reversed). A transaction-scoped
    advisory lock on the unordered pair makes the second wait for the first, and
    is released at commit or rollback. Row locks on ``users`` would also work but
    conflict with the key-share locks that foreign-key checks take.

    :param conn: An open connection inside a :func:`~chesssnake.db.engine.locked_transaction`.
    """
    from .engine import require_write_transaction

    require_write_transaction()
    low, high = sorted((int(a), int(b)))
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:pair, 0))"),
        {"pair": f"chesssnake-pair:{int(group_id)}:{low}:{high}"},
    )


def configure_engine(engine, **_kwargs) -> None:
    """No connect-time setup is needed for PostgreSQL."""


def admin_url(url, admin_db: str = MAINTENANCE_DB):
    """
    Derive a URL for the maintenance database, plus the target database's name.

    ``CREATE DATABASE`` cannot run on a connection to the database being created,
    so the target is swapped for the maintenance database. Every other connection
    parameter — credentials, port, ``sslmode``, a unix-socket host — is preserved.

    :param url: The parsed SQLAlchemy URL.
    :param admin_db: Database to connect to instead of the target one.
    :return: ``(admin_url, target_database_name)``.
    :raises errors.SQLError: If the URL names no database.
    """
    if not url.database:
        raise errors.SQLError("The database URL does not name a database, so there is nothing to create.")
    return url.set(database=admin_db), url.database


def create_database(url) -> str:
    """
    Create the target database if it does not already exist.

    :param url: The parsed SQLAlchemy URL of the database to create.
    :return: A human-readable description of what happened.
    :raises errors.SQLError: On insufficient privileges or any other failure.
    """
    from sqlalchemy import create_engine

    admin, db_name = admin_url(url)

    # AUTOCOMMIT because CREATE DATABASE cannot run inside a transaction block.
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}).scalar()
            if exists:
                return f"Database '{db_name}' already exists."
            # A database name cannot be a bound parameter in DDL, so it is quoted
            # by the dialect's own identifier preparer rather than by hand.
            quoted = engine.dialect.identifier_preparer.quote(db_name)
            conn.execute(text(f"CREATE DATABASE {quoted}"))
            return f"Database '{db_name}' created successfully."
    except SQLAlchemyError as e:
        # 42501 is insufficient_privilege (psycopg 3 calls the code `sqlstate`;
        # psycopg2 called it `pgcode`); the string check is a fallback for
        # locales that translate the message.
        sqlstate = getattr(getattr(e, "orig", None), "sqlstate", None)
        if sqlstate == "42501" or "permission denied" in str(e).lower():
            raise errors.SQLError(
                f"Insufficient privileges to create the database '{db_name}'. "
                f"Ensure the user has appropriate permissions:\n{e}"
            ) from e
        raise errors.SQLError(f"Database creation error: {e}") from e
    finally:
        engine.dispose()
