"""
The chesssnake database schema, as SQLAlchemy table definitions.

This is the single source of truth for the schema on every backend: the same
definitions emit PostgreSQL DDL and SQLite DDL, and
``metadata.create_all(engine, checkfirst=True)`` replaces the hand-written
``init.sql`` that used to ship as package data.

**Every identifier here is lowercase, deliberately.** The original schema was
created with unquoted mixed-case names (``GroupId``), which PostgreSQL folds to
lowercase, so deployed databases have ``groupid`` columns. SQLAlchemy *quotes*
any name that is not already lowercase, and ``games."GroupId"`` would not match
``games.groupid`` — every query against an existing database would fail. Writing
the names lowercase keeps them unquoted, so this schema is byte-compatible with
databases created by the old script, and result-row keys come out lowercase on
both backends (which is what :class:`chesssnake.dto.GameState` already expects).

A triple ``(groupid, whiteid, blackid)`` can own many games, one per
``generation``: the current game is the row with the highest generation, and
earlier ones are the read-only archive. There are deliberately no foreign keys —
``groupid`` is a discriminator, not a reference — and rows are cleaned up
explicitly in :mod:`chesssnake.db.operations`.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    func,
    text,
)

metadata = MetaData()

#: The board (plus turn, castling rights, en-passant target, and the move clocks)
#: is stored as a single standard FEN string; status/draw/termination/version are
#: separate columns.
games = Table(
    "games",
    metadata,
    Column("groupid", BigInteger, primary_key=True),
    Column("whiteid", BigInteger, primary_key=True),
    Column("blackid", BigInteger, primary_key=True),
    Column("generation", Integer, primary_key=True, server_default=text("1")),
    Column("fen", Text, nullable=False),
    Column("draw", Integer),
    Column("status", Integer, nullable=False),
    Column("termination", Text),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("wname", Text),
    Column("bname", Text),
    Column("createdat", DateTime, server_default=func.now()),
    # ``onupdate`` replaces the PL/pgSQL BEFORE-UPDATE trigger the old schema used,
    # which SQLite has no equivalent for. SQLAlchemy applies it to every UPDATE it
    # emits, which is all of them.
    Column("updatedat", DateTime, server_default=func.now(), onupdate=func.now()),
    CheckConstraint("draw IN (0, 1)", name="ck_games_draw"),
    CheckConstraint("status BETWEEN 0 AND 3", name="ck_games_status"),
)

#: One row per applied move (``ply >= 1``), plus a ply-0 row per game recording the
#: initial position. ``san`` is the move played; ``positionkey`` is the first four
#: FEN fields, used for threefold-repetition detection. Scoped per generation.
moves = Table(
    "moves",
    metadata,
    Column("groupid", BigInteger, primary_key=True),
    Column("whiteid", BigInteger, primary_key=True),
    Column("blackid", BigInteger, primary_key=True),
    Column("generation", Integer, primary_key=True, server_default=text("1")),
    Column("ply", Integer, primary_key=True),
    Column("san", Text),
    Column("positionkey", Text, nullable=False),
)

#: Pending challenges between two players in a group.
challenges = Table(
    "challenges",
    metadata,
    Column("groupid", BigInteger, primary_key=True),
    Column("challenger", BigInteger, primary_key=True),
    Column("challenged", BigInteger, primary_key=True),
    Column("createdat", DateTime, server_default=func.now()),
)

# The composite primary keys already index the full key tuples, so only the
# partial-key lookups that they cannot serve get their own index.
Index("idx_games_group_id", games.c.groupid)
Index("idx_games_player_ids", games.c.whiteid, games.c.blackid)
Index("idx_moves_game", moves.c.groupid, moves.c.whiteid, moves.c.blackid, moves.c.generation)
Index("idx_challenges_group_id", challenges.c.groupid)
Index("idx_challenges_player_ids", challenges.c.challenger, challenges.c.challenged)

#: Every table, in dependency order (there are no dependencies, but ordering keeps
#: teardown deterministic).
TABLES = (games, moves, challenges)


def create_all(engine) -> None:
    """
    Create any missing tables and indexes.

    Idempotent, and safe against a database created by the pre-0.9.0 ``init.sql``:
    existing tables are left exactly as they are rather than altered.

    :param engine: A SQLAlchemy engine.
    """
    metadata.create_all(engine, checkfirst=True)
