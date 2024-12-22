import psycopg2
from os import getenv
from . import GameError

def load_sql_env():
    CHESSDB_NAME = getenv("CHESSDB_NAME")
    CHESSDB_USER = getenv("CHESSDB_USER")
    CHESSDB_PASS = getenv("CHESSDB_PASS")
    CHESSDB_HOST = getenv("CHESSDB_HOST", "localhost")
    CHESSDB_PORT = getenv("CHESSDB_PORT", "5432")

    if CHESSDB_NAME is None or CHESSDB_USER is None or CHESSDB_PASS is None:
        raise GameError.SQLAuthError()

    return {
        "name": CHESSDB_NAME,
        "user": CHESSDB_USER,
        "password": CHESSDB_PASS,
        "host": CHESSDB_HOST,
        "port": CHESSDB_PORT
    }


def execute_sql(statement: str, params=None):
    # Reload the execute_sql creds every time a query is called
    # This is a very small performance hit, but ensures that we can dynamically change the db credentials
    sql_creds = load_sql_env()

    conn_str = (f"dbname='{sql_creds["name"]}' "
                f"user='{sql_creds["user"]}' "
                f"password='{sql_creds["password"]}' "
                f"host='{sql_creds["host"]}' "
                f"port='{sql_creds["port"]}'")

    with psycopg2.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(statement, params)
            try:
                results = cur.fetchall()
                return results
            except psycopg2.ProgrammingError:
                return None
