"""
Tests for the database administration helpers in ``chesssnake.db.sql``.

These cover the DSN plumbing that the configuration system feeds: deriving a
maintenance-database connection and creating the target database. The
create-database path had never worked before 0.8.0 (it built an unusable admin
connection string, and then tried to run ``CREATE DATABASE`` inside a
transaction), so it is worth pinning down.
"""

import psycopg2
import pytest
from psycopg2.extensions import make_dsn, parse_dsn

from chesssnake.db import errors
from chesssnake.db.sql import admin_dsn, psql_db_init, require_dsn

pytestmark = pytest.mark.integration


def test_require_dsn_rejects_nothing_configured():
    with pytest.raises(errors.SQLAuthError):
        require_dsn(None)


def test_admin_dsn_targets_the_maintenance_database():
    admin, target = admin_dsn("postgresql://u:pw@h:5432/chess")
    assert target == "chess"
    assert parse_dsn(admin)["dbname"] == "postgres"


def test_admin_dsn_preserves_other_parameters():
    admin, _ = admin_dsn("postgresql://u:pw@h/chess?sslmode=require")
    parsed = parse_dsn(admin)
    assert parsed["sslmode"] == "require"
    assert (parsed["user"], parsed["password"], parsed["host"]) == ("u", "pw", "h")


def test_admin_dsn_accepts_keyword_form():
    admin, target = admin_dsn("dbname='chess' user='u' host='h'")
    assert target == "chess"
    assert parse_dsn(admin)["dbname"] == "postgres"


def test_admin_dsn_rejects_a_dsn_without_a_database():
    with pytest.raises(errors.SQLError, match="does not name a database"):
        admin_dsn("postgresql://u:pw@h:5432/")


def _with_dbname(dsn, name):
    return make_dsn(**{**parse_dsn(dsn), "dbname": name})


def test_create_database_and_schema(database_url):
    """CREATE DATABASE cannot run in a transaction; this fails if that regresses."""
    target = _with_dbname(database_url, "created_by_test")
    psql_db_init(target)

    conn = psycopg2.connect(target)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name IN ('games', 'moves', 'challenges')"
            )
            assert cur.fetchone()[0] == 3
    finally:
        conn.close()


def test_create_database_is_idempotent(database_url):
    target = _with_dbname(database_url, "created_twice")
    psql_db_init(target)
    psql_db_init(target)  # must not raise on the second run
