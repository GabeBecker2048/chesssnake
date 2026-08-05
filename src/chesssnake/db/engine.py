"""
Database engine construction and transaction handling.

One :class:`sqlalchemy.engine.Engine` is created at startup from
``settings.database.url`` and held here. The URL's scheme selects the backend, so
``postgresql://…`` and ``sqlite:///…`` are the only configuration difference
between running against a server and running against a file.

Each backend needs setup the other does not, and those differences live in
:mod:`chesssnake.db.postgres` and :mod:`chesssnake.db.sqlite` rather than being
inferred. The important one is locking: PostgreSQL takes a row lock with
``SELECT … FOR UPDATE``, which SQLite does not support — and, dangerously,
silently *ignores* rather than rejecting. SQLite instead takes the database write
lock up front with ``BEGIN IMMEDIATE``. See :func:`locked_transaction`.
"""

from __future__ import annotations

import contextvars
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine as _sa_create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.pool import StaticPool

from . import errors

#: Backends this build knows how to talk to, mapped to the extra that provides
#: their driver (``None`` when the driver is in the standard library).
SUPPORTED_BACKENDS = {"postgresql": "postgres", "sqlite": None}

#: ``COUNT(*) FILTER (WHERE …)`` (``game_record``) needs SQLite 3.30 (2019);
#: ``INSERT … ON CONFLICT`` (``game_get_or_create``, ``challenge_create``) needs
#: 3.24. Do not lower this past 3.24 without replacing both.
MIN_SQLITE_VERSION = (3, 30, 0)

#: True while a :func:`locked_transaction` is open. The SQLite backend reads this
#: in its ``begin`` hook to choose ``BEGIN IMMEDIATE`` over a deferred ``BEGIN``.
#: A ContextVar rather than the pooled connection's ``info`` dict (which outlives
#: the checkout) or a module global (which is not thread- or task-safe).
WRITE_TRANSACTION: contextvars.ContextVar[bool] = contextvars.ContextVar("chesssnake_write_transaction", default=False)

_engine: Engine | None = None


# --- URL handling ----------------------------------------------------------


def parse_url(url: str | None):
    """
    Validate a database URL and return it parsed.

    :param url: The configured ``database.url``.
    :return: The parsed SQLAlchemy URL.
    :raises errors.SQLAuthError: If no URL is configured.
    :raises errors.SQLError: If the URL is malformed or names an unknown backend.
    """
    if not url:
        raise errors.SQLAuthError()
    try:
        parsed = make_url(url)
    except ArgumentError as e:
        # The most likely cause is a libpq keyword connection string, which was
        # accepted before 0.9.0 but cannot be expressed as a URL.
        if "=" in url and "://" not in url:
            raise errors.SQLError(
                "The database URL must be a URL, not a libpq keyword connection string.\n"
                f"  got:      {url}\n"
                "  expected: postgresql://user:password@host:5432/dbname\n"
                "Keyword connection strings (dbname='…' user='…') are no longer accepted."
            ) from e
        raise errors.SQLError(f"Could not parse the database URL: {e}") from e

    backend = parsed.get_backend_name()
    if backend not in SUPPORTED_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_BACKENDS))
        raise errors.SQLError(f"Unsupported database backend {backend!r}. Supported backends: {supported}.")
    return parsed


def backend_name(url: str) -> str:
    """Return the backend a URL selects, e.g. ``"postgresql"`` or ``"sqlite"``."""
    return parse_url(url).get_backend_name()


def is_memory_url(parsed) -> bool:
    """Whether a parsed SQLite URL refers to an in-memory database."""
    return parsed.get_backend_name() == "sqlite" and parsed.database in (None, "", ":memory:")


# --- Engine construction ---------------------------------------------------


def _engine_kwargs(parsed, pool_min_size: int, pool_max_size: int) -> dict[str, Any]:
    """
    Build ``create_engine`` keyword arguments appropriate to the backend.

    Pool sizing is not universally applicable: SQLAlchemy gives a file-backed
    SQLite database a ``QueuePool`` (which accepts sizing) but an in-memory one a
    ``SingletonThreadPool`` (which rejects it outright), so the arguments are only
    passed where they mean something.
    """
    if is_memory_url(parsed):
        # Every connection must see the same in-memory database, which is only
        # true when they are literally the same connection.
        return {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}

    # QueuePool opens connections lazily, so pool_min_size is a floor on what is
    # kept rather than opened up front (psycopg2's SimpleConnectionPool opened
    # minconn eagerly).
    kwargs: dict[str, Any] = {
        "pool_size": pool_min_size,
        "max_overflow": max(0, pool_max_size - pool_min_size),
    }
    if parsed.get_backend_name() == "sqlite":
        # SQLAlchemy sets this itself for a file database, but the failure mode if
        # it ever stopped is a thread-affinity error under load, so be explicit.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Long-lived TCP connections through NAT or a pooler die silently.
        kwargs["pool_pre_ping"] = True
    return kwargs


def create_engine(
    url: str,
    *,
    pool_min_size: int = 1,
    pool_max_size: int = 10,
    sqlite_busy_timeout: int = 5000,
) -> Engine:
    """
    Build an engine for a database URL, with backend-appropriate setup applied.

    :param url: The database URL; its scheme selects the backend.
    :param pool_min_size: Connections kept open persistently.
    :param pool_max_size: Ceiling on simultaneous connections.
    :param sqlite_busy_timeout: Milliseconds a blocked SQLite writer waits.
    :return: A configured engine.
    :raises errors.SQLAuthError: If no URL is configured.
    :raises errors.SQLError: If the URL is invalid or the driver is missing.
    """
    parsed = parse_url(url)
    backend = parsed.get_backend_name()

    try:
        engine = _sa_create_engine(parsed, **_engine_kwargs(parsed, pool_min_size, pool_max_size))
    except ModuleNotFoundError as e:
        extra = SUPPORTED_BACKENDS[backend]
        hint = f" Install it with: pip install 'chesssnake[api,{extra}]'" if extra else ""
        raise errors.SQLError(f"The {backend} driver is not installed ({e}).{hint}") from e
    except SQLAlchemyError as e:
        raise errors.SQLError(f"Could not create the database engine: {e}") from e

    if backend == "sqlite":
        from . import sqlite as backend_module

        backend_module.configure_engine(engine, busy_timeout=sqlite_busy_timeout)
    check_capabilities(engine)
    return engine


def initialize_engine(url: str, **kwargs: Any) -> Engine:
    """
    Create the process-wide engine. Called once at application startup.

    :param url: The database URL.
    :return: The engine, which is also stored for :func:`get_engine`.
    """
    global _engine
    _engine = create_engine(url, **kwargs)
    return _engine


def current_engine() -> Engine | None:
    """Return the process-wide engine, or ``None`` if none has been created."""
    return _engine


def get_engine() -> Engine:
    """
    Return the process-wide engine.

    :raises errors.SQLError: If no engine has been initialized.
    """
    if _engine is None:
        raise errors.SQLError("The database engine is not initialized.\n    Use chesssnake.db.engine.initialize_engine")
    return _engine


def dispose_engine() -> None:
    """
    Close every pooled connection and drop the engine.

    Safe to call when no engine was ever created, so teardown paths do not need to
    inspect module state themselves.
    """
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


def backend_module(name: str) -> Any:
    """
    Return the dialect shim module for a backend name.

    Imported lazily so that using SQLite never imports the PostgreSQL shim, which
    would pull in psycopg2 -- the whole point of the separate `postgres` extra.

    :param name: A backend name, e.g. ``"postgresql"`` or ``"sqlite"``.
    """
    if name == "sqlite":
        from . import sqlite

        return sqlite
    from . import postgres

    return postgres


def backend() -> Any:
    """Return the dialect shim module for the active engine."""
    return backend_module(get_engine().dialect.name)


# --- Transactions ----------------------------------------------------------


@contextmanager
def transaction() -> Iterator[Any]:
    """
    Run several statements in one transaction on a single pooled connection.

    Commits when the block exits cleanly and rolls back on any exception. A
    database error is wrapped in :class:`~chesssnake.db.errors.SQLError`; anything
    else propagates unchanged, which is what lets an engine ``ChessError`` raised
    inside :func:`~chesssnake.db.operations.apply_game_change`'s ``mutate``
    callback reach the caller with its own type intact.

    :raises errors.SQLError: On any database error, after rolling back.
    """
    try:
        with get_engine().begin() as conn:
            yield conn
    except errors.GameError:
        # Already one of ours (raised by a mutate callback or a guard); don't
        # rewrap it as a generic SQL failure.
        raise
    except SQLAlchemyError as e:
        raise errors.SQLError(f"SQL execution error: {e}") from e


@contextmanager
def locked_transaction() -> Iterator[Any]:
    """
    A transaction that may lock rows for a read-modify-write.

    On PostgreSQL this is an ordinary transaction; the lock is taken per row by
    ``SELECT … FOR UPDATE``. On SQLite there are no row locks, so the *whole
    database* write lock is taken as the transaction opens, via ``BEGIN
    IMMEDIATE``. Marking write transactions explicitly is what keeps ordinary
    reads from taking that lock too and queueing behind each other.

    Every read-modify-write must use this rather than :func:`transaction`.
    """
    token = WRITE_TRANSACTION.set(True)
    try:
        with transaction() as conn:
            yield conn
    finally:
        WRITE_TRANSACTION.reset(token)


def require_write_transaction() -> None:
    """
    Guard against locking a row outside :func:`locked_transaction`.

    Without this the mistake is invisible: PostgreSQL would take a ``FOR UPDATE``
    lock and drop it at the end of the implicit transaction, and SQLite would take
    no lock at all.

    :raises errors.SQLError: If called outside a write transaction.
    """
    if not WRITE_TRANSACTION.get():
        raise errors.SQLError(
            "A locking read was attempted outside locked_transaction(), so it would not be "
            "atomic. Wrap the read-modify-write in chesssnake.db.engine.locked_transaction()."
        )


def check_capabilities(engine: Engine) -> None:
    """
    Fail fast on a backend too old to run our queries.

    ``game_record`` uses ``COUNT(*) FILTER (WHERE …)``, which SQLite only gained in
    3.30. Python bundles its own SQLite, so this is a fixed floor rather than
    something that drifts.

    :raises errors.SQLError: If the backend is too old.
    """
    if engine.dialect.name == "sqlite" and sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        required = ".".join(str(part) for part in MIN_SQLITE_VERSION)
        raise errors.SQLError(
            f"SQLite {required} or newer is required (this Python is linked against "
            f"{sqlite3.sqlite_version}). Upgrade Python or its SQLite library, or use PostgreSQL."
        )
