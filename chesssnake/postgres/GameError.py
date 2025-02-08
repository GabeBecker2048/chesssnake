class GameError(BaseException):
    def __init__(self, msg):
        super().__init__(msg)

class SQLError(GameError):
    def __init__(self, msg):
        super().__init__(msg)

class SQLIdError(SQLError):
    def __init__(self, white_id, black_id, group_id):
        msg = "\n".join([
            "One of the following ids is invalid for a PostgreSQL database:",
            f"  white id: {white_id}",
            f"  black id: {black_id}",
            f"  group id: {group_id}",
            "IDs must be BIGINT NOT NULL."
        ])
        super().__init__(msg)

class SQLAuthError(SQLError):
    def __init__(self):
        msg = "\n".join([
            "The SQL database credentials are invalid.",
            "There are four ways to set the database credentials:"
            "Option 1: Set the CHESSDB_CONN_STR environment variable to a valid connection string:"
            "  CHESSDB_CONN_STR='postgresql://user:password@localhost:5432/name'",
            "Option 2: Make sure these environment variables are set:",
            "  CHESSDB_NAME, CHESSDB_USER, CHESSDB_PASS",
            "  It is also recommended that you also set CHESSDB_HOST and CHESSDB_PORT",
            "Option 3: Set the database connection string when declaring a Game object:",
            "  creds = {'conn_str':'postgresql://user:password@localhost:5432/name'}",
            "  db_init(sql_creds=creds)",
            "Option 4, set the database connection credentials when declaring a Game object. For example:",
            "  creds = {'name':'name', 'user':'user', 'pass':'password'}",
            "  db_init(sql_creds=creds)",
        ])
        super().__init__(msg)

class ChallengeError(GameError):
    def __init__(self, msg):
        super().__init__(msg)
