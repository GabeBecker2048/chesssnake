class GameError(BaseException):
    def __init__(self, msg):
        super().__init__(msg)

class SQLIdError(GameError):
    def __init__(self, white_id, black_id, group_id):
        msg = (f"One of the following ids is invalid for a PostgreSQL db: \n"
               f"  {white_id}\n"
               f"  {black_id}\n"
               f"  {group_id}\n"
               f"ids must be BIGINT NOT NULL")
        super().__init__(msg)

class SQLAuthError(GameError):
    def __init__(self):
        msg = ("The SQL database conditionals are invalid. Make sure these environment variables are set:\n"
               "  CHESSDB_NAME CHESSDB_USER\n"
               "It is also recommended to have these variables set too:\n"
               " CHESSDB_PASS CHESSDB_HOST CHESSDB_PORT")
        super().__init__(msg)

class ChallengeError(GameError):
    def __init__(self, msg):
        super().__init__(msg)
