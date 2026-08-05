"""
Tests for the SQLAlchemy schema definitions.

The load-bearing property here is *compatibility with databases that already
exist*. Before 0.9.0 the schema was a hand-written ``init.sql`` whose unquoted
mixed-case identifiers PostgreSQL folded to lowercase. SQLAlchemy quotes any
identifier that is not already lowercase, so a mixed-case column definition would
emit ``games."GroupId"`` and fail to match the deployed ``games.groupid``. These
tests pin the lowercase convention and the generated DDL so that can't regress.

They need SQLAlchemy but no database, so they live here rather than in
``tests/integration``.
"""

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from chesssnake.db import schema

DIALECTS = {"postgresql": postgresql.dialect(), "sqlite": sqlite.dialect()}


def ddl(table, dialect):
    return str(CreateTable(table).compile(dialect=DIALECTS[dialect]))


@pytest.fixture(params=sorted(DIALECTS))
def dialect(request):
    return request.param


# --- The lowercase convention ----------------------------------------------


def test_every_identifier_is_lowercase():
    """Mixed case would be quoted, and quoted names don't match existing databases."""
    for table in schema.TABLES:
        assert table.name == table.name.lower(), f"table {table.name} is not lowercase"
        for column in table.columns:
            assert column.name == column.name.lower(), f"{table.name}.{column.name} is not lowercase"
    for index in (ix for table in schema.TABLES for ix in table.indexes):
        assert index.name == index.name.lower()


def test_identifiers_are_emitted_unquoted(dialect):
    """The actual guarantee: no quoting, so the SQL matches a pre-0.9.0 database."""
    for table in schema.TABLES:
        assert '"' not in ddl(table, dialect), f"{table.name} DDL quotes an identifier on {dialect}"


# --- Shape matches the pre-0.9.0 init.sql ----------------------------------


def test_table_names():
    assert {t.name for t in schema.TABLES} == {"games", "moves", "challenges"}


@pytest.mark.parametrize(
    "table,expected",
    [
        ("games", ["groupid", "whiteid", "blackid", "generation"]),
        ("moves", ["groupid", "whiteid", "blackid", "generation", "ply"]),
        ("challenges", ["groupid", "challenger", "challenged"]),
    ],
)
def test_composite_primary_keys(table, expected):
    assert [c.name for c in schema.metadata.tables[table].primary_key.columns] == expected


def test_games_columns():
    assert [c.name for c in schema.games.columns] == [
        "groupid",
        "whiteid",
        "blackid",
        "generation",
        "fen",
        "draw",
        "status",
        "termination",
        "version",
        "wname",
        "bname",
        "createdat",
        "updatedat",
    ]


def test_moves_columns():
    assert [c.name for c in schema.moves.columns] == [
        "groupid",
        "whiteid",
        "blackid",
        "generation",
        "ply",
        "san",
        "positionkey",
    ]


def test_nullability_matches_the_original_schema():
    assert schema.games.c.fen.nullable is False
    assert schema.games.c.status.nullable is False
    assert schema.games.c.version.nullable is False
    assert schema.games.c.draw.nullable is True
    assert schema.games.c.termination.nullable is True
    assert schema.moves.c.positionkey.nullable is False
    assert schema.moves.c.san.nullable is True


def test_check_constraints_are_present(dialect):
    text = ddl(schema.games, dialect)
    assert "CHECK (draw IN (0, 1))" in text
    assert "CHECK (status BETWEEN 0 AND 3)" in text


def test_integer_defaults_are_unquoted(dialect):
    """`server_default="1"` would emit DEFAULT '1'; text("1") reproduces the original."""
    text = ddl(schema.games, dialect)
    assert "DEFAULT 1" in text
    assert "DEFAULT '1'" not in text


def test_indexes_match_the_original_schema():
    names = {ix.name for table in schema.TABLES for ix in table.indexes}
    assert names == {
        "idx_games_group_id",
        "idx_games_player_ids",
        "idx_moves_game",
        "idx_challenges_group_id",
        "idx_challenges_player_ids",
    }


def test_indexes_compile_on_both_dialects(dialect):
    for table in schema.TABLES:
        for index in table.indexes:
            assert "CREATE INDEX" in str(CreateIndex(index).compile(dialect=DIALECTS[dialect]))


def test_no_foreign_keys():
    """groupid is a discriminator, not a reference; cleanup is explicit in operations."""
    for table in schema.TABLES:
        assert not table.foreign_keys


# --- Per-dialect type rendering --------------------------------------------


def test_timestamps_render_per_dialect():
    pg = ddl(schema.games, "postgresql")
    assert "TIMESTAMP WITHOUT TIME ZONE DEFAULT now()" in pg  # same as the old TIMESTAMP DEFAULT NOW()
    assert "DATETIME DEFAULT CURRENT_TIMESTAMP" in ddl(schema.games, "sqlite")


def test_updatedat_has_an_onupdate_replacing_the_trigger():
    """SQLite has no equivalent of the PL/pgSQL BEFORE UPDATE trigger this replaces."""
    assert schema.games.c.updatedat.onupdate is not None
    assert schema.games.c.createdat.onupdate is None
