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
        with pytest.raises(errors.DatabaseError, match="locked_transaction"):
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
            assert conn.execute(text("SELECT count(*) FROM finished_games")).scalar() == 0
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


# --- Schema behavior the operations layer relies on ------------------------


def _user(conn, name):
    from chesssnake.db.operations import _utcnow

    return conn.execute(schema.users.insert().values(username=name, created_at=_utcnow())).inserted_primary_key[0]


def _game(conn, white, black, group_id=1):
    from chesssnake.db.operations import _utcnow

    now = _utcnow()
    return conn.execute(
        schema.games.insert().values(
            group_id=group_id, white_id=white, black_id=black, fen="x", started_at=now, updated_at=now
        )
    ).inserted_primary_key[0]


def test_timestamps_come_back_as_datetimes(file_engine):
    """The operations layer calls .isoformat(); raw sqlite3 would have returned a string."""
    import datetime as dt

    with file_engine.begin() as conn:
        game_id = _game(conn, _user(conn, "ann"), _user(conn, "bob"))
        value = conn.execute(schema.games.select().where(schema.games.c.id == game_id)).mappings().one()["updated_at"]
    assert isinstance(value, dt.datetime)


def test_timestamps_normalise_to_utc(file_engine):
    """
    SQLite keeps the wall-clock text and drops the offset, so only UTC may be written,
    and a naive value read back is UTC.
    """
    import datetime as dt

    from chesssnake.db.operations import _as_utc

    with file_engine.begin() as conn:
        _user(conn, "ann")
        stored = conn.execute(schema.users.select()).mappings().one()["created_at"]
    assert stored.tzinfo is None, "pins the SQLite behavior _as_utc exists for"
    assert _as_utc(stored).tzinfo == dt.UTC
    aware = dt.datetime(2026, 1, 1, 12, tzinfo=dt.timezone(dt.timedelta(hours=5)))
    assert _as_utc(aware) == aware and _as_utc(aware).tzinfo == dt.UTC


def test_foreign_keys_are_enforced(file_engine):
    """Off by default in SQLite; the connect hook turns them on."""
    from sqlalchemy.exc import IntegrityError

    with file_engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    with pytest.raises(IntegrityError):
        with file_engine.begin() as conn:
            _game(conn, 1001, 1002)


def test_deleting_a_game_cascades_to_its_moves(file_engine):
    from sqlalchemy import delete, func, select

    with file_engine.begin() as conn:
        game_id = _game(conn, _user(conn, "ann"), _user(conn, "bob"))
        conn.execute(schema.moves.insert().values(game_id=game_id, ply=1, san="e4", position_key="k"))
        conn.execute(delete(schema.games).where(schema.games.c.id == game_id))
        assert conn.execute(select(func.count()).select_from(schema.moves)).scalar() == 0


def test_game_ids_are_never_reused(file_engine):
    """
    Without AUTOINCREMENT SQLite hands out max(rowid) + 1, so deleting the newest
    game (as archiving it does) would give its id to the next one, colliding with
    the finished_games row that kept it.
    """
    from sqlalchemy import delete

    with file_engine.begin() as conn:
        white, black = _user(conn, "ann"), _user(conn, "bob")
        first = _game(conn, white, black)
        conn.execute(delete(schema.games).where(schema.games.c.id == first))
        assert _game(conn, white, black) > first


def test_missing_driver_reports_the_extra_to_install(monkeypatch):
    """A postgresql:// URL without psycopg (3) should say how to fix it."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psycopg" or name.startswith("psycopg."):
            raise ModuleNotFoundError("No module named 'psycopg'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(errors.DatabaseError, match=r"chesssnake\[api,postgres\]"):
        db_engine.create_engine("postgresql://u:pw@localhost/chess")
