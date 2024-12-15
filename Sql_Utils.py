import psycopg2
from os import getenv
import GameError

def load_sql_env():
    CHESSDB_NAME = getenv("CHESSDB_NAME")
    CHESSDB_USER = getenv("CHESSDB_USER")
    CHESSDB_PASS = getenv("CHESSDB_PASS")
    CHESSDB_HOST = getenv("CHESSDB_HOST")
    CHESSDB_PORT = getenv("CHESSDB_PORT")

    if CHESSDB_NAME is None or CHESSDB_USER is None:
        raise GameError.SQLAuthError()

    return CHESSDB_NAME, CHESSDB_USER, CHESSDB_PASS, CHESSDB_HOST, CHESSDB_PORT


def execute_sql(statement: str, params=None):
    # Reload the execute_sql creds every time a query is called
    # This is a very small performance hit, but ensures that we can dynamically change the db credentials
    CHESSDB_NAME, CHESSDB_USER, CHESSDB_PASS, CHESSDB_HOST, CHESSDB_PORT = load_sql_env()

    conn_str = f"dbname='{CHESSDB_NAME}' user='{CHESSDB_USER}'"
    if CHESSDB_PASS:
        conn_str += f" password='{CHESSDB_PASS}'"
    if CHESSDB_HOST:
        conn_str += f" host='{CHESSDB_HOST}'"
    if CHESSDB_PORT:
        conn_str += f" port='{CHESSDB_PORT}'"

    with psycopg2.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(statement, params)
            try:
                results = cur.fetchall()
                return results
            except psycopg2.ProgrammingError:
                return None
