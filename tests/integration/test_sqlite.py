"""
SQLite-specific behavior.

These do not need the shared backend fixtures — they build their own engines — so
they run everywhere, including on interpreters where ``pgserver`` is unavailable.
"""

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import text
from sqlalchemy.dialects import postgresql as pg_dialect
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.pool import StaticPool

from chesssnake.db import engine as db_engine
from chesssnake.db import errors, postgres, schema, sqlite

pytestmark = pytest.mark.integration


@pytest.fixture
def file_engine(tmp_path):
    engine = db_engine.create_engine(f"sqlite:///{tmp_path / 'chess.db'}")
    schema.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


# --- The FOR UPDATE trap ---------------------------------------------------


def test_sqlite_lock_does_not_emit_for_update(file_engine, monkeypatch):
    """
    SQLAlchemy compiles FOR UPDATE *away* on SQLite instead of raising, so using
    it here would look correct while leaving the read-modify-write unprotected.
    """
    monkeypatch.setattr(db_engine, "_engine", file_engine)
    stmt = schema.games.select().limit(1)
    with db_engine.locked_transaction() as conn:
        compiled = str(sqlite.lock_current_game(conn, stmt).context.compiled)
    assert "FOR UPDATE" not in compiled.upper()


def test_locking_outside_a_write_transaction_is_rejected(file_engine, monkeypatch):
    """
    The mistake is otherwise invisible: PostgreSQL would take a FOR UPDATE lock
    and drop it immediately, and SQLite would take no lock at all.
    """
    monkeypatch.setattr(db_engine, "_engine", file_engine)
    stmt = schema.games.select().limit(1)
    with db_engine.transaction() as conn:
        with pytest.raises(errors.SQLError, match="locked_transaction"):
            sqlite.lock_current_game(conn, stmt)


def test_reads_do_not_take_the_write_lock(file_engine, monkeypatch):
    """
    Plain reads use a deferred BEGIN so they don't serialize against each other;
    only locked_transaction() escalates to BEGIN IMMEDIATE.
    """
    monkeypatch.setattr(db_engine, "_engine", file_engine)
    assert db_engine.WRITE_TRANSACTION.get() is False
    with db_engine.transaction():
        assert db_engine.WRITE_TRANSACTION.get() is False
    with db_engine.locked_transaction():
        assert db_engine.WRITE_TRANSACTION.get() is True
    assert db_engine.WRITE_TRANSACTION.get() is False


def test_postgres_lock_does_emit_for_update():
    stmt = schema.games.select().limit(1)
    compiled = str(stmt.with_for_update().compile(dialect=pg_dialect.dialect()))
    assert "FOR UPDATE" in compiled.upper()


def test_for_update_would_silently_vanish_on_sqlite():
    """Pins the SQLAlchemy behavior this design exists to work around."""
    stmt = schema.games.select().limit(1).with_for_update()
    assert "FOR UPDATE" not in str(stmt.compile(dialect=sqlite_dialect.dialect())).upper()


def test_backends_declare_their_locking_capability():
    assert postgres.SUPPORTS_ROW_LOCKS is True
    assert sqlite.SUPPORTS_ROW_LOCKS is False


# --- Connect-time configuration --------------------------------------------


def test_wal_mode_is_enabled(file_engine):
    """WAL is what lets readers proceed while a writer holds the lock."""
    with file_engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"


def test_busy_timeout_is_applied(tmp_path):
    engine = db_engine.create_engine(f"sqlite:///{tmp_path / 'chess.db'}", sqlite_busy_timeout=1234)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 1234
    finally:
        engine.dispose()


def test_sqlite_version_supports_filter():
    """game_record uses COUNT(*) FILTER, which SQLite gained in 3.30."""
    import sqlite3

    assert sqlite3.sqlite_version_info >= db_engine.MIN_SQLITE_VERSION


# --- Engine construction ---------------------------------------------------


def test_memory_engine_uses_a_shared_connection():
    """An in-memory database only exists for as long as its connection does."""
    engine = db_engine.create_engine("sqlite://")
    try:
        assert isinstance(engine.pool, StaticPool)
        schema.create_all(engine)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM games")).scalar() == 0
    finally:
        engine.dispose()


def test_file_engine_accepts_pool_sizing(tmp_path):
    engine = db_engine.create_engine(f"sqlite:///{tmp_path / 'c.db'}", pool_min_size=2, pool_max_size=5)
    try:
        assert engine.pool.size() == 2
    finally:
        engine.dispose()


def test_schema_creation_is_idempotent(file_engine):
    schema.create_all(file_engine)
    schema.create_all(file_engine)  # must not raise


def test_timestamps_come_back_as_datetimes(file_engine):
    """game_archive calls .isoformat(); raw sqlite3 would have returned a string."""
    import datetime as dt

    schema.create_all(file_engine)
    with file_engine.begin() as conn:
        conn.execute(
            schema.games.insert().values(groupid=1, whiteid=2, blackid=3, generation=1, fen="x", status=0, version=1)
        )
        value = conn.execute(schema.games.select()).mappings().one()["updatedat"]
    assert isinstance(value, dt.datetime)


def test_missing_driver_reports_the_extra_to_install(monkeypatch):
    """A postgresql:// URL without psycopg2 should say how to fix it."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("psycopg2"):
            raise ModuleNotFoundError("No module named 'psycopg2'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(errors.SQLError, match=r"chesssnake\[api,postgres\]"):
        db_engine.create_engine("postgresql://u:pw@localhost/chess")
