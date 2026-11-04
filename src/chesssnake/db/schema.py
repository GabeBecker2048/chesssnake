"""
The chesssnake database schema, as SQLAlchemy table definitions.

This is the single source of truth for the schema on every backend: the same
definitions emit PostgreSQL DDL and SQLite DDL through
``metadata.create_all(engine, checkfirst=True)``.

**Every identifier here is lowercase, deliberately.** SQLAlchemy quotes any name
that is not already lowercase, and PostgreSQL folds unquoted names to lowercase,
so lowercase is the one spelling that stays unquoted on both backends and makes
result-row keys identical on both (which is what :mod:`chesssnake.dto` relies on).

The shape, and the invariants :mod:`chesssnake.db.operations` keeps:

- ``users`` owns identity. Game rows reference players by ``users.id`` and never
  carry names. ``user_identities`` maps an external id (a Discord id, say) to a
  user, one row per ``(provider, external_id)``, so a person can be reached
  from any number of outside systems. ``auth_tokens`` holds the bearer tokens a
  user logs in with, as SHA-256 hashes only.
- Games are normally created by accepting a ``challenges`` row, which is deleted
  in the same transaction.
- A row in ``games`` *is* a game in progress; there is no status column. The
  moment a game ends it is moved, in the same transaction, to
  ``finished_games``, with its ``moves`` rows collapsed into one ``movetext``
  string. The hot table only ever holds in-play games, and the archive is
  append-only.
- A game keeps its ``id`` for life. ``games.id`` is declared so that neither
  backend ever reuses one (``AUTOINCREMENT`` on SQLite, an identity sequence on
  PostgreSQL), and the archived row carries the same id.
- ``group_id`` is a caller-defined namespace, not a reference: the same two
  users can have independent games in different groups. A triple
  ``(group_id, white_id, black_id)`` has at most one game in progress; its
  finished games are numbered by ``generation``.

Foreign keys are enforced on both backends: SQLite needs ``PRAGMA foreign_keys``
per connection, which :mod:`chesssnake.db.sqlite` sets. Timestamps are written
by the operations layer as UTC-aware datetimes, with no server-side defaults,
because SQLite and PostgreSQL would disagree about the time zone of ``now()``.
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

metadata = MetaData()

#: A server-assigned 64-bit id. The SQLite variant is a plain ``INTEGER`` because
#: only that spelling makes the column the table's rowid alias, which is what
#: ``AUTOINCREMENT`` attaches to; PostgreSQL gets ``BIGINT`` with an identity
#: sequence. Tables using it also pass ``sqlite_autoincrement=True``.
_ASSIGNED_ID = BigInteger().with_variant(Integer, "sqlite")


def _assigned_id():
    return Column("id", _ASSIGNED_ID, Identity(), primary_key=True)


def _user_ref(name):
    return Column(name, BigInteger, ForeignKey("users.id"), nullable=False)


def _timestamp(name, nullable=False):
    return Column(name, DateTime(timezone=True), nullable=nullable)


#: Accounts. ``password_hash`` is an Argon2id PHC string, or NULL for an account
#: that cannot log in (a bot that only uses api tokens); ``role`` is 0 for a
#: player and 1 for an administrator; a disabled user's tokens are refused.
users = Table(
    "users",
    metadata,
    _assigned_id(),
    Column("username", Text, nullable=False),
    Column("password_hash", Text),
    Column("role", SmallInteger, nullable=False, server_default=text("0")),
    _timestamp("created_at"),
    _timestamp("disabled_at", nullable=True),
    CheckConstraint("role IN (0, 1)", name="ck_users_role"),
    sqlite_autoincrement=True,
)

#: Usernames are unique ignoring case, so ``Alice`` and ``alice`` cannot both
#: exist, while the case the user typed is what is stored and shown.
Index("ix_users_username", func.lower(users.c.username), unique=True)

#: External ids. ``external_id`` is text because not every source uses numbers;
#: a Discord snowflake is stored as its decimal digits.
user_identities = Table(
    "user_identities",
    metadata,
    Column("provider", Text, primary_key=True),
    Column("external_id", Text, primary_key=True),
    Column("user_id", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    _timestamp("created_at"),
)

Index("ix_user_identities_user_id", user_identities.c.user_id)

#: Bearer tokens. ``kind`` 0 is a login session (always expires), 1 a named api
#: token for scripts and bots (expiry optional). Only ``sha256(token)`` is stored,
#: so a database dump does not hand out working credentials.
auth_tokens = Table(
    "auth_tokens",
    metadata,
    _assigned_id(),
    Column("user_id", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("kind", SmallInteger, nullable=False),
    Column("name", Text),
    Column("token_hash", Text, nullable=False, unique=True),
    _timestamp("created_at"),
    _timestamp("expires_at", nullable=True),
    CheckConstraint("kind IN (0, 1)", name="ck_auth_tokens_kind"),
    sqlite_autoincrement=True,
)

Index("ix_auth_tokens_user_id", auth_tokens.c.user_id)

#: Games in progress. The board (plus turn, castling rights, en-passant target
#: and the move clocks) is one standard FEN string; ``draw`` is the colour with
#: an open draw offer; ``version`` counts every applied change, for optimistic
#: concurrency.
games = Table(
    "games",
    metadata,
    _assigned_id(),
    Column("group_id", BigInteger, nullable=False),
    _user_ref("white_id"),
    _user_ref("black_id"),
    Column("generation", Integer, nullable=False, server_default=text("1")),
    Column("fen", Text, nullable=False),
    Column("draw", SmallInteger),
    Column("version", Integer, nullable=False, server_default=text("1")),
    _timestamp("started_at"),
    _timestamp("updated_at"),
    UniqueConstraint("group_id", "white_id", "black_id", name="uq_games_pairing"),
    CheckConstraint("draw IN (0, 1)", name="ck_games_draw"),
    sqlite_autoincrement=True,
)

# The unique constraint serves lookups by triple and by (group, white); these
# serve "games where this user plays", whichever colour, and the FK checks.
Index("ix_games_white_id", games.c.white_id)
Index("ix_games_black_id", games.c.black_id)

#: One row per applied ply of a game in progress (``ply >= 1``; the starting
#: position is not stored, the server knows it). ``san`` is the move played;
#: ``position_key`` is the first four FEN fields, for threefold repetition.
moves = Table(
    "moves",
    metadata,
    Column("game_id", BigInteger, ForeignKey("games.id", ondelete="CASCADE"), primary_key=True),
    Column("ply", SmallInteger, primary_key=True),
    Column("san", Text, nullable=False),
    Column("position_key", Text, nullable=False),
)

#: The archive. ``status`` is 1 white won, 2 black won, 3 draw; ``termination``
#: says why; ``movetext`` is the game's SAN tokens separated by spaces, the same
#: tokens ``moves.san`` held; ``fen`` is the final position, kept so that
#: reading or rendering an old game needs no replay.
finished_games = Table(
    "finished_games",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("group_id", BigInteger, nullable=False),
    _user_ref("white_id"),
    _user_ref("black_id"),
    Column("generation", Integer, nullable=False),
    Column("status", SmallInteger, nullable=False),
    Column("termination", Text, nullable=False),
    Column("movetext", Text, nullable=False),
    Column("fen", Text, nullable=False),
    Column("version", Integer, nullable=False),
    _timestamp("started_at"),
    _timestamp("finished_at"),
    UniqueConstraint("group_id", "white_id", "black_id", "generation", name="uq_finished_games_pairing"),
    CheckConstraint("status IN (1, 2, 3)", name="ck_finished_games_status"),
)

Index("ix_finished_games_white_id", finished_games.c.white_id)
Index("ix_finished_games_black_id", finished_games.c.black_id)

#: Pending challenges. ``color`` is the colour the challenger asked for: 0 white,
#: 1 black, 2 random (decided when it is accepted). Accepting deletes the row and
#: creates the game in one transaction; declining or withdrawing deletes it.
challenges = Table(
    "challenges",
    metadata,
    _assigned_id(),
    Column("group_id", BigInteger, nullable=False),
    Column("challenger_id", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("challenged_id", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("color", SmallInteger, nullable=False, server_default=text("2")),
    _timestamp("created_at"),
    UniqueConstraint("group_id", "challenger_id", "challenged_id", name="uq_challenges_pairing"),
    CheckConstraint("color IN (0, 1, 2)", name="ck_challenges_color"),
    sqlite_autoincrement=True,
)

Index("ix_challenges_challenger_id", challenges.c.challenger_id)
Index("ix_challenges_challenged_id", challenges.c.challenged_id)

#: Per-user settings, one row per user who has changed one (no row: all defaults).
#: ``settings`` is a JSON object of the values the user has set; the operations
#: layer validates names and types and fills in the defaults on read. One JSON column rather than a column per setting
#: so that adding a setting is not a schema change: before 1.0 there are no
#: migrations, and a changed table makes the server refuse an existing database.
user_settings = Table(
    "user_settings",
    metadata,
    Column("user_id", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("settings", Text, nullable=False),
    _timestamp("updated_at"),
)

#: Every table, in dependency order: a table only references tables before it.
#: Delete in reverse to empty a database without tripping a foreign key.
TABLES = (users, user_identities, user_settings, auth_tokens, games, moves, finished_games, challenges)


def create_all(engine) -> None:
    """
    Create any missing tables and indexes.

    Idempotent: existing tables are left exactly as they are rather than
    altered, so a database from an older schema has to be dropped first (see
    :func:`drop_all`, or ``chesssnake init-db --drop``).

    :param engine: A SQLAlchemy engine.
    """
    metadata.create_all(engine, checkfirst=True)


def stale_tables(engine) -> list[str]:
    """
    Name every existing chesssnake table whose columns differ from this schema.

    :func:`create_all` never alters a table, so a database created by an older
    chesssnake keeps its old shape and would fail at the first query that touches
    a changed table. The api-endpoint checks this at startup and refuses to run,
    rather than half-working. Tables that do not exist yet are not stale: they are
    simply created.

    :param engine: A SQLAlchemy engine.
    :return: The names of mismatched tables, empty when the database is current.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    stale = []
    for table in TABLES:
        if table.name in existing:
            columns = {column["name"] for column in inspector.get_columns(table.name)}
            if columns != {column.name for column in table.columns}:
                stale.append(table.name)
    return stale


def missing_tables(engine) -> list[str]:
    """
    Name the chesssnake tables an existing chesssnake database does not have yet.

    A release can add a table (0.14.0 added ``user_settings``); unlike a changed
    one, that needs no reset, only :func:`create_all` (``chesssnake init-db``),
    which leaves every existing table and row alone. Empty for a database with no
    chesssnake tables at all: that is a new database, not an old one.

    :param engine: A SQLAlchemy engine.
    :return: The names of the tables to create.
    """
    from sqlalchemy import inspect

    existing = set(inspect(engine).get_table_names())
    if not existing & {table.name for table in TABLES}:
        return []
    return [table.name for table in TABLES if table.name not in existing]


def drop_all(engine) -> None:
    """
    Drop every chesssnake table, in dependency order. Everything in them is lost.

    :param engine: A SQLAlchemy engine.
    """
    metadata.drop_all(engine, checkfirst=True)
