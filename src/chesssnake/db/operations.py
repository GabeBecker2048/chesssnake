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
connection instead, so a caller that needs several operations to be atomic can
run them together. Any function that reads and then writes based on what it read
uses :func:`~chesssnake.db.engine.locked_transaction`; see that module for why a
plain transaction is not safe for those on SQLite.

Passwords are hashed and verified by the caller (``chesssnake.api.auth``), never
here and never inside a transaction: Argon2 is deliberately slow, and on SQLite a
write transaction holds the whole database's lock. What this layer does instead
is make the *write* that follows a verification safe, by re-checking inside the
transaction that the hash it was verified against is still the current one.
"""

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from . import errors
from .engine import backend, locked_transaction, transaction
from .schema import auth_tokens, challenges, finished_games, games, moves, user_identities, user_settings, users

#: PostgreSQL BIGINT bounds. SQLite's INTEGER is also a signed 64-bit value, so
#: the same range applies to both backends.
_BIGINT_MIN = -9223372036854775808
_BIGINT_MAX = 9223372036854775807

#: Role codes, as stored. :mod:`chesssnake.dto` maps them to names for the wire.
ROLE_USER = 0
ROLE_ADMIN = 1

#: Token kinds, as stored.
TOKEN_SESSION = 0
TOKEN_API = 1

#: The prefix every token starts with, so a leaked one is easy to recognise and
#: secret scanners can be taught to look for it.
TOKEN_PREFIX = "css_"

#: Sessions kept per user; minting another deletes the oldest. A script that logs
#: in on every run would otherwise accumulate one row per run, forever.
MAX_SESSIONS_PER_USER = 20

#: Challenge colours, as stored: the colour the challenger asked to play.
COLOR_WHITE, COLOR_BLACK, COLOR_RANDOM = 0, 1, 2

#: Sentinel for "do not check the password hash" in the re-checking writes.
_UNCHECKED = object()


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


def hash_token(raw: str) -> str:
    """
    The stored form of a token: its SHA-256, hex.

    A fast hash is right here, unlike for passwords: a token is 256 random bits,
    so there is nothing to brute-force, and the lookup runs on every request.
    """
    return hashlib.sha256(raw.encode()).hexdigest()


def new_token() -> str:
    """A fresh bearer token: the prefix plus 256 random bits, URL-safe."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


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

#: Everything about a user that may leave this layer. ``password_hash`` never does
#: (only whether there is one); :func:`user_credentials` is the single exception.
_USER_COLUMNS = (
    users.c.id,
    users.c.username,
    users.c.role,
    users.c.created_at,
    users.c.disabled_at,
    users.c.password_hash.is_not(None).label("has_password"),
)


def _user_dict(row, identities=()):
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "role": int(row["role"]),
        "created_at": _as_utc(row["created_at"]),
        "disabled_at": _as_utc(row["disabled_at"]),
        "has_password": bool(row["has_password"]),
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


def _insert_user(conn, username, role, now, password_hash=None):
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
        result = conn.execute(
            users.insert().values(username=username, role=role, created_at=now, password_hash=password_hash)
        )
    except IntegrityError as e:
        raise errors.UserExistsError(f"The username {username!r} is already taken") from e
    return {
        "id": int(result.inserted_primary_key[0]),
        "username": username,
        "role": role,
        "created_at": now,
        "disabled_at": None,
        "has_password": password_hash is not None,
        "identities": [],
    }


def user_create(username, role=ROLE_USER, password_hash=None):
    """
    Create a user with a server-assigned id.

    :param username: Must satisfy :data:`chesssnake.db.errors.USERNAME_RE`; unique ignoring case.
    :param role: 0 for a player (default), 1 for an administrator.
    :param password_hash: An already-hashed password, or ``None`` for an account
        that cannot log in (one that only ever uses api tokens).
    :return: The user dict.
    :raises errors.UserValidationError: On a malformed username or role.
    :raises errors.UserExistsError: If the username is taken.
    """
    validate_username(username)
    _validate_role(role)
    with locked_transaction() as conn:
        return _insert_user(conn, username, role, _utcnow(), password_hash)


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


def user_credentials(username=None, user_id=None):
    """
    What a login needs to know: ``{id, username, role, disabled, password_hash}``, or ``None``.

    The only function that returns a password hash. Look up by exactly one of
    ``username`` (ignoring case) or ``user_id``.
    """
    stmt = select(users.c.id, users.c.username, users.c.role, users.c.disabled_at, users.c.password_hash)
    if user_id is not None:
        validate_ids(user_id)
        stmt = stmt.where(users.c.id == user_id)
    else:
        if not isinstance(username, str) or not username:
            return None
        stmt = stmt.where(func.lower(users.c.username) == username.lower())
    with transaction() as conn:
        row = conn.execute(stmt).mappings().first()
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "role": int(row["role"]),
        "disabled": row["disabled_at"] is not None,
        "password_hash": row["password_hash"],
    }


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
        try:
            conn.execute(update(users).where(users.c.id == user_id).values(username=username))
        except IntegrityError as e:
            raise errors.UserExistsError(f"The username {username!r} is already taken") from e
        return _load_user(conn, _user_by_id(conn, user_id))


def _refuse_losing_the_last_admin(conn, user_id):
    """Raise if ``user_id`` is the only enabled administrator left."""
    others = conn.execute(
        select(func.count())
        .select_from(users)
        .where((users.c.role == ROLE_ADMIN) & users.c.disabled_at.is_(None) & (users.c.id != user_id))
    ).scalar()
    if not others:
        raise errors.ForbiddenError("That is the last enabled administrator; make another admin first")


def user_set_role(user_id, role):
    """
    Make a user an administrator (``role=1``) or a plain player (``role=0``).

    :raises errors.UserNotFoundError: If there is no such user.
    :raises errors.UserValidationError: On an unknown role.
    :raises errors.ForbiddenError: On demoting the last enabled administrator.
    """
    validate_ids(user_id)
    _validate_role(role)
    with locked_transaction() as conn:
        current = _require_user(conn, user_id)
        if int(current["role"]) == ROLE_ADMIN and role != ROLE_ADMIN and current["disabled_at"] is None:
            _refuse_losing_the_last_admin(conn, user_id)
        conn.execute(update(users).where(users.c.id == user_id).values(role=role))
        return _load_user(conn, _user_by_id(conn, user_id))


def user_set_disabled(user_id, disabled):
    """
    Disable or re-enable a user. Disabling deletes every token the user has.

    A disabled user's tokens are also refused at authentication, so this is
    belt and braces; deleting them means re-enabling does not bring them back.

    :raises errors.UserNotFoundError: If there is no such user.
    :raises errors.ForbiddenError: On disabling the last enabled administrator.
    """
    validate_ids(user_id)
    with locked_transaction() as conn:
        current = _require_user(conn, user_id)
        if disabled:
            if int(current["role"]) == ROLE_ADMIN and current["disabled_at"] is None:
                _refuse_losing_the_last_admin(conn, user_id)
            if current["disabled_at"] is None:
                conn.execute(update(users).where(users.c.id == user_id).values(disabled_at=_utcnow()))
            conn.execute(delete(auth_tokens).where(auth_tokens.c.user_id == user_id))
        else:
            conn.execute(update(users).where(users.c.id == user_id).values(disabled_at=None))
        return _load_user(conn, _user_by_id(conn, user_id))


def _check_hash_unchanged(conn, user_id, expected_hash):
    """
    Inside a locked transaction: refuse if the password changed, or the user was
    disabled, since the caller verified a password outside it.
    """
    row = conn.execute(select(users.c.password_hash, users.c.disabled_at).where(users.c.id == user_id)).first()
    if row is None:
        raise errors.AuthError("Invalid username or password")
    if row.disabled_at is not None:
        raise errors.ForbiddenError("This account is disabled")
    if row.password_hash != expected_hash:
        raise errors.AuthError("The password changed while signing in; try again")


def user_set_password(user_id, password_hash, *, revoke="all", keep_token_id=None, expected_hash=_UNCHECKED):
    """
    Store a new password hash and revoke tokens, atomically.

    :param password_hash: The new hash, or ``None`` to remove the password (the
        account can then only use api tokens).
    :param revoke: ``"all"`` deletes every token (an admin reset: assume the old
        password leaked); ``"sessions"`` deletes only login sessions, which is what
        a user changing their own password wants, since their api tokens (a bot's,
        say) are separate credentials that did not leak.
    :param keep_token_id: A token to keep anyway, the one making the request, so
        changing your password does not log you out of the session you did it in.
    :param expected_hash: The hash the caller verified the current password
        against. If given and no longer current, nothing is written.
    :raises errors.UserNotFoundError: If there is no such user.
    :raises errors.AuthError: If ``expected_hash`` is stale.
    """
    validate_ids(user_id)
    if revoke not in ("all", "sessions"):
        raise ValueError(f"revoke must be 'all' or 'sessions', not {revoke!r}")
    with locked_transaction() as conn:
        _require_user(conn, user_id)
        if expected_hash is not _UNCHECKED:
            _check_hash_unchanged(conn, user_id, expected_hash)
        conn.execute(update(users).where(users.c.id == user_id).values(password_hash=password_hash))
        doomed = delete(auth_tokens).where(auth_tokens.c.user_id == user_id)
        if revoke == "sessions":
            doomed = doomed.where(auth_tokens.c.kind == TOKEN_SESSION)
        if keep_token_id is not None:
            doomed = doomed.where(auth_tokens.c.id != keep_token_id)
        conn.execute(doomed)


def user_rehash_password(user_id, old_hash, new_hash):
    """
    Upgrade a hash made with older Argon2 parameters, if it is still the current one.

    Called after a successful login. Losing the race to a password change is
    fine: that change wrote a fresh hash anyway, so this simply does nothing.
    """
    validate_ids(user_id)
    with transaction() as conn:
        conn.execute(
            update(users)
            .where((users.c.id == user_id) & (users.c.password_hash == old_hash))
            .values(password_hash=new_hash)
        )


# --- Tokens ----------------------------------------------------------------


def _token_dict(row):
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "kind": "session" if int(row["kind"]) == TOKEN_SESSION else "api",
        "name": row["name"],
        "created_at": _as_utc(row["created_at"]),
        "expires_at": _as_utc(row["expires_at"]),
    }


_TOKEN_COLUMNS = (
    auth_tokens.c.id,
    auth_tokens.c.user_id,
    auth_tokens.c.kind,
    auth_tokens.c.name,
    auth_tokens.c.created_at,
    auth_tokens.c.expires_at,
)


def token_create(user_id, kind, *, name=None, lifetime_days=None, expected_hash=_UNCHECKED):
    """
    Mint a token for a user and return ``(raw_token, token_dict)``.

    The raw token is returned once and never stored; only its hash is. Minting a
    session also prunes the user's expired tokens and keeps at most
    :data:`MAX_SESSIONS_PER_USER` sessions.

    :param kind: :data:`TOKEN_SESSION` or :data:`TOKEN_API`.
    :param lifetime_days: Days until it expires; ``None`` for an api token that does not.
    :param expected_hash: When minting right after verifying a password, the hash
        it was verified against: refused if the password changed or the account
        was disabled in between, so a login cannot outlive a reset that raced it.
    :raises errors.UserNotFoundError: If there is no such user.
    :raises errors.AuthError: If ``expected_hash`` is stale.
    :raises errors.ForbiddenError: If the account is disabled.
    """
    validate_ids(user_id)
    if kind not in (TOKEN_SESSION, TOKEN_API):
        raise ValueError(f"unknown token kind {kind!r}")
    if kind == TOKEN_SESSION and lifetime_days is None:
        raise ValueError("a session token must expire")
    now = _utcnow()
    expires_at = now + timedelta(days=lifetime_days) if lifetime_days is not None else None
    raw = new_token()
    with locked_transaction() as conn:
        user = _require_user(conn, user_id)
        if expected_hash is not _UNCHECKED:
            _check_hash_unchanged(conn, user_id, expected_hash)
        elif user["disabled_at"] is not None:
            raise errors.ForbiddenError("This account is disabled")
        conn.execute(
            delete(auth_tokens).where(
                (auth_tokens.c.user_id == user_id)
                & auth_tokens.c.expires_at.is_not(None)
                & (auth_tokens.c.expires_at <= now)
            )
        )
        if kind == TOKEN_SESSION:
            keep = (
                select(auth_tokens.c.id)
                .where((auth_tokens.c.user_id == user_id) & (auth_tokens.c.kind == TOKEN_SESSION))
                .order_by(auth_tokens.c.id.desc())
                .limit(MAX_SESSIONS_PER_USER - 1)
            )
            conn.execute(
                delete(auth_tokens).where(
                    (auth_tokens.c.user_id == user_id)
                    & (auth_tokens.c.kind == TOKEN_SESSION)
                    & auth_tokens.c.id.not_in(keep.scalar_subquery())
                )
            )
        result = conn.execute(
            auth_tokens.insert().values(
                user_id=user_id,
                kind=kind,
                name=name,
                token_hash=hash_token(raw),
                created_at=now,
                expires_at=expires_at,
            )
        )
        token_id = int(result.inserted_primary_key[0])
    return raw, {
        "id": token_id,
        "user_id": user_id,
        "kind": "session" if kind == TOKEN_SESSION else "api",
        "name": name,
        "created_at": now,
        "expires_at": expires_at,
    }


def token_resolve(raw):
    """
    Who a bearer token belongs to: ``{token_id, user_id, username, role}``, or ``None``.

    ``None`` for an unknown, expired or revoked token, or one whose user is
    disabled. One indexed lookup, a plain read: it runs on every request, so it
    must never take the write lock.
    """
    if not isinstance(raw, str) or not raw.startswith(TOKEN_PREFIX):
        return None
    now = _utcnow()
    stmt = (
        select(auth_tokens.c.id.label("token_id"), users.c.id.label("user_id"), users.c.username, users.c.role)
        .select_from(auth_tokens.join(users, auth_tokens.c.user_id == users.c.id))
        .where(
            (auth_tokens.c.token_hash == hash_token(raw))
            & users.c.disabled_at.is_(None)
            & (auth_tokens.c.expires_at.is_(None) | (auth_tokens.c.expires_at > now))
        )
    )
    with transaction() as conn:
        row = conn.execute(stmt).mappings().first()
    if row is None:
        return None
    return {
        "token_id": int(row["token_id"]),
        "user_id": int(row["user_id"]),
        "username": row["username"],
        "role": int(row["role"]),
    }


def tokens_list(user_id):
    """A user's tokens, newest first, without their secrets (which are not stored)."""
    validate_ids(user_id)
    stmt = select(*_TOKEN_COLUMNS).where(auth_tokens.c.user_id == user_id).order_by(auth_tokens.c.id.desc())
    with transaction() as conn:
        return [_token_dict(row) for row in conn.execute(stmt).mappings()]


def token_delete(token_id, user_id=None):
    """
    Revoke a token. With ``user_id``, only if it belongs to that user.

    :return: Whether a token was deleted.
    """
    validate_ids(token_id)
    stmt = delete(auth_tokens).where(auth_tokens.c.id == token_id)
    if user_id is not None:
        validate_ids(user_id)
        stmt = stmt.where(auth_tokens.c.user_id == user_id)
    with transaction() as conn:
        return conn.execute(stmt).rowcount > 0


# --- External identities ---------------------------------------------------


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


def identity_unlink(user_id, provider, external_id):
    """
    Remove a link. Silent when it is not there.

    :return: The user dict.
    :raises errors.UserNotFoundError: If there is no such user.
    """
    validate_ids(user_id)
    _validate_identity(provider, external_id)
    with transaction() as conn:
        conn.execute(
            delete(user_identities).where(
                (user_identities.c.user_id == user_id)
                & (user_identities.c.provider == provider)
                & (user_identities.c.external_id == external_id)
            )
        )
        return _load_user(conn, _require_user(conn, user_id))


# --- User settings -----------------------------------------------------------

#: Every per-user setting and its default. The type of the default is the
#: setting's type, checked exactly (``True`` is not an int here, nor 1 a bool).
#: Adding one is adding a line: they live in one JSON column, so it is not a
#: schema change. Only clients act on them; the server just keeps them.
USER_SETTING_DEFAULTS: dict[str, Any] = {
    "auto_queen": False,  # the web UI promotes pawns to a queen without asking
    # The web UI's board marks (0.14.2), each "#rrggbb". A highlight is a
    # right-click; an arrow a right-drag, and a ring a middle-click, use the arrow
    # colour; Ctrl, Alt and Ctrl+Alt override the colour of any mark.
    "mark_highlight_color": "#1b7a3a",  # forest green
    "mark_arrow_color": "#1b7a3a",  # forest green
    "mark_ctrl_color": "#c42b2b",  # crimson
    "mark_alt_color": "#7b3fc4",  # violet
    "mark_ctrl_alt_color": "#0b7e86",  # teal
}

#: A colour setting's only accepted form. Stored lowercase.
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _setting_value(name, value):
    """
    ``value`` checked (and normalised) for setting ``name``, or ``None`` if it is
    not acceptable. The type of a setting's default is its type, compared exactly
    (``True`` is not an int here, nor 1 a bool); a ``*_color`` is "#rrggbb".
    """
    if type(value) is not type(USER_SETTING_DEFAULTS[name]):
        return None
    if name.endswith("_color"):
        # Colours end up in the web UI's drawing, so they are a strict format,
        # never free text.
        return value.lower() if _HEX_COLOR.match(value) else None
    return value


def _settings_with_defaults(stored):
    settings = dict(USER_SETTING_DEFAULTS)
    for name, value in (stored or {}).items():
        # A setting since removed, or a value no longer acceptable, falls back to the default.
        if name in settings:
            checked = _setting_value(name, value)
            if checked is not None:
                settings[name] = checked
    return settings


def user_settings_get(user_id):
    """
    Return a user's settings: every setting, defaults filled in.

    :raises errors.UserNotFoundError: If there is no such user.
    """
    validate_ids(user_id)
    with transaction() as conn:
        _require_user(conn, user_id)
        raw = conn.execute(select(user_settings.c.settings).where(user_settings.c.user_id == user_id)).scalar()
    return _settings_with_defaults(json.loads(raw) if raw else {})


def user_settings_update(user_id, changes):
    """
    Change some of a user's settings; the others keep their values.

    :param changes: ``{name: value}``; every name must be a known setting and
        every value of that setting's type.
    :return: All the user's settings afterwards, defaults filled in.
    :raises errors.UserValidationError: On an unknown setting or a wrong type.
    :raises errors.UserNotFoundError: If there is no such user.
    """
    validate_ids(user_id)
    if not isinstance(changes, dict):
        raise errors.UserValidationError("Settings must be an object of {name: value}")
    checked = {}
    for name, value in changes.items():
        if name not in USER_SETTING_DEFAULTS:
            raise errors.UserValidationError(
                f"Unknown setting {name!r}; known: {', '.join(sorted(USER_SETTING_DEFAULTS))}"
            )
        normalised = _setting_value(name, value)
        if normalised is None:
            wanted = (
                "a colour as #rrggbb" if name.endswith("_color") else f"a {type(USER_SETTING_DEFAULTS[name]).__name__}"
            )
            raise errors.UserValidationError(f"Setting {name!r} must be {wanted}")
        checked[name] = normalised
    changes = checked
    now = _utcnow()
    # A read-modify-write: two changes to different settings at once must both land.
    with locked_transaction() as conn:
        _require_user(conn, user_id)
        # Make sure the row exists, so there is something to lock on PostgreSQL
        # (FOR UPDATE locks rows, not their absence); SQLite's BEGIN IMMEDIATE
        # already serializes the whole thing.
        conn.execute(
            backend()
            .insert(user_settings)
            .values(user_id=user_id, settings="{}", updated_at=now)
            .on_conflict_do_nothing(index_elements=["user_id"])
        )
        raw = conn.execute(
            select(user_settings.c.settings).where(user_settings.c.user_id == user_id).with_for_update()
        ).scalar()
        stored = json.loads(raw) if raw else {}
        stored = {name: value for name, value in stored.items() if name in USER_SETTING_DEFAULTS}
        stored.update(changes)
        conn.execute(
            update(user_settings)
            .where(user_settings.c.user_id == user_id)
            .values(settings=json.dumps(stored, sort_keys=True), updated_at=now)
        )
    return _settings_with_defaults(stored)


def user_get_or_create_by_identity(provider, external_id, username):
    """
    Return the user linked to an external id, creating user and link if there is none.

    This is the one call an integration (a Discord bot, say) needs per
    interaction: idempotent, and the ``username`` is only used when the user is
    created. An existing user is returned as is, whatever name was passed. A user
    created here has no password, so it cannot log in; the integration acts for
    it with its own admin token.

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
    """Archived games, with names. Add ``.where(...)`` to pick one or some."""
    return select(
        *_shared_columns(finished_games),
        finished_games.c.status,
        finished_games.c.termination,
        finished_games.c.finished_at,
    ).select_from(_joined(finished_games))


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


def _game_in_progress_between(conn, player1, player2, group_id):
    """The game in progress between two players in a group, either colour, or ``None``."""
    stmt = _active_query().where((games.c.group_id == group_id) & _either_pairing(games, player1, player2))
    return _game_dict(conn.execute(stmt).mappings().first(), finished=False)


def _create_game(conn, group_id, white_id, black_id, initial_fen):
    """
    Start a game for a triple inside a locked transaction; returns the game dict.

    Its ``generation`` is one more than the triple's finished games, so past games
    keep their numbering. ``ON CONFLICT DO NOTHING`` plus the re-select settle a
    concurrent creator; the callers' pair lock makes that rare.
    """
    now = _utcnow()
    latest = conn.execute(
        select(func.max(finished_games.c.generation)).where(_triple(finished_games, group_id, white_id, black_id))
    ).scalar()
    conn.execute(
        backend()
        .insert(games)
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
    return _game_dict(_active_for_triple(conn, group_id, white_id, black_id), finished=False)


def game_get_or_create(group_id, white_id, black_id, initial_fen):
    """
    Load the game in progress for ``(group_id, white_id, black_id)``, or start one.

    The administrator's way of creating a game; players normally get one by
    accepting a challenge (:func:`challenge_accept`). The engine-derived
    ``initial_fen`` is passed in so this layer stays engine-free.

    :return: The game dict.
    :raises errors.SQLIdError: On an invalid id, or when both sides are the same user.
    :raises errors.UserNotFoundError: If either player does not exist.
    """
    validate_ids(white_id, black_id, group_id)
    if white_id == black_id:
        raise errors.SQLIdError(white_id, "White and black must be different users.")

    # locked_transaction, not transaction: this reads and then writes based on
    # what it read. Under a plain (deferred) BEGIN, SQLite starts as a reader and
    # must upgrade to a writer for the INSERT, which fails with SQLITE_BUSY
    # *immediately* if another writer holds the lock (busy_timeout does not apply
    # to the upgrade path): a 500 "database is locked" whenever a move was in flight.
    with locked_transaction() as conn:
        backend().lock_pair(conn, group_id, white_id, black_id)
        row = _active_for_triple(conn, group_id, white_id, black_id)
        if row is not None:
            return _game_dict(row, finished=False)
        _require_users(conn, white_id, black_id)
        return _create_game(conn, group_id, white_id, black_id, initial_fen)


def game_get_by_id(game_id):
    """Return the game dict for a game id, in progress or archived, or ``None``."""
    validate_ids(game_id)
    with transaction() as conn:
        row = conn.execute(_active_query().where(games.c.id == game_id)).mappings().first()
        if row is not None:
            return _game_dict(row, finished=False)
        row = conn.execute(_finished_query().where(finished_games.c.id == game_id)).mappings().first()
        return _game_dict(row, finished=True)


def games_between(player1, player2, group_id=0, status="all"):
    """
    Every game between two players in a group, either colour, oldest first.

    :param status: ``"active"`` (the game in progress, if any), ``"finished"``
        (the archive) or ``"all"``.
    """
    validate_ids(player1, player2, group_id)
    if status not in ("active", "finished", "all"):
        raise errors.UserValidationError(f"status must be active, finished or all, not {status!r}")
    found = []
    with transaction() as conn:
        if status in ("finished", "all"):
            stmt = _finished_query().where(
                (finished_games.c.group_id == group_id) & _either_pairing(finished_games, player1, player2)
            )
            found += [_game_dict(r, finished=True) for r in conn.execute(stmt).mappings()]
        if status in ("active", "all"):
            stmt = _active_query().where((games.c.group_id == group_id) & _either_pairing(games, player1, player2))
            found += [_game_dict(r, finished=False) for r in conn.execute(stmt).mappings()]
    return sorted(found, key=lambda game: game["id"])


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


def apply_game_change(game_id, mutate, expected_version=None):
    """
    Atomically read a game in progress (with its moves), transform it, and write it back.

    Locks the row, loads the ``moves`` history, optionally enforces
    ``expected_version``, calls ``mutate(game, history, now)``, which runs the
    engine, then persists the returned :class:`GameChange`: an UPDATE plus
    appended moves while the game continues, or, once it is over, an insert into
    ``finished_games`` and the removal of the live row and its moves. One
    transaction either way, so concurrent actions on the same game cannot
    clobber each other.

    How the lock is taken differs by backend and is deliberately explicit: see
    :func:`chesssnake.db.postgres.lock_current_game` (``SELECT … FOR UPDATE OF
    games``) and :func:`chesssnake.db.sqlite.lock_current_game` (already
    exclusive, because the transaction opened with ``BEGIN IMMEDIATE``).

    An id that names a *finished* game is handed to ``mutate`` read-only, so the
    engine refuses the action with its own ``GameOverError``, exactly as it
    would for a game still in memory. An archived game is never changed: should
    ``mutate`` not raise, nothing is written and :class:`errors.GameError` is.

    :param mutate: ``(game_dict, history, now) -> GameChange``, where ``history``
        is ``{"position_keys": [...], "move_sans": [...], "max_ply": int}`` for
        the plies played so far (the starting position is not included) and
        ``now`` is the UTC timestamp this change is recorded at.
    :param expected_version: If given and stale, raise.
    :return: ``GameChange.result``.
    :raises errors.GameNotFoundError: If there is no such game.
    :raises errors.VersionConflictError: If ``expected_version`` is stale.
    """
    validate_ids(game_id)
    module = backend()
    now = _utcnow()

    with locked_transaction() as conn:
        row = module.lock_current_game(conn, _active_query().where(games.c.id == game_id), of=games).mappings().first()
        if row is None:
            finished = _game_dict(
                conn.execute(_finished_query().where(finished_games.c.id == game_id)).mappings().first(),
                finished=True,
            )
            if finished is None:
                raise errors.GameNotFoundError(f"No game with id {game_id}")
            _check_version(finished, expected_version)
            sans = game_history_in(conn, game_id) or []
            mutate(finished, {"position_keys": [], "move_sans": sans, "max_ply": len(sans)}, now)
            raise errors.GameError(f"Game {game_id} is over and cannot change")
        _check_version(row, expected_version)

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
                    group_id=int(row["group_id"]),
                    white_id=int(row["white_id"]),
                    black_id=int(row["black_id"]),
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


def game_history_in(conn, game_id):
    """The SAN list of an archived game, on an open connection, or ``None``."""
    movetext = conn.execute(select(finished_games.c.movetext).where(finished_games.c.id == game_id)).scalar()
    return None if movetext is None else movetext.split()


def game_delete(game_id):
    """
    Delete a game (in progress or archived) and its moves.

    :return: Whether a game was deleted.
    """
    validate_ids(game_id)
    with transaction() as conn:
        # Two statements rather than one: a single execute containing both is
        # rejected outright by SQLite's driver. Moves first, for the foreign key.
        conn.execute(delete(moves).where(moves.c.game_id == game_id))
        live = conn.execute(delete(games).where(games.c.id == game_id)).rowcount
        archived = conn.execute(delete(finished_games).where(finished_games.c.id == game_id)).rowcount
    return bool(live or archived)


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


#: The most rows one listing call returns (``limit`` is clamped to it).
LIST_LIMIT_MAX = 200


def _validate_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= LIST_LIMIT_MAX):
        raise errors.UserValidationError(f"limit must be 1 to {LIST_LIMIT_MAX}")


def games_live(limit=50):
    """
    Every game in progress, in any group, most recently changed first.

    What a spectator browses: any logged-in user may read any game.
    """
    _validate_limit(limit)
    stmt = _active_query().order_by(games.c.updated_at.desc(), games.c.id.desc()).limit(limit)
    with transaction() as conn:
        return [_game_dict(r, finished=False) for r in conn.execute(stmt).mappings()]


def games_finished(player_id=None, limit=50, before=None):
    """
    Archived games, newest first (by id, which only increases).

    :param player_id: Only games this user played, either colour; ``None`` for all.
    :param before: Only games with an id below this one: pass the last id of a
        page to get the next.
    """
    _validate_limit(limit)
    validate_ids(*(x for x in (player_id, before) if x is not None))
    stmt = _finished_query()
    if player_id is not None:
        stmt = stmt.where((finished_games.c.white_id == player_id) | (finished_games.c.black_id == player_id))
    if before is not None:
        stmt = stmt.where(finished_games.c.id < before)
    stmt = stmt.order_by(finished_games.c.id.desc()).limit(limit)
    with transaction() as conn:
        return [_game_dict(r, finished=True) for r in conn.execute(stmt).mappings()]


def users_search(prefix="", limit=20, offset=0):
    """
    Users whose name starts with ``prefix`` (ignoring case), ordered by name.

    ``%`` and ``_`` in the prefix match themselves, not anything. An empty prefix
    lists everyone, a page at a time.
    """
    _validate_limit(limit)
    if not isinstance(prefix, str) or len(prefix) > 64:
        raise errors.UserValidationError("The search text must be at most 64 characters")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise errors.UserValidationError("offset must be 0 or more")
    stmt = select(*_USER_COLUMNS)
    if prefix:
        stmt = stmt.where(func.lower(users.c.username).startswith(prefix.lower(), autoescape=True))
    stmt = stmt.order_by(func.lower(users.c.username), users.c.id).limit(limit).offset(offset)
    with transaction() as conn:
        rows = list(conn.execute(stmt).mappings())
        found: dict[int, list] = {int(r["id"]): [] for r in rows}
        if found:
            ids_stmt = (
                select(user_identities.c.user_id, user_identities.c.provider, user_identities.c.external_id)
                .where(user_identities.c.user_id.in_(list(found)))
                .order_by(user_identities.c.provider, user_identities.c.external_id)
            )
            for ident in conn.execute(ids_stmt).mappings():
                found[int(ident["user_id"])].append(
                    {"provider": ident["provider"], "external_id": ident["external_id"]}
                )
    return [_user_dict(r, found[int(r["id"])]) for r in rows]


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

_challenger = users.alias("cr")
_challenged = users.alias("cd")


def _challenge_query():
    return select(
        challenges,
        _challenger.c.username.label("challenger_name"),
        _challenged.c.username.label("challenged_name"),
    ).select_from(
        challenges.join(_challenger, challenges.c.challenger_id == _challenger.c.id).join(
            _challenged, challenges.c.challenged_id == _challenged.c.id
        )
    )


def _challenge_dict(row):
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "group_id": int(row["group_id"]),
        "challenger_id": int(row["challenger_id"]),
        "challenger_name": row["challenger_name"],
        "challenged_id": int(row["challenged_id"]),
        "challenged_name": row["challenged_name"],
        "color": int(row["color"]),
        "created_at": _as_utc(row["created_at"]),
    }


def _pending_between(conn, a, b, group_id):
    stmt = _challenge_query().where(
        (challenges.c.group_id == group_id)
        & (
            ((challenges.c.challenger_id == a) & (challenges.c.challenged_id == b))
            | ((challenges.c.challenger_id == b) & (challenges.c.challenged_id == a))
        )
    )
    return _challenge_dict(conn.execute(stmt).mappings().first())


def challenge_create(challenger_id, challenged_id, group_id=0, color=COLOR_RANDOM):
    """
    Challenge another user to a game in a group.

    :param color: The colour the challenger wants: :data:`COLOR_WHITE`,
        :data:`COLOR_BLACK` or :data:`COLOR_RANDOM` (decided on acceptance).
    :return: The challenge dict.
    :raises errors.UserNotFoundError: If either user does not exist.
    :raises errors.ChallengeError: On a self-challenge, a disabled opponent, a game
        already in progress between the two in that group, or a pending
        challenge between them in either direction.
    """
    validate_ids(challenger_id, challenged_id, group_id)
    if color not in (COLOR_WHITE, COLOR_BLACK, COLOR_RANDOM):
        raise errors.UserValidationError(f"Invalid colour {color!r}")
    if challenger_id == challenged_id:
        raise errors.ChallengeError("You can't challenge yourself.")

    with locked_transaction() as conn:
        backend().lock_pair(conn, group_id, challenger_id, challenged_id)
        _require_users(conn, challenger_id, challenged_id)
        if _user_by_id(conn, challenged_id)["disabled_at"] is not None:
            raise errors.ChallengeError("That user's account is disabled.")
        if _game_in_progress_between(conn, challenger_id, challenged_id, group_id) is not None:
            raise errors.ChallengeError("There is already a game in progress between you in this group.")
        pending = _pending_between(conn, challenger_id, challenged_id, group_id)
        if pending is not None:
            if pending["challenger_id"] == challenger_id:
                raise errors.ChallengeError(
                    f"You have already challenged them (challenge {pending['id']}); wait for them to accept."
                )
            raise errors.ChallengeError(f"They have already challenged you: accept challenge {pending['id']} instead.")
        result = conn.execute(
            challenges.insert().values(
                group_id=group_id,
                challenger_id=challenger_id,
                challenged_id=challenged_id,
                color=color,
                created_at=_utcnow(),
            )
        )
        challenge_id = int(result.inserted_primary_key[0])
        return _challenge_dict(
            conn.execute(_challenge_query().where(challenges.c.id == challenge_id)).mappings().first()
        )


def challenge_get(challenge_id):
    """The challenge dict, or ``None``."""
    validate_ids(challenge_id)
    with transaction() as conn:
        return _challenge_dict(
            conn.execute(_challenge_query().where(challenges.c.id == challenge_id)).mappings().first()
        )


def challenges_for(user_id, direction="all"):
    """
    A user's pending challenges, oldest first.

    :param direction: ``"incoming"`` (they were challenged), ``"outgoing"`` (they
        challenged) or ``"all"``.
    """
    validate_ids(user_id)
    if direction == "incoming":
        where = challenges.c.challenged_id == user_id
    elif direction == "outgoing":
        where = challenges.c.challenger_id == user_id
    elif direction == "all":
        where = (challenges.c.challenger_id == user_id) | (challenges.c.challenged_id == user_id)
    else:
        raise errors.UserValidationError(f"direction must be incoming, outgoing or all, not {direction!r}")
    with transaction() as conn:
        rows = conn.execute(_challenge_query().where(where).order_by(challenges.c.id)).mappings()
        return [_challenge_dict(row) for row in rows]


def challenge_delete(challenge_id):
    """Decline or withdraw a challenge. :return: Whether one was deleted."""
    validate_ids(challenge_id)
    with transaction() as conn:
        return conn.execute(delete(challenges).where(challenges.c.id == challenge_id)).rowcount > 0


def challenge_accept(challenge_id, initial_fen, accepted_by=None):
    """
    Accept a challenge: the challenge is consumed and the game created, atomically.

    The challenge row is deleted *first*, and the accept proceeds only if that
    delete removed it. Two concurrent accepts (or an accept racing a withdrawal)
    therefore cannot both succeed: on PostgreSQL the second delete waits for the
    first transaction's row lock and then finds nothing; on SQLite the
    transactions are serialised outright. The pair lock covers an administrator
    creating a game between the same two at the same moment.

    :param accepted_by: If given, the user accepting, who must be the challenged one.
    :return: The new game dict.
    :raises errors.ChallengeNotFoundError: If it is no longer pending.
    :raises errors.ForbiddenError: If ``accepted_by`` is not the challenged user.
    :raises errors.ChallengeError: If a game between them started in the meantime
        (the challenge is then kept).
    """
    validate_ids(challenge_id)
    with locked_transaction() as conn:
        challenge = _challenge_dict(
            conn.execute(_challenge_query().where(challenges.c.id == challenge_id)).mappings().first()
        )
        if challenge is None:
            raise errors.ChallengeNotFoundError(f"Challenge {challenge_id} is not pending")
        if accepted_by is not None and int(accepted_by) != challenge["challenged_id"]:
            raise errors.ForbiddenError("Only the challenged player can accept a challenge")
        challenger, challenged, group_id = (
            challenge["challenger_id"],
            challenge["challenged_id"],
            challenge["group_id"],
        )
        backend().lock_pair(conn, group_id, challenger, challenged)
        if conn.execute(delete(challenges).where(challenges.c.id == challenge_id)).rowcount == 0:
            raise errors.ChallengeNotFoundError(f"Challenge {challenge_id} is no longer pending")
        if _user_by_id(conn, challenger)["disabled_at"] is not None:
            raise errors.ChallengeError("The challenger's account is disabled.")
        if _game_in_progress_between(conn, challenger, challenged, group_id) is not None:
            # Raising rolls the delete back, so the challenge survives for later.
            raise errors.ChallengeError("A game between you is already in progress in this group.")
        color = challenge["color"]
        if color == COLOR_RANDOM:
            color = secrets.randbelow(2)
        white, black = (challenger, challenged) if color == COLOR_WHITE else (challenged, challenger)
        return _create_game(conn, group_id, white, black, initial_fen)
