"""
Authentication and authorization for the api-endpoint.

Every ``/v1`` route except login and registration needs a bearer token:
``Authorization: Bearer css_…``. A token is opaque, random, and stored only as its
SHA-256 (see :mod:`chesssnake.db.operations`), so revoking one (logout, a
password reset, disabling the user) takes effect on the very next request.

:func:`authenticate` turns a raw token into a :class:`Principal` and knows nothing
about HTTP, so a websocket handshake can call it exactly as the HTTP dependency
:func:`current_principal` does.

Passwords are hashed with Argon2id. Hashing is deliberately expensive in both
time and memory, so two rules hold everywhere here:

- it never runs inside a database transaction (on SQLite a write transaction
  holds the whole database's lock); and
- it runs on a dedicated pool of :data:`MAX_CONCURRENT_HASHES` threads, never on
  the request's own worker thread. Each hash takes ~19 MiB, and glibc keeps a
  block that size in the allocating thread's arena after it is freed rather than
  returning it to the system. Capping only how many hash *at once* (0.12.0's
  semaphore) still let each of anyio's 40 worker threads keep its own 19 MiB:
  measured, one burst of 40 logins left a process at 700 MiB and pinned the
  512 MiB container at its limit. With four threads that ever hash, the same
  bursts settle at ~93 MiB and stay there. Waiting too long for the pool is a
  503, like a saturated database pool.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Header

from ..db import errors
from ..db import operations as ops

#: Argon2id parameters: RFC 9106's low-memory recommendation (19 MiB, 2 passes).
#: The library default is 64 MiB per hash, which is a lot to ask of the 512 MiB
#: containers this commonly runs in. Changing these is safe: existing hashes keep
#: verifying and are upgraded at the user's next login.
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST_KIB = 19456
ARGON2_PARALLELISM = 1

#: Threads that ever run a password hash, so also how many run at once (see the
#: module docstring for why it must be a fixed set of threads, not just a cap).
MAX_CONCURRENT_HASHES = 4
#: How long a login waits for a hashing slot before answering 503.
HASH_SLOT_TIMEOUT_SECONDS = 5

#: Admission: a caller holds a slot while its hash is queued or running, so the
#: pool's queue can never grow without bound and a long wait becomes a 503.
_hash_slots = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)
#: The only threads that run Argon2. Created on first use; they do no database
#: work, so the request's context (WRITE_TRANSACTION) not following them is fine.
_hash_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_HASHES, thread_name_prefix="chesssnake-argon2")


@lru_cache(maxsize=1)
def _hasher():
    # Imported lazily: argon2-cffi ships in the `api` extra, and this module is
    # imported by the server only.
    from argon2 import PasswordHasher

    return PasswordHasher(
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST_KIB,
        parallelism=ARGON2_PARALLELISM,
    )


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A hash nobody's password matches, verified against when there is no real one."""
    return _hasher().hash("chesssnake: no such account")


class _HashSlot:
    """The semaphore as a context manager that turns a timeout into a 503."""

    def __enter__(self):
        if not _hash_slots.acquire(timeout=HASH_SLOT_TIMEOUT_SECONDS):
            raise errors.SQLBusyError("The server is busy checking passwords. Retry shortly.")

    def __exit__(self, *_exc):
        _hash_slots.release()


def _on_hash_pool(fn, *args):
    """Run ``fn(*args)`` on the Argon2 pool, holding a slot; returns its result."""
    with _HashSlot():
        return _hash_pool.submit(fn, *args).result()


def validate_password(password) -> str:
    """
    :return: The password, unchanged.
    :raises errors.UserValidationError: If it is not a string of an acceptable length.
    """
    if not isinstance(password, str) or not (errors.PASSWORD_MIN <= len(password) <= errors.PASSWORD_MAX):
        raise errors.UserValidationError(
            f"A password must be {errors.PASSWORD_MIN} to {errors.PASSWORD_MAX} characters long"
        )
    return password


def hash_password(password: str) -> str:
    """Hash a (validated) password with Argon2id. Slow on purpose; never call inside a transaction."""
    validate_password(password)
    return _on_hash_pool(_hasher().hash, password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """
    Whether ``password`` matches ``password_hash``.

    Always costs one full verification, even when there is no hash to check (an
    unknown user, or an account without a password), so the response time does
    not reveal which usernames exist or which accounts can log in.
    """
    if not isinstance(password, str):
        password = ""
    return _on_hash_pool(_verify, password_hash, password)


def _verify(password_hash: str | None, password: str) -> bool:
    """The verification itself; runs on the Argon2 pool (the dummy hash is made there too)."""
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    try:
        return _hasher().verify(password_hash or _dummy_hash(), password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Whether a hash was made with weaker parameters than the current ones."""
    return _hasher().check_needs_rehash(password_hash)


@dataclass(frozen=True)
class Principal:
    """Who a request is from: the user its token belongs to."""

    user_id: int
    username: str
    role: int
    token_id: int

    @property
    def is_admin(self) -> bool:
        return self.role == ops.ROLE_ADMIN


def authenticate(raw_token: str | None) -> Principal:
    """
    Resolve a raw bearer token to its :class:`Principal`.

    Transport-agnostic: the HTTP dependency below wraps it, and a websocket can
    call it with a token received in its first message. Database failures are
    *not* turned into an authentication failure: a saturated pool stays a 503,
    rather than telling a client with a perfectly good token to log in again.

    :raises errors.AuthError: For a missing, unknown, expired or revoked token,
        or one whose user has been disabled.
    """
    if not raw_token:
        raise errors.AuthError()
    found = ops.token_resolve(raw_token)
    if found is None:
        raise errors.AuthError("Invalid, expired or revoked token; log in again")
    return Principal(found["user_id"], found["username"], found["role"], found["token_id"])


def bearer_token(authorization: str | None) -> str | None:
    """The token from an ``Authorization: Bearer …`` header value, or ``None``."""
    if not authorization:
        return None
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def current_principal(authorization: str | None = Header(default=None)) -> Principal:
    """
    The FastAPI dependency every authenticated route uses.

    A plain ``def`` so it runs in the threadpool with the route, and it reads the
    header itself rather than through ``HTTPBearer``, whose 401 has no
    ``error_type`` and so reaches the Python client as a generic error.
    """
    return authenticate(bearer_token(authorization))


def require_admin(principal: Principal) -> None:
    """:raises errors.ForbiddenError: Unless the principal is an administrator."""
    if not principal.is_admin:
        raise errors.ForbiddenError("Only an administrator can do that")


def acting_as(principal: Principal, player_id: int | None, *, participants=None, require_actor=True) -> int | None:
    """
    Decide which user an action is performed as.

    - A non-admin always acts as themselves; naming anyone else is a 403.
    - An admin acts as an explicitly named ``player_id`` (how an integration such
      as a Discord bot plays for its users), as long as that user exists and is
      not disabled.
    - An admin who names nobody acts as themselves when they are one of
      ``participants`` (or when there are none to choose from). Otherwise, with
      ``require_actor=False``, the result is ``None``, meaning "whoever the rules
      allow" (a move by the side to move); with ``require_actor=True`` it is an
      error, since resigning or offering a draw needs a definite player.

    :param participants: The users the action concerns (a game's two players),
        or ``None`` when it is not about anyone in particular.
    :raises errors.ForbiddenError: If a non-admin names another user, or the
        named user is disabled.
    :raises errors.UserNotFoundError: If an admin names a user that does not exist.
    :raises errors.UserValidationError: If an admin must name a player and did not.
    """
    if player_id is None or player_id == principal.user_id:
        if player_id is None and principal.is_admin and participants and principal.user_id not in participants:
            if require_actor:
                raise errors.UserValidationError("An administrator acting in someone else's game must give player_id")
            return None
        return principal.user_id
    if not principal.is_admin:
        raise errors.ForbiddenError("You can only act as yourself")
    target = ops.user_get(player_id)
    if target is None:
        raise errors.UserNotFoundError(f"No user with id {player_id}")
    if target["disabled_at"] is not None:
        raise errors.ForbiddenError(f"User {player_id} is disabled")
    return int(player_id)


def login(username: str, password: str, lifetime_days: int):
    """
    Check a username and password and mint a session token.

    The password is verified outside any transaction; the token is then minted in
    a transaction that requires the password hash to be unchanged and the
    account still enabled, so a login cannot slip in after a reset or a disable
    that happened while it was being verified.

    :return: ``(raw_token, token_dict, user_dict)``.
    :raises errors.AuthError: On any wrong username or password, with one message.
    :raises errors.ForbiddenError: If the password was right but the account is disabled.
    """
    credentials = ops.user_credentials(username=username)
    stored = credentials["password_hash"] if credentials else None
    if not verify_password(stored, password) or credentials is None or stored is None:
        raise errors.AuthError("Invalid username or password")
    if credentials["disabled"]:
        raise errors.ForbiddenError("This account is disabled")
    raw, token = ops.token_create(
        credentials["id"], ops.TOKEN_SESSION, name="login", lifetime_days=lifetime_days, expected_hash=stored
    )
    if needs_rehash(stored):
        # After minting, not before: the mint re-checked the hash it was given.
        ops.user_rehash_password(credentials["id"], stored, hash_password(password))
    return raw, token, ops.user_get(credentials["id"])


def check_current_password(principal: Principal, password: str) -> str | None:
    """
    Verify the caller's own password; returns the hash it was checked against.

    :raises errors.AuthError: If it is wrong (or the account has none).
    """
    credentials = ops.user_credentials(user_id=principal.user_id)
    stored = credentials["password_hash"] if credentials else None
    if not verify_password(stored, password):
        raise errors.AuthError("The current password is wrong")
    return stored
