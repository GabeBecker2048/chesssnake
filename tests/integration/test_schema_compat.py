"""
The SQLAlchemy metadata must describe the same database the pre-0.9.0 SQL did.

``create_all(checkfirst=True)`` leaves an existing table exactly as it is, so
drift here does not fail at startup — it fails on the first query against a
database somebody deployed on 0.8.0. This builds both schemas on the same
throwaway PostgreSQL server and compares what the database reports back.

Comparing reflections rather than DDL text matters: SQLAlchemy emits
``TIMESTAMP WITHOUT TIME ZONE`` where the old script wrote ``TIMESTAMP``, and
those are the same type. Constraint *names* also differ by construction, since
PostgreSQL auto-names the old script's inline CHECKs — the predicates are what
has to match.
"""

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, inspect, text

from chesssnake.db import engine as db_engine
from chesssnake.db import schema

pytestmark = pytest.mark.integration

LEGACY_SQL = Path(__file__).parent.parent / "legacy_schema.sql"
TABLES = ("games", "moves", "challenges")


def _shape(engine):
    """Everything about the schema that a query could depend on."""
    inspector = inspect(engine)
    return {
        table: {
            "columns": {
                column["name"]: (str(column["type"]), column["nullable"]) for column in inspector.get_columns(table)
            },
            "primary_key": tuple(inspector.get_pk_constraint(table)["constrained_columns"]),
            "indexes": {index["name"]: tuple(index["column_names"]) for index in inspector.get_indexes(table)},
            "checks": sorted(" ".join(check["sqltext"].split()) for check in inspector.get_check_constraints(table)),
        }
        for table in TABLES
    }


def _build(database_url, name, builder):
    """Create a fresh database and populate its schema with ``builder``."""
    from chesssnake.db import postgres

    target = db_engine.parse_url(database_url).set(database=name)
    postgres.create_database(target)
    engine = create_engine(target)
    builder(engine)
    return engine


def test_metadata_matches_the_legacy_schema(backend, database_url):
    if backend != "postgresql":
        pytest.skip("compares against the PostgreSQL schema that init.sql deployed")

    def legacy(engine):
        with engine.begin() as conn:
            conn.execute(text(LEGACY_SQL.read_text()))

    old = _build(database_url, "compat_legacy", legacy)
    new = _build(database_url, "compat_modern", schema.create_all)
    try:
        assert _shape(old) == _shape(new)
    finally:
        old.dispose()
        new.dispose()


def test_legacy_database_is_usable_without_migration(backend, database_url):
    """A 0.8.0 database must serve 0.9.0 queries untouched — no ALTER, no rename."""
    if backend != "postgresql":
        pytest.skip("PostgreSQL-only")
    from chesssnake.db import operations as ops

    def legacy(engine):
        with engine.begin() as conn:
            conn.execute(text(LEGACY_SQL.read_text()))

    old = _build(database_url, "compat_legacy_ops", legacy)
    try:
        # Point the process-wide engine at the legacy database and exercise the
        # real operations against it.
        db_engine.dispose_engine()
        db_engine.initialize_engine(str(old.url))
        # create_all must be a no-op here rather than trying to alter anything.
        schema.create_all(db_engine.get_engine())

        row = ops.game_get_or_create(500, 501, 502, "startpos-fen", "startpos-key", "W", "B")
        assert row["fen"] == "startpos-fen"
        assert row["wname"] == "W"

        def mutate(game_row, history):
            columns = {"fen": "after-move", "draw": None, "status": 0, "termination": None}
            return columns, [{"ply": history["max_ply"] + 1, "san": "e4", "position_key": "k"}], "ok"

        assert ops.apply_game_change(500, 501, 502, mutate) == "ok"
        assert ops.game_history(500, 501, 502, 1) == [{"ply": 1, "san": "e4"}]
        assert ops.game_archive(500, 501, 502)[0]["fen"] == "after-move"
    finally:
        db_engine.dispose_engine()
        old.dispose()
