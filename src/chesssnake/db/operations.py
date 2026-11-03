"""
Database operations for the chesssnake API, backend-agnostic.

These are the queries that back the REST API, written as SQLAlchemy Core
expressions so one definition compiles correctly for both PostgreSQL and SQLite.
They deal only in primitive values (ints, strings, dicts, datetimes): the chess
engine runs on the server, and **nothing here imports it**. Engine-derived
values like the initial FEN are passed in, and the engine logic itself arrives
as the ``mutate`` callback of :func:`apply_game_change`, which returns a
:class:`GameChange` describing what to persist.

Every read of a game returns the same dict, whether the game is in progress or
archived: ``id, group_id, white_id, black_id, generation, fen, status, draw,
termination, version, white_name, black_name, started_at, updated_at`` (see
:func:`_game_dict`). Names are joined in from ``users``; timestamps are
UTC-aware datetimes on both backends.

Each public function opens its own transaction. The private ``_`` variants take a
connection instead, so a caller that needs several operations to be atomic, as
:func:`challenge` does, can run them together. Any function that reads and then
writes based on what it read uses :func:`~chesssnake.db.engine.locked_transaction`;
see that module for why a plain transaction is not safe for those on SQLite.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from . import errors
from .engine import backend, locked_transaction, transaction
from .schema import challenges, finished_games, games, moves, user_identities, users

#: PostgreSQL BIGINT bounds. SQLite's INTEGER is also a signed 64-bit value, so
#: the same range applies to both backends.
_BIGINT_MIN = -9223372036854775808
_BIGINT_MAX = 9223372036854775807

#: Role codes, as stored. :mod:`chesssnake.dto` maps them to names for the wire.
ROLE_USER = 0
ROLE_ADMIN = 1


def validate_ids(*ids: int) -> None:
    """
    Validate that all provided ids are integers within the 64-bit signed range.

    :param ids: The ids to check (user ids, group ids, game ids).
    :raises errors.SQLIdError: If any id is not an int or is out of range.
    """
    for id_ in ids:
        if not isinstance(id_, int) or isinstance(id_, bool):
            raise errors.SQLIdError(id_)
        if not (_BIGINT_MIN <= id_ <= _BIGINT_MAX):
            raise errors.SQLIdError(id_)


def validate_username(username) -> str:
    """
    Check a username against :data:`chesssnake.db.errors.USERNAME_RE`.

    :return: The username, unchanged.
    :raises errors.UserValidationError: If it does not fit the rule.
    """
    if not isinstance(username, str) or not errors.USERNAME_RE.match(username):
        raise errors.UserValidationError(f"Invalid username {username!r}: {errors.USERNAME_RULE}")
    return username


def _validate_identity(provider, external_id) -> None:
    if not isinstance(provider, str) or not errors.PROVIDER_RE.match(provider):
        raise errors.UserValidationError(
            f"Invalid provider {provider!r}: 1 to 32 lowercase letters, digits, '_' and '-' only"
        )
    if not isinstance(external_id, str) or not errors.EXTERNAL_ID_RE.match(external_id):
        raise errors.UserValidationError(f"Invalid external id {external_id!r}: 1 to 128 characters, no whitespace")


def _validate_role(role) -> None:
    if role not in (ROLE_USER, ROLE_ADMIN) or isinstance(role, bool):
        raise errors.UserValidationError(f"Invalid role {role!r}: 0 (user) or 1 (admin)")


def _utcnow() -> datetime:
    """The timestamp every write uses: UTC-aware, so both backends store the same instant."""
    return datetime.now(UTC)


def _as_utc(value):
    """
    Normalise a stored timestamp to a UTC-aware datetime.

    SQLite has no time zone type: SQLAlchemy stores the wall-clock text and hands
    back a naive datetime, which is UTC because :func:`_utcnow` is the only thing
    that ever writes one. PostgreSQL returns an aware value in the session's zone.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _triple(table, group_id, white_id, black_id):
    """The WHERE clause matching one ``(group, white, black)`` triple."""
    return (table.c.group_id == group_id) & (table.c.white_id == white_id) & (table.c.black_id == black_id)


def _either_pairing(table, player1, player2):
    """The WHERE clause matching the two players in either colour arrangement."""
    return ((table.c.white_id == player1) & (table.c.black_id == player2)) | (
        (table.c.white_id == player2) & (table.c.black_id == player1)
    )


# --- Initialization --------------------------------------------------------


def db_init(url, create_database=False, **engine_kwargs):
    """
    Initialize the database environment: optionally create the database, create the
    engine, and create the schema.

    :param url: The database URL.
    :param create_database: Whether to create the database if it is missing.
    :raises errors.GameError: If any step of initialization fails.
    """
    from . import engine as engine_module
    from . import schema

    try:
        if create_database:
            parsed = engine_module.parse_url(url)
            print(engine_module.backend_module(parsed.get_backend_name()).create_database(parsed))
        eng = engine_module.initialize_engine(url, **engine_kwargs)
        schema.create_all(eng)
        print("Database initialized successfully.")
    except errors.GameError:
        # Already a well-formed persistence error (e.g. SQLAuthError, whose message
        # explains exactly how to configure the URL); don't flatten its type.
        raise
    except Exception as e:
        raise errors.GameError(f"Database initialization error:\n{str(e)}")


# --- Users -----------------------------------------------------------------

#: Everything about a user that may leave this layer. ``password_hash`` never does.
_USER_COLUMNS = (users.c.id, users.c.username, users.c.role, users.c.created_at, users.c.disabled_at)


def _user_dict(row, identities=()):
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "role": int(row["role"]),
        "created_at": _as_utc(row["created_at"]),
        "disabled_at": _as_utc(row["disabled_at"]),
        "identities": [dict(identity) for identity in identities],
    }


def _user_by_id(conn, user_id):
    return conn.execute(select(*_USER_COLUMNS).where(users.c.id == user_id)).mappings().first()


def _user_by_name(conn, username):
    # lower() on both sides is the expression the unique index is built on, so
    # this lookup uses that index rather than scanning.
    stmt = select(*_USER_COLUMNS).where(func.lower(users.c.username) == username.lower())
    return conn.execute(stmt).mappings().first()


def _user_by_identity(conn, provider, external_id):
    stmt = (
        select(*_USER_COLUMNS)
        .select_from(user_identities.join(users, user_identities.c.user_id == users.c.id))
        .where((user_identities.c.provider == provider) & (user_identities.c.external_id == external_id))
    )
    return conn.execute(stmt).mappings().first()


def _identities_of(conn, user_id):
    stmt = (
        select(user_identities.c.provider, user_identities.c.external_id)
        .where(user_identities.c.user_id == user_id)
        .order_by(user_identities.c.provider, user_identities.c.external_id)
    )
    return [{"provider": r["provider"], "external_id": r["external_id"]} for r in conn.execute(stmt).mappings()]


def _load_user(conn, row):
    """A user row as the public dict, with its identities; ``None`` stays ``None``."""
    if row is None:
        return None
    return _user_dict(row, _identities_of(conn, int(row["id"])))


def _require_user(conn, user_id):
    row = _user_by_id(conn, user_id)
    if row is None:
        raise errors.UserNotFoundError(f"No user with id {user_id}")
    return row


def _require_users(conn, *ids):
    """Raise :class:`errors.UserNotFoundError` naming every id that is not a user."""
    wanted = set(ids)
    found = {int(found_id) for found_id in conn.execute(select(users.c.id).where(users.c.id.in_(wanted))).scalars()}
    missing = sorted(wanted - found)
    if missing:
        raise errors.UserNotFoundError("No user with id " + ", ".join(str(id_) for id_ in missing))


def _insert_user(conn, username, role, now):
    """
    Create a user inside a locked transaction and return its dict.

    The pre-check gives a precise message for the common case. It is not enough
    on PostgreSQL, where two transactions can both pass it before either commits,
    so the unique index on ``lower(username)`` is the real guarantee and its
    failure is reported the same way.
    """
    if _user_by_name(conn, username) is not None:
        raise errors.UserExistsError(f"The username {username!r} is already taken")
    try:
        result = conn.execute(users.insert().values(username=username, role=role, created_at=now))
    except IntegrityError as e:
        raise errors.UserExistsError(f"The username {username!r} is already taken") from e
    return {
        "id": int(result.inserted_primary_key[0]),
        "username": username,
        "role": role,
        "created_at": now,
        "disabled_at": None,
        "identities": [],
    }


def user_create(username, role=ROLE_USER):
    """
    Create a user with a server-assigned id.

    :param username: Must satisfy :data:`chesssnake.db.errors.USERNAME_RE`; unique ignoring case.
    :param role: 0 for a player (default), 1 for an administrator.
    :return: The user dict (``id, username, role, created_at, disabled_at, identities``).
    :raises errors.UserValidationError: On a malformed username or role.
    :raises errors.UserExistsError: If the username is taken.
    """
    validate_username(username)
    _validate_role(role)
    with locked_transaction() as conn:
        return _insert_user(conn, username, role, _utcnow())


def user_get(user_id):
    """Return the user dict for an id, or ``None``."""
    validate_ids(user_id)
    with transaction() as conn:
        return _load_user(conn, _user_by_id(conn, user_id))


def user_get_by_name(username):
    """Return the user dict for a username (matched ignoring case), or ``None``."""
    if not isinstance(username, str) or not username:
        raise errors.UserValidationError("A username is required")
    with transaction() as conn:
        return _load_user(conn, _user_by_name(conn, username))


def user_rename(user_id, username):
    """
    Change a user's username.

    :raises errors.UserNotFoundError: If there is no such user.
    :raises errors.UserValidationError: On a malformed username.
    :raises errors.UserExistsError: If another user has that name (ignoring case).
    """
    validate_ids(user_id)
    validate_username(username)
    with locked_transaction() as conn:
        _require_user(conn, user_id)
        other = _user_by_name(conn, username)
        if other is not None and int(other["id"]) != user_id:
            raise errors.UserExistsError(f"The username {username!r} is already taken")
        conn.execute(update(users).where(users.c.id == user_id).values(username=username))
        return _load_user(conn, _user_by_id(conn, user_id))


def user_set_role(user_id, role):
    """
    Make a user an administrator (``role=1``) or a plain player (``role=0``).

    :raises errors.UserNotFoundError: If there is no such user.
    :raises errors.UserValidationError: On an unknown role.
    """
    validate_ids(user_id)
    _validate_role(role)
    with transaction() as conn:
        # Write first, then read: no read-modify-write, so no lock is needed.
        if conn.execute(update(users).where(users.c.id == user_id).values(role=role)).rowcount == 0:
            raise errors.UserNotFoundError(f"No user with id {user_id}")
        return _load_user(conn, _user_by_id(conn, user_id))


def identity_get(provider, external_id):
    """Return the user dict linked to an external id, or ``None``."""
    _validate_identity(provider, external_id)
    with transaction() as conn:
        return _load_user(conn, _user_by_identity(conn, provider, external_id))


def identity_link(user_id, provider, external_id):
    """
    Link an external id to an existing user. Linking it again to the same user is a no-op.

    :return: The user dict, identities included.
    :raises errors.UserNotFoundError: If there is no such user.
    :raises errors.UserValidationError: On a malformed provider or external id.
    :raises errors.UserExistsError: If the external id is linked to another user.
    """
    validate_ids(user_id)
    _validate_identity(provider, external_id)
    with locked_transaction() as conn:
        _require_user(conn, user_id)
        owner = _user_by_identity(conn, provider, external_id)
        if owner is not None:
            if int(owner["id"]) == user_id:
                return _load_user(conn, owner)
            raise errors.UserExistsError(f"{provider} id {external_id!r} is already linked to user {owner['id']}")
        conn.execute(
            user_identities.insert().values(
                provider=provider, external_id=external_id, user_id=user_id, created_at=_utcnow()
            )
        )
        return _load_user(conn, _user_by_id(conn, user_id))


def user_get_or_create_by_identity(provider, external_id, username):
    """
    Return the user linked to an external id, creating user and link if there is none.

    This is the one call an integration (a Discord bot, say) needs per
    interaction: idempotent, and the ``username`` is only used when the user is
    created. An existing user is returned as is, whatever name was passed.

    :raises errors.UserValidationError: On a malformed provider, external id or username.
    :raises errors.UserExistsError: If the user had to be created and the username is taken.
    """
    _validate_identity(provider, external_id)
    validate_username(username)
    with locked_transaction() as conn:
        existing = _user_by_identity(conn, provider, external_id)
        if existing is not None:
            return _load_user(conn, existing)
        now = _utcnow()
        user = _insert_user(conn, username, ROLE_USER, now)
        try:
            conn.execute(
                user_identities.insert().values(
                    provider=provider, external_id=external_id, user_id=user["id"], created_at=now
                )
            )
        except IntegrityError as e:
            # Only reachable on PostgreSQL, when another transaction linked the
            # same external id between the lookup above and this insert.
            raise errors.UserExistsError(f"{provider} id {external_id!r} was linked concurrently; retry") from e
        user["identities"] = [{"provider": provider, "external_id": external_id}]
        return user


# --- Games -----------------------------------------------------------------

# The two joins that put the players' names on every game read.
_white = users.alias("w")
_black = users.alias("b")


def _joined(table):
    return table.join(_white, table.c.white_id == _white.c.id).join(_black, table.c.black_id == _black.c.id)


def _shared_columns(table):
    return (
        table.c.id,
        table.c.group_id,
        table.c.white_id,
        table.c.black_id,
        table.c.generation,
        table.c.fen,
        table.c.version,
        table.c.started_at,
        _white.c.username.label("white_name"),
        _black.c.username.label("black_name"),
    )


def _active_query():
    """Games in progress, with names. Add ``.where(...)`` to pick one or some."""
    return select(*_shared_columns(games), games.c.draw, games.c.updated_at).select_from(_joined(games))


def _finished_query():
    """Archived games, with names, newest generation first."""
    return (
        select(
            *_shared_columns(finished_games),
            finished_games.c.status,
            finished_games.c.termination,
            finished_games.c.finished_at,
        )
        .select_from(_joined(finished_games))
        .order_by(finished_games.c.generation.desc())
    )


def _game_dict(row, finished):
    """The uniform game dict (see the module docstring) from an active or archived row."""
    if row is None:
        return None
    game = {
        "id": int(row["id"]),
        "group_id": int(row["group_id"]),
        "white_id": int(row["white_id"]),
        "black_id": int(row["black_id"]),
        "generation": int(row["generation"]),
        "fen": row["fen"],
        "version": int(row["version"]),
        "white_name": row["white_name"],
        "black_name": row["black_name"],
        "started_at": _as_utc(row["started_at"]),
    }
    if finished:
        game.update(
            status=int(row["status"]),
            draw=None,
            termination=row["termination"],
            updated_at=_as_utc(row["finished_at"]),
        )
    else:
        game.update(
            status=0,
            draw=int(row["draw"]) if row["draw"] is not None else None,
            termination=None,
            updated_at=_as_utc(row["updated_at"]),
        )
    return game


def _active_for_triple(conn, group_id, white_id, black_id):
    return conn.execute(_active_query().where(_triple(games, group_id, white_id, black_id))).mappings().first()


def game_get_or_create(group_id, white_id, black_id, initial_fen):
    """
    Load the game in progress for ``(group_id, white_id, black_id)``, or start one.

    A new game's ``generation`` is one more than the number of finished games
    between the triple, so past games keep their numbering. The engine-derived
    ``initial_fen`` is passed in so this layer stays engine-free.

    :return: The game dict.
    :raises errors.SQLIdError: On an invalid id, or when both sides are the same user.
    :raises errors.UserNotFoundError: If either player does not exist.
    """
    validate_ids(white_id, black_id, group_id)
    if white_id == black_id:
        raise errors.SQLIdError(white_id, "White and black must be different users.")
    insert = backend().insert

    # locked_transaction, not transaction: this reads the archive and then writes
    # based on what it read, so it is a read-modify-write like apply_game_change.
    # Under a plain (deferred) BEGIN, SQLite starts this as a reader and has to
    # upgrade to a writer for the INSERT; if another writer holds the lock,
    # SQLite fails that upgrade with SQLITE_BUSY *immediately*, because
    # busy_timeout does not apply to the upgrade path. The result was a 500
    # "database is locked" from POST /v1/games whenever a move was in flight.
    # Taking the write lock up front removes the upgrade entirely. On PostgreSQL
    # this only sets the WRITE_TRANSACTION flag; no FOR UPDATE is issued here.
    with locked_transaction() as conn:
        row = _active_for_triple(conn, group_id, white_id, black_id)
        if row is None:
            _require_users(conn, white_id, black_id)
            now = _utcnow()
            latest = conn.execute(
                select(func.max(finished_games.c.generation)).where(
                    _triple(finished_games, group_id, white_id, black_id)
                )
            ).scalar()
            # ON CONFLICT DO NOTHING makes this race-safe: a concurrent creator may
            # have inserted first, and the re-select below is what settles which
            # row we return.
            conn.execute(
                insert(games)
                .values(
                    group_id=group_id,
                    white_id=white_id,
                    black_id=black_id,
                    generation=int(latest or 0) + 1,
                    fen=initial_fen,
                    draw=None,
                    version=1,
                    started_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(index_elements=["group_id", "white_id", "black_id"])
            )
            row = _active_for_triple(conn, group_id, white_id, black_id)
        return _game_dict(row, finished=False)


def game_get(group_id, white_id, black_id, generation=None):
    """
    Return the game dict for a triple, or ``None``.

    With ``generation`` omitted this is the game in progress, or, when there is
    none, the most recently finished one (so a client can still show how the
    last game ended). With a generation it is that game, wherever it lives.
    """
    validate_ids(white_id, black_id, group_id)
    with transaction() as conn:
        row = _active_for_triple(conn, group_id, white_id, black_id)
        if row is not None and (generation is None or int(row["generation"]) == int(generation)):
            return _game_dict(row, finished=False)
        stmt = _finished_query().where(_triple(finished_games, group_id, white_id, black_id))
        if generation is not None:
            stmt = stmt.where(finished_games.c.generation == generation)
        return _game_dict(conn.execute(stmt.limit(1)).mappings().first(), finished=True)


def game_get_by_id(game_id):
    """Return the game dict for a game id, in progress or archived, or ``None``."""
    validate_ids(game_id)
    with transaction() as conn:
        row = conn.execute(_active_query().where(games.c.id == game_id)).mappings().first()
        if row is not None:
            return _game_dict(row, finished=False)
        row = conn.execute(_finished_query().where(finished_games.c.id == game_id)).mappings().first()
        return _game_dict(row, finished=True)


def game_archive(group_id, white_id, black_id):
    """Return every game between a triple as dicts, oldest first, the one in progress last."""
    validate_ids(white_id, black_id, group_id)
    with transaction() as conn:
        stmt = (
            _finished_query()
            .where(_triple(finished_games, group_id, white_id, black_id))
            .order_by(None)
            .order_by(finished_games.c.generation)
        )
        archive = [_game_dict(r, finished=True) for r in conn.execute(stmt).mappings()]
        active = _active_for_triple(conn, group_id, white_id, black_id)
        if active is not None:
            archive.append(_game_dict(active, finished=False))
    return archive


def game_history(game_id):
    """Return the moves of a game, in progress or archived, as ``[{"ply", "san"}]``."""
    validate_ids(game_id)
    with transaction() as conn:
        movetext = conn.execute(select(finished_games.c.movetext).where(finished_games.c.id == game_id)).scalar()
        if movetext is not None:
            sans = movetext.split()
        else:
            stmt = select(moves.c.san).where(moves.c.game_id == game_id).order_by(moves.c.ply)
            sans = list(conn.execute(stmt).scalars())
    return [{"ply": ply, "san": san} for ply, san in enumerate(sans, start=1)]


@dataclass
class GameChange:
    """
    What :func:`apply_game_change`'s ``mutate`` callback returns.

    ``new_moves`` are ``(ply, san, position_key)`` tuples to append. ``outcome``
    is ``None`` while the game continues; once it is ``(status, termination)``
    the game is finished and is moved to the archive instead of updated.
    ``result`` is handed back to the caller untouched.
    """

    fen: str
    draw: int | None
    new_moves: list[tuple[int, str, str]] = field(default_factory=list)
    result: Any = None
    outcome: tuple[int, str] | None = None


def _check_version(row, expected_version):
    if expected_version is not None and int(row["version"]) != int(expected_version):
        raise errors.VersionConflictError(
            f"Expected version {expected_version} but the game is at version {row['version']}"
        )


def _refuse_finished(conn, group_id, white_id, black_id, mutate, expected_version, expected_generation, now):
    """
    Handle an action aimed at a triple with no game in progress. Always raises.

    The targeted finished game (the latest, or ``expected_generation``) is handed
    to ``mutate`` read-only, so the engine rejects the action with the error a
    local game would give (``GameOverError``) rather than this layer inventing
    one. Archived games are immutable, so no lock is needed to read it.
    """
    stmt = _finished_query().where(_triple(finished_games, group_id, white_id, black_id))
    if expected_generation is not None:
        stmt = stmt.where(finished_games.c.generation == expected_generation)
    finished = _game_dict(conn.execute(stmt.limit(1)).mappings().first(), finished=True)
    if finished is None:
        detail = f"No game for group {group_id} between {white_id} and {black_id}"
        if expected_generation is not None:
            detail += f" (generation {expected_generation})"
        raise errors.GameNotFoundError(detail)
    _check_version(finished, expected_version)
    sans = conn.execute(select(finished_games.c.movetext).where(finished_games.c.id == finished["id"])).scalar()
    history = {"position_keys": [], "move_sans": sans.split(), "max_ply": len(sans.split())}
    mutate(finished, history, now)
    raise errors.GenerationConflictError(
        f"Game {finished['generation']} between {white_id} and {black_id} in group {group_id} is over; "
        "re-open the game to start the next one"
    )


def apply_game_change(group_id, white_id, black_id, mutate, expected_version=None, expected_generation=None):
    """
    Atomically read the game in progress (with its moves), transform it, and write it back.

    Locks the row, loads the ``moves`` history, optionally enforces
    ``expected_generation`` and ``expected_version``, calls
    ``mutate(game, history, now)``, which runs the engine, then persists the
    returned :class:`GameChange`: an UPDATE plus appended moves while the game
    continues, or, once it is over, an insert into ``finished_games`` and the
    removal of the live row and its moves. One transaction either way, so
    concurrent actions on the same game cannot clobber each other.

    How the lock is taken differs by backend and is deliberately explicit: see
    :func:`chesssnake.db.postgres.lock_current_game` (``SELECT … FOR UPDATE OF
    games``) and :func:`chesssnake.db.sqlite.lock_current_game` (already
    exclusive, because the transaction opened with ``BEGIN IMMEDIATE``).

    :param mutate: ``(game_dict, history, now) -> GameChange``, where ``history``
        is ``{"position_keys": [...], "move_sans": [...], "max_ply": int}`` for
        the plies played so far (the starting position is not included) and
        ``now`` is the UTC timestamp this change is recorded at.
    When there is no game in progress but the targeted one has finished,
    ``mutate`` is called on the *finished* game instead, so the engine refuses
    the action with its own ``GameOverError``, exactly as it would for a game
    still in memory. Should ``mutate`` not raise, nothing is written and
    :class:`~chesssnake.db.errors.GenerationConflictError` is raised: an
    archived game is never changed.

    :param expected_version: If given and stale, raise.
    :param expected_generation: If given and not the targeted game, raise.
    :return: ``GameChange.result``.
    :raises errors.GameNotFoundError: If there is no such game.
    :raises errors.GenerationConflictError: If ``expected_generation`` names a game
        that is over while a later one is in progress.
    :raises errors.VersionConflictError: If ``expected_version`` is stale.
    """
    validate_ids(white_id, black_id, group_id)
    module = backend()
    now = _utcnow()

    with locked_transaction() as conn:
        stmt = _active_query().where(_triple(games, group_id, white_id, black_id))
        row = module.lock_current_game(conn, stmt, of=games).mappings().first()
        if row is None:
            _refuse_finished(conn, group_id, white_id, black_id, mutate, expected_version, expected_generation, now)
        if expected_generation is not None and int(row["generation"]) != int(expected_generation):
            raise errors.GenerationConflictError(
                f"Generation {expected_generation} is over; the game in progress is generation {row['generation']}"
            )
        _check_version(row, expected_version)
        game_id = int(row["id"])

        move_rows = (
            conn.execute(
                select(moves.c.ply, moves.c.san, moves.c.position_key)
                .where(moves.c.game_id == game_id)
                .order_by(moves.c.ply)
            )
            .mappings()
            .all()
        )
        history = {
            "position_keys": [r["position_key"] for r in move_rows],
            "move_sans": [r["san"] for r in move_rows],
            "max_ply": max((int(r["ply"]) for r in move_rows), default=0),
        }

        change = mutate(_game_dict(row, finished=False), history, now)

        if change.outcome is None:
            conn.execute(
                update(games)
                .where(games.c.id == game_id)
                .values(fen=change.fen, draw=change.draw, version=games.c.version + 1, updated_at=now)
            )
            if change.new_moves:
                conn.execute(
                    moves.insert(),
                    [
                        {"game_id": game_id, "ply": ply, "san": san, "position_key": key}
                        for ply, san, key in change.new_moves
                    ],
                )
        else:
            status, termination = change.outcome
            conn.execute(
                finished_games.insert().values(
                    id=game_id,
                    group_id=group_id,
                    white_id=white_id,
                    black_id=black_id,
                    generation=int(row["generation"]),
                    status=status,
                    termination=termination,
                    movetext=" ".join([*history["move_sans"], *(san for _, san, _ in change.new_moves)]),
                    fen=change.fen,
                    version=int(row["version"]) + 1,
                    started_at=_as_utc(row["started_at"]),
                    finished_at=now,
                )
            )
            # Explicit rather than via the cascade: same cost, and not dependent
            # on the SQLite pragma being in force.
            conn.execute(delete(moves).where(moves.c.game_id == game_id))
            conn.execute(delete(games).where(games.c.id == game_id))
    return change.result


def game_delete(group_id, white_id, black_id, generation=None):
    """
    Delete a game and its moves.

    With ``generation`` omitted this is the game in progress, or, when there is
    none, the most recently finished one. With a generation it is that game,
    wherever it lives. Deleting is silent when there is nothing to delete.
    """
    validate_ids(white_id, black_id, group_id)

    # Resolving which game to delete and deleting it must be atomic, or two
    # concurrent deletes can both resolve the same game.
    with locked_transaction() as conn:
        active = (
            conn.execute(select(games.c.id, games.c.generation).where(_triple(games, group_id, white_id, black_id)))
            .mappings()
            .first()
        )
        if active is not None and (generation is None or int(active["generation"]) == int(generation)):
            # Two statements rather than one: a single execute containing both is
            # rejected outright by SQLite's driver.
            conn.execute(delete(moves).where(moves.c.game_id == active["id"]))
            conn.execute(delete(games).where(games.c.id == active["id"]))
            return
        target = select(finished_games.c.id).where(_triple(finished_games, group_id, white_id, black_id))
        if generation is None:
            target = target.order_by(finished_games.c.generation.desc()).limit(1)
        else:
            target = target.where(finished_games.c.generation == generation)
        conn.execute(delete(finished_games).where(finished_games.c.id.in_(target.scalar_subquery())))


def current_games(player_id, group_id=None):
    """
    Return the games in progress that ``player_id`` is playing, as game dicts.

    Most recently changed first. ``group_id`` restricts to one group; ``None``
    means every group.
    """
    validate_ids(player_id, *([group_id] if group_id is not None else []))
    stmt = _active_query().where((games.c.white_id == player_id) | (games.c.black_id == player_id))
    if group_id is not None:
        stmt = stmt.where(games.c.group_id == group_id)
    stmt = stmt.order_by(games.c.updated_at.desc(), games.c.id.desc())
    with transaction() as conn:
        return [_game_dict(r, finished=False) for r in conn.execute(stmt).mappings()]


def game_exists(player1, player2, group_id=0):
    """
    Return the game in progress between two players (either colour), as a game
    dict, or ``None``. Finished games don't count, so a rematch is allowed.
    """
    validate_ids(player1, player2, group_id)
    with transaction() as conn:
        return _game_exists(conn, player1, player2, group_id)


def _game_exists(conn, player1, player2, group_id):
    stmt = _active_query().where((games.c.group_id == group_id) & _either_pairing(games, player1, player2))
    return _game_dict(conn.execute(stmt).mappings().first(), finished=False)


def game_record(player1, player2, group_id=0):
    """
    Win/draw/loss record between two players across all their finished games
    (either colour arrangement) in a group.

    Status values: 1 = white won, 2 = black won, 3 = draw.

    :return: ``{"player1", "player2", "player1_wins", "player2_wins", "draws"}``.
    :rtype: dict
    """
    validate_ids(player1, player2, group_id)

    def wins(player):
        return func.count().filter(
            ((finished_games.c.white_id == player) & (finished_games.c.status == 1))
            | ((finished_games.c.black_id == player) & (finished_games.c.status == 2))
        )

    stmt = select(
        wins(player1).label("p1_wins"),
        wins(player2).label("p2_wins"),
        func.count().filter(finished_games.c.status == 3).label("draws"),
    ).where((finished_games.c.group_id == group_id) & _either_pairing(finished_games, player1, player2))
    with transaction() as conn:
        row = conn.execute(stmt).mappings().one()
    return {
        "player1": player1,
        "player2": player2,
        "player1_wins": int(row["p1_wins"]),
        "player2_wins": int(row["p2_wins"]),
        "draws": int(row["draws"]),
    }


# --- Challenges ------------------------------------------------------------


def challenge_exists(player1, player2, group_id=0):
    """Return ``{"challenger", "challenged"}`` for a pending challenge, or ``None``."""
    validate_ids(player1, player2, group_id)
    with transaction() as conn:
        return _challenge_exists(conn, player1, player2, group_id)


def _challenge_exists(conn, player1, player2, group_id):
    stmt = select(challenges.c.challenger, challenges.c.challenged).where(
        (challenges.c.group_id == group_id)
        & (
            ((challenges.c.challenger == player1) & (challenges.c.challenged == player2))
            | ((challenges.c.challenger == player2) & (challenges.c.challenged == player1))
        )
    )
    row = conn.execute(stmt).mappings().first()
    return None if row is None else {"challenger": row["challenger"], "challenged": row["challenged"]}


def challenge_create(challenger, challenged, group_id=0):
    """Create a pending challenge (no-op if it already exists)."""
    validate_ids(challenger, challenged, group_id)
    with locked_transaction() as conn:
        _require_users(conn, challenger, challenged)
        _challenge_create(conn, challenger, challenged, group_id)


def _challenge_create(conn, challenger, challenged, group_id):
    conn.execute(
        backend()
        .insert(challenges)
        .values(group_id=group_id, challenger=challenger, challenged=challenged, created_at=_utcnow())
        .on_conflict_do_nothing(index_elements=["group_id", "challenger", "challenged"])
    )


def challenge_delete(challenger, challenged, group_id=0):
    """Delete a pending challenge."""
    validate_ids(challenger, challenged, group_id)
    with transaction() as conn:
        _challenge_delete(conn, challenger, challenged, group_id)


def _challenge_delete(conn, challenger, challenged, group_id):
    """Delete a challenge, returning how many rows that removed."""
    result = conn.execute(
        delete(challenges).where(
            (challenges.c.group_id == group_id)
            & (challenges.c.challenger == challenger)
            & (challenges.c.challenged == challenged)
        )
    )
    return result.rowcount


def challenge(challenger, opponent, group_id=0):
    """
    Issue (or accept) a challenge between two players.

    If a reciprocal challenge already exists it is accepted (deleted) and ``True``
    is returned; otherwise a new challenge is created and ``False`` is returned.

    The whole check-and-mutate runs in **one** transaction. Before 0.9.0 these were
    four separate connections, so two players challenging each other simultaneously
    could both observe "no existing challenge" and each create one, leaving a
    reciprocal pair that nobody had accepted.

    :raises errors.UserNotFoundError: If either player does not exist.
    :raises errors.ChallengeError: On self-challenge, an existing game, or a
        duplicate outstanding challenge.
    """
    validate_ids(challenger, opponent, group_id)

    if challenger == opponent:
        raise errors.ChallengeError("You can't challenge yourself.")

    with locked_transaction() as conn:
        _require_users(conn, challenger, opponent)
        if _game_exists(conn, challenger, opponent, group_id):
            raise errors.ChallengeError(f"There is an unresolved game between {challenger} and {opponent} already!")

        existing = _challenge_exists(conn, challenger, opponent, group_id)
        if existing is None:
            _challenge_create(conn, challenger, opponent, group_id)
            return False
        if challenger == existing["challenger"]:
            raise errors.ChallengeError(f"You have already challenged {opponent}! Wait for them to accept.")

        # A reciprocal challenge exists: accept it by deleting the stored challenge.
        # Two concurrent accepts can both read the same pending row on PostgreSQL
        # (SQLite serializes them), so the row count is what decides which one won.
        if _challenge_delete(conn, existing["challenger"], existing["challenged"], group_id) == 0:
            raise errors.ChallengeError("That challenge is no longer pending; refresh and try again.")
        return True
