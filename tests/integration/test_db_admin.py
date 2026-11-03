"""
Tests for database administration: URL handling and database creation.

These cover the plumbing the configuration system feeds into the engine. Most of
it is backend-neutral and needs no database at all; the PostgreSQL
``CREATE DATABASE`` path does, and is marked accordingly.
"""

import pytest

pytest.importorskip("sqlalchemy")

from chesssnake.db import engine as db_engine
from chesssnake.db import errors

pytestmark = pytest.mark.integration


# --- URL validation --------------------------------------------------------


def test_missing_url_is_an_auth_error():
    with pytest.raises(errors.SQLAuthError):
        db_engine.parse_url(None)


def test_empty_url_is_an_auth_error():
    with pytest.raises(errors.SQLAuthError):
        db_engine.parse_url("")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("postgresql://u:pw@h:5432/chess", "postgresql"),
        ("postgresql+psycopg2://u@h/chess", "postgresql"),
        ("sqlite:///chess.db", "sqlite"),
        ("sqlite:////abs/chess.db", "sqlite"),
        ("sqlite://", "sqlite"),
    ],
)
def test_supported_backends_are_recognized(url, expected):
    assert db_engine.backend_name(url) == expected


def test_unsupported_backend_is_rejected():
    with pytest.raises(errors.SQLError, match="Unsupported database backend"):
        db_engine.parse_url("mysql://u@h/chess")


def test_bare_postgres_url_names_the_installed_driver():
    """
    SQLAlchemy's default driver for a bare `postgresql://` changed between 2.0
    (psycopg2) and 2.1 (psycopg v3), so the same URL and the same
    `chesssnake[api,postgres]` install worked or failed depending on which
    SQLAlchemy got resolved. It surfaced as `No module named 'psycopg'` from a
    package that had installed psycopg2. parse_url now names whichever driver
    is present, so the behaviour does not depend on that default.
    """
    import importlib.util

    parsed = db_engine.parse_url("postgresql://u:p@h:5432/chess")
    installed = next(
        (d for d in ("psycopg2", "psycopg") if importlib.util.find_spec(d) is not None),
        None,
    )
    if installed is None:
        pytest.skip("no PostgreSQL driver installed")
    assert parsed.drivername == f"postgresql+{installed}"


def test_an_explicit_postgres_driver_is_left_alone():
    """Naming a driver is a deliberate choice; it must survive parse_url."""
    assert db_engine.parse_url("postgresql+psycopg://u@h/chess").drivername == "postgresql+psycopg"
    assert db_engine.parse_url("postgresql+psycopg2://u@h/chess").drivername == "postgresql+psycopg2"


def test_sqlite_urls_are_not_given_a_driver():
    assert db_engine.parse_url("sqlite:///chess.db").drivername == "sqlite"


def test_keyword_dsn_is_rejected_with_the_url_equivalent():
    """Keyword connection strings worked before 0.9.0; the error has to explain that."""
    with pytest.raises(errors.SQLError) as exc:
        db_engine.parse_url("dbname='chess' user='u' host='h'")
    message = str(exc.value)
    assert "keyword connection string" in message
    assert "postgresql://" in message


def test_memory_urls_are_detected():
    assert db_engine.is_memory_url(db_engine.parse_url("sqlite://"))
    assert db_engine.is_memory_url(db_engine.parse_url("sqlite:///:memory:"))
    assert not db_engine.is_memory_url(db_engine.parse_url("sqlite:///chess.db"))
    assert not db_engine.is_memory_url(db_engine.parse_url("postgresql://u@h/chess"))


# --- PostgreSQL admin URLs -------------------------------------------------


def test_admin_url_targets_the_maintenance_database():
    from chesssnake.db import postgres

    admin, target = postgres.admin_url(db_engine.parse_url("postgresql://u:pw@h:5432/chess"))
    assert target == "chess"
    assert admin.database == "postgres"


def test_admin_url_preserves_other_parameters():
    from chesssnake.db import postgres

    admin, _ = postgres.admin_url(db_engine.parse_url("postgresql://u:pw@h/chess?sslmode=require"))
    assert admin.query["sslmode"] == "require"
    assert (admin.username, admin.password, admin.host) == ("u", "pw", "h")


def test_admin_url_rejects_a_url_without_a_database():
    from chesssnake.db import postgres

    with pytest.raises(errors.SQLError, match="does not name a database"):
        postgres.admin_url(db_engine.parse_url("postgresql://u:pw@h:5432/"))


# --- Creating databases ----------------------------------------------------


def test_sqlite_create_database_makes_the_parent_directory(tmp_path):
    from chesssnake.db import sqlite

    target = tmp_path / "nested" / "deeper" / "chess.db"
    sqlite.create_database(db_engine.parse_url(f"sqlite:///{target}"))
    assert target.parent.is_dir()
    assert not target.exists()  # the file itself appears on first connection


def test_sqlite_create_database_is_a_noop_in_memory():
    from chesssnake.db import sqlite

    assert "in-memory" in sqlite.create_database(db_engine.parse_url("sqlite://")).lower()


def test_postgres_create_database_and_schema(backend, database_url):
    """CREATE DATABASE cannot run inside a transaction; this fails if that regresses."""
    if backend != "postgresql":
        pytest.skip("PostgreSQL-only")
    from sqlalchemy import create_engine, inspect

    from chesssnake.db import postgres, schema

    target = db_engine.parse_url(database_url).set(database="created_by_test")
    postgres.create_database(target)

    created = create_engine(target)
    try:
        schema.create_all(created)
        assert set(inspect(created).get_table_names()) >= {t.name for t in schema.TABLES}
    finally:
        created.dispose()


def test_postgres_create_database_is_idempotent(backend, database_url):
    if backend != "postgresql":
        pytest.skip("PostgreSQL-only")
    from chesssnake.db import postgres

    target = db_engine.parse_url(database_url).set(database="created_twice")
    postgres.create_database(target)
    assert "already exists" in postgres.create_database(target)
