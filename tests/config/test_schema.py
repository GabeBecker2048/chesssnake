"""
Tests for the SQLAlchemy schema definitions.

These pin the DDL each backend receives, because several properties of the
schema are invisible until they fail in production: a mixed-case identifier
gets quoted, an id column that is not exactly ``INTEGER PRIMARY KEY
AUTOINCREMENT`` on SQLite reuses ids, a ``FOR UPDATE`` without ``OF`` locks the
users rows a game joins. They need SQLAlchemy but no database, so they live
here rather than in ``tests/integration``.
"""

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from chesssnake.db import schema

DIALECTS = {"postgresql": postgresql.dialect(), "sqlite": sqlite.dialect()}


def ddl(table, dialect):
    return str(CreateTable(table).compile(dialect=DIALECTS[dialect]))


def all_indexes():
    return {ix.name: ix for table in schema.TABLES for ix in table.indexes}


@pytest.fixture(params=sorted(DIALECTS))
def dialect(request):
    return request.param


# --- The lowercase convention ----------------------------------------------


def test_every_identifier_is_lowercase():
    """Mixed case would be quoted, so the same name would differ between backends."""
    for table in schema.TABLES:
        assert table.name == table.name.lower(), f"table {table.name} is not lowercase"
        for column in table.columns:
            assert column.name == column.name.lower(), f"{table.name}.{column.name} is not lowercase"
    for name in all_indexes():
        assert name == name.lower()


def test_identifiers_are_emitted_unquoted(dialect):
    for table in schema.TABLES:
        assert '"' not in ddl(table, dialect), f"{table.name} DDL quotes an identifier on {dialect}"


# --- Shape -----------------------------------------------------------------


def test_tables_are_listed_in_dependency_order():
    """Teardown deletes in reverse, so a table must come after everything it references."""
    names = [t.name for t in schema.TABLES]
    assert names == ["users", "user_identities", "auth_tokens", "games", "moves", "finished_games", "challenges"]
    for position, table in enumerate(schema.TABLES):
        for fk in table.foreign_keys:
            assert names.index(fk.column.table.name) < position


@pytest.mark.parametrize(
    "table,expected",
    [
        ("users", ["id"]),
        ("user_identities", ["provider", "external_id"]),
        ("auth_tokens", ["id"]),
        ("games", ["id"]),
        ("moves", ["game_id", "ply"]),
        ("finished_games", ["id"]),
        ("challenges", ["id"]),
    ],
)
def test_primary_keys(table, expected):
    assert [c.name for c in schema.metadata.tables[table].primary_key.columns] == expected


def test_users_columns():
    assert [c.name for c in schema.users.columns] == [
        "id",
        "username",
        "password_hash",
        "role",
        "created_at",
        "disabled_at",
    ]


def test_games_hold_no_outcome_and_no_names():
    """A row in games is a game in progress; names live on users."""
    names = [c.name for c in schema.games.columns]
    assert names == [
        "id",
        "group_id",
        "white_id",
        "black_id",
        "generation",
        "fen",
        "draw",
        "version",
        "started_at",
        "updated_at",
    ]


def test_finished_games_columns():
    assert [c.name for c in schema.finished_games.columns] == [
        "id",
        "group_id",
        "white_id",
        "black_id",
        "generation",
        "status",
        "termination",
        "movetext",
        "fen",
        "version",
        "started_at",
        "finished_at",
    ]


def test_moves_columns():
    assert [c.name for c in schema.moves.columns] == ["game_id", "ply", "san", "position_key"]
    assert schema.moves.c.san.nullable is False, "there is no ply-0 row with a NULL move any more"


def test_one_game_in_progress_per_triple():
    (unique,) = [c for c in schema.games.constraints if c.name == "uq_games_pairing"]
    assert [c.name for c in unique.columns] == ["group_id", "white_id", "black_id"]
    (archived,) = [c for c in schema.finished_games.constraints if c.name == "uq_finished_games_pairing"]
    assert [c.name for c in archived.columns] == ["group_id", "white_id", "black_id", "generation"]


def test_foreign_keys():
    def targets(table):
        return {(fk.parent.name, fk.column.table.name, fk.ondelete) for fk in table.foreign_keys}

    assert targets(schema.user_identities) == {("user_id", "users", "CASCADE")}
    assert targets(schema.games) == {("white_id", "users", None), ("black_id", "users", None)}
    assert targets(schema.moves) == {("game_id", "games", "CASCADE")}
    assert targets(schema.finished_games) == {("white_id", "users", None), ("black_id", "users", None)}
    assert targets(schema.challenges) == {("challenger_id", "users", "CASCADE"), ("challenged_id", "users", "CASCADE")}
    assert targets(schema.auth_tokens) == {("user_id", "users", "CASCADE")}


def test_auth_tokens_store_only_a_unique_hash():
    columns = [c.name for c in schema.auth_tokens.columns]
    assert columns == ["id", "user_id", "kind", "name", "token_hash", "created_at", "expires_at"]
    assert schema.auth_tokens.c.token_hash.unique and not schema.auth_tokens.c.token_hash.nullable
    assert "token" not in columns, "the raw token must never have a column"


def test_challenges_columns_and_one_per_direction():
    assert [c.name for c in schema.challenges.columns] == [
        "id",
        "group_id",
        "challenger_id",
        "challenged_id",
        "color",
        "created_at",
    ]
    (unique,) = [c for c in schema.challenges.constraints if c.name == "uq_challenges_pairing"]
    assert [c.name for c in unique.columns] == ["group_id", "challenger_id", "challenged_id"]


def test_check_constraints_are_present(dialect):
    assert "CHECK (role IN (0, 1))" in ddl(schema.users, dialect)
    assert "CHECK (draw IN (0, 1))" in ddl(schema.games, dialect)
    assert "CHECK (status IN (1, 2, 3))" in ddl(schema.finished_games, dialect)
    assert "CHECK (kind IN (0, 1))" in ddl(schema.auth_tokens, dialect)
    assert "CHECK (color IN (0, 1, 2))" in ddl(schema.challenges, dialect)


def test_integer_defaults_are_unquoted(dialect):
    """`server_default="1"` would emit DEFAULT '1'."""
    text = ddl(schema.games, dialect)
    assert "DEFAULT 1" in text
    assert "DEFAULT '1'" not in text


# --- Ids -------------------------------------------------------------------


@pytest.mark.parametrize("table", [schema.users, schema.games, schema.auth_tokens, schema.challenges])
def test_assigned_ids_are_never_reused_on_sqlite(table):
    """
    Only exactly ``INTEGER ... PRIMARY KEY AUTOINCREMENT`` does it: BIGINT is not a
    rowid alias, and without AUTOINCREMENT SQLite reuses the highest id once that
    row is deleted, as archiving a game does.
    """
    assert "id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT" in ddl(table, "sqlite")


@pytest.mark.parametrize("table", [schema.users, schema.games, schema.auth_tokens, schema.challenges])
def test_assigned_ids_use_an_identity_on_postgresql(table):
    assert "id BIGINT GENERATED BY DEFAULT AS IDENTITY" in ddl(table, "postgresql")


def test_archived_ids_are_carried_over_not_assigned(dialect):
    text = ddl(schema.finished_games, dialect)
    assert "AUTOINCREMENT" not in text and "IDENTITY" not in text and "SERIAL" not in text


# --- Indexes ---------------------------------------------------------------


def test_indexes():
    assert set(all_indexes()) == {
        "ix_users_username",
        "ix_user_identities_user_id",
        "ix_games_white_id",
        "ix_games_black_id",
        "ix_finished_games_white_id",
        "ix_finished_games_black_id",
        "ix_auth_tokens_user_id",
        "ix_challenges_challenger_id",
        "ix_challenges_challenged_id",
    }


def test_usernames_are_unique_ignoring_case(dialect):
    index = all_indexes()["ix_users_username"]
    assert index.unique
    compiled = str(CreateIndex(index).compile(dialect=DIALECTS[dialect]))
    assert compiled == "CREATE UNIQUE INDEX ix_users_username ON users (lower(username))"


def test_indexes_compile_on_both_dialects(dialect):
    for index in all_indexes().values():
        assert "INDEX" in str(CreateIndex(index).compile(dialect=DIALECTS[dialect]))


# --- Timestamps ------------------------------------------------------------


def test_timestamps_render_per_dialect():
    assert "started_at TIMESTAMP WITH TIME ZONE NOT NULL" in ddl(schema.games, "postgresql")
    assert "started_at DATETIME NOT NULL" in ddl(schema.games, "sqlite")


def test_timestamps_are_written_by_the_application():
    """
    No server defaults and no onupdate: the operations layer writes every timestamp
    as UTC, because SQLite and PostgreSQL disagree about the zone of now().
    """
    for table in schema.TABLES:
        for column in table.columns:
            if column.name.endswith("_at"):
                assert column.server_default is None, f"{table.name}.{column.name}"
                assert column.onupdate is None, f"{table.name}.{column.name}"


# --- Locking ---------------------------------------------------------------


def test_the_game_lock_does_not_lock_the_players():
    """
    The active-game read joins users twice for the names. A bare FOR UPDATE would
    lock both users rows and serialize every game either player is in.
    """
    from chesssnake.db.operations import _active_query

    stmt = _active_query().with_for_update(of=schema.games)
    compiled = str(stmt.compile(dialect=DIALECTS["postgresql"]))
    assert compiled.endswith("FOR UPDATE OF games")


def test_drop_all_exists():
    assert callable(schema.drop_all)


def test_stale_tables_finds_an_old_shape(tmp_path):
    from sqlalchemy import create_engine, text

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    try:
        assert schema.stale_tables(engine) == [], "an empty database is not stale"
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE challenges (group_id BIGINT, challenger BIGINT, challenged BIGINT)"))
        assert schema.stale_tables(engine) == ["challenges"]
        schema.drop_all(engine)
        schema.create_all(engine)
        assert schema.stale_tables(engine) == []
    finally:
        engine.dispose()


def test_the_pair_lock_is_keyed_on_the_unordered_pair():
    """A->B and B->A must take the same lock, or crossing challenges both get through."""
    from unittest import mock

    from chesssnake.db import engine as db_engine
    from chesssnake.db import postgres

    seen = []
    conn = mock.Mock()
    conn.execute.side_effect = lambda _stmt, params: seen.append(params["pair"])
    token = db_engine.WRITE_TRANSACTION.set(True)
    try:
        postgres.lock_pair(conn, 5, 2, 9)
        postgres.lock_pair(conn, 5, 9, 2)
        postgres.lock_pair(conn, 6, 2, 9)
    finally:
        db_engine.WRITE_TRANSACTION.reset(token)
    assert seen[0] == seen[1] != seen[2]
