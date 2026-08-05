class GameError(Exception):
    def __init__(self, msg):
        super().__init__(msg)


class SQLError(GameError):
    def __init__(self, msg):
        super().__init__(msg)


class SQLIdError(SQLError):
    def __init__(self, id_):
        msg = "\n".join(
            [
                "One of the given ids is invalid for a PostgreSQL database:",
                f"  id: {id_}",
                "All IDs must be BIGINT NOT NULL.",
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
                "Set it in any one of these places (later ones win):",
                "  1. In your config file, under the [database] table:",
                "       [database]",
                "       url = 'postgresql://user:password@localhost:5432/chesssnake'",
                "  2. As an environment variable:",
                "       CHESSSNAKE__DATABASE__URL='postgresql://user:password@localhost:5432/chesssnake'",
                "  3. On the command line:",
                "       chesssnake api-endpoint --database-url 'postgresql://user:password@localhost:5432/chesssnake'",
                "",
                "Both URL and keyword ('dbname=... user=...') connection strings are accepted.",
                "Run `chesssnake config show` to see the current settings and where each one came from.",
            ]
        )
        super().__init__(msg)


class ChallengeError(GameError):
    def __init__(self, msg):
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
