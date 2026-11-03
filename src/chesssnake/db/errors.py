"""
Persistence-layer errors, shared by the api-endpoint and the remote client.

This is the one ``db`` module the client imports (``remote/client.py`` maps the
``error_type`` in an error response back to a class by name), so it must stay
free of SQLAlchemy. That is also why the username and identity rules live here
rather than in ``operations``: the api-endpoint's request validation, the CLI
and the operations layer all share one definition without any of them having
to import the others.
"""

import re

#: What a username may look like: 2 to 32 characters of letters, digits, ``_``,
#: ``.`` and ``-``, and not digits alone. Case is preserved for display but
#: ignored for uniqueness. The not-all-digits rule is what lets every client
#: (``chesssnake play --white 42``, ``Game.remote("alice", ...)``) accept either
#: a user id or a username in the same place without ambiguity.
USERNAME_RE = re.compile(r"^(?![0-9]+$)[A-Za-z0-9_.-]{2,32}$")
USERNAME_RULE = "2 to 32 characters of letters, digits, '_', '.' and '-', and not only digits"

#: An identity provider name (``discord``): short, lowercase, URL-safe.
PROVIDER_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

#: An external id (a Discord snowflake, say): any non-blank token.
EXTERNAL_ID_RE = re.compile(r"^\S{1,128}$")

#: Password length bounds. The upper one only stops absurd inputs: Argon2 hashes
#: any length in the same time.
PASSWORD_MIN = 8
PASSWORD_MAX = 256


class GameError(Exception):
    def __init__(self, msg):
        super().__init__(msg)


class SQLError(GameError):
    def __init__(self, msg):
        super().__init__(msg)


class SQLBusyError(SQLError):
    """
    Every pooled database connection is in use and none came free in time.

    Distinct from :class:`SQLError` because nothing is wrong: the server is
    simply saturated, the request was never attempted, and retrying shortly is
    the right response. The api-endpoint maps it to ``503`` rather than ``500``
    so a client can tell "come back in a moment" from "something is broken".
    """

    def __init__(self, msg="The server is busy: no database connection became free in time. Retry shortly."):
        super().__init__(msg)


class SQLIdError(SQLError):
    def __init__(self, id_, reason=None):
        msg = "\n".join(
            [
                "One of the given ids is invalid:",
                f"  id: {id_}",
                reason or "All ids must be integers that fit in a signed 64-bit integer (BIGINT).",
            ]
        )
        super().__init__(msg)


class SQLAuthError(SQLError):
    """No database connection string is configured.

    The env var and config-file names below are derived from the configuration
    schema in :mod:`chesssnake.config`; a test asserts they stay in sync, since
    this layer deliberately does not import that module.
    """

    def __init__(self):
        msg = "\n".join(
            [
                "No database connection string is configured.",
                "",
                "The URL scheme selects the backend:",
                "  sqlite:///chesssnake.db                                  (a local file, no server)",
                "  postgresql://user:password@localhost:5432/chesssnake     (needs the `postgres` extra)",
                "",
                "Set it in any one of these places (later ones win):",
                "  1. In your config file, under the [database] table:",
                "       [database]",
                "       url = 'sqlite:///chesssnake.db'",
                "  2. As an environment variable:",
                "       CHESSSNAKE__DATABASE__URL='sqlite:///chesssnake.db'",
                "  3. On the command line:",
                "       chesssnake api-endpoint --database-url sqlite:///chesssnake.db",
                "",
                "Only URL-form connection strings are accepted; libpq keyword strings",
                "(dbname=... user=...) are not. Run `chesssnake config init` to write a",
                "commented config file, or `chesssnake config show` to see current settings.",
            ]
        )
        super().__init__(msg)


class ChallengeError(GameError):
    def __init__(self, msg):
        super().__init__(msg)


class ChallengeNotFoundError(GameError):
    """No such pending challenge: never made, or already accepted, declined or withdrawn."""

    def __init__(self, msg="No such pending challenge"):
        super().__init__(msg)


class TokenNotFoundError(GameError):
    """No such token, or not one of the caller's."""

    def __init__(self, msg="No such token"):
        super().__init__(msg)


class GameNotFoundError(GameError):
    def __init__(self, msg="No such game"):
        super().__init__(msg)


class NotYourTurnError(GameError):
    """The acting player is not allowed to make this move/action right now."""

    def __init__(self, msg="It is not that player's turn / that player is not in this game"):
        super().__init__(msg)


class VersionConflictError(GameError):
    """The game changed since the client's expected version (optimistic concurrency)."""

    def __init__(self, msg="The game has changed since your last read; refresh and retry"):
        super().__init__(msg)


class UserNotFoundError(GameError):
    def __init__(self, msg="No such user"):
        super().__init__(msg)


class UserExistsError(GameError):
    """A username, or an external id, is already taken by another user."""

    def __init__(self, msg="That username or external id is already taken"):
        super().__init__(msg)


class UserValidationError(GameError):
    """A username, provider or external id does not fit the rules above."""

    def __init__(self, msg):
        super().__init__(msg)


class AuthError(GameError):
    """
    The request is not authenticated: no token, an unknown, expired or revoked one,
    or a failed login. The api-endpoint answers ``401``.

    Login failures deliberately share one message, so it never says whether the
    username exists.
    """

    def __init__(self, msg="Authentication required: send Authorization: Bearer <token>"):
        super().__init__(msg)


class ForbiddenError(GameError):
    """Authenticated, but not allowed to do this. The api-endpoint answers ``403``."""

    def __init__(self, msg="You are not allowed to do that"):
        super().__init__(msg)
