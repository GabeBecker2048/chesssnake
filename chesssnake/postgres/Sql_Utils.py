import psycopg2
import importlib.resources
from os import getenv

from . import GameError

def load_env_sql_creds():
    return {
        "conn_str": getenv("CHESSDB_CONN_STR"),
        "name": getenv("CHESSDB_NAME"),
        "user": getenv("CHESSDB_USER"),
        "password": getenv("CHESSDB_PASS"),
        "host": getenv("CHESSDB_HOST", "localhost"),
        "port": getenv("CHESSDB_PORT", "5432")
    }


def load_sql_conn_str(prog_sql_creds: dict|None=None):
    env_sql_creds = load_env_sql_creds()
    prog_sql_creds = prog_sql_creds or {}

    # Merge dictionaries, with env_sql_creds having priority
    sql_creds = {**prog_sql_creds, **env_sql_creds}

    # create the connection string
    if sql_creds["conn_str"] is not None:
        conn_str = sql_creds["conn_str"]
    elif sql_creds["name"] is not None and sql_creds["user"] is not None and sql_creds["password"] is not None:
        conn_str = (
            "dbname='{name}' user='{user}' password='{password}' host='{host}' port='{port}'"
            .format(**sql_creds)
        )
    else:
        raise GameError.SQLAuthError()

    return conn_str


def sql_db_init(prog_sql_creds: dict|None=None):

    conn_str = load_sql_conn_str(prog_sql_creds)
    print("Initializing database...")

    try:
        # Gets the database initialization query
        db_init_fp = str(importlib.resources.files('chesssnake').joinpath('data/init.sql'))
        with open(db_init_fp, 'r') as db_init_file:
            db_init = db_init_file.read()

        # Initializes the database
        with psycopg2.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(db_init)  # Execute the initialization SQL
                conn.commit()
    except FileNotFoundError as e:
        # Handles the case where the init.sql file is not found
        print(f"Database initialization file not found: {e}")
        raise
    except psycopg2.OperationalError as e:
        # Handles issues related to the connection to the SQL database
        print(f"Error connecting to the database: {e}")
        raise
    except psycopg2.DatabaseError as e:
        # Handles issues during SQL execution
        print(f"Database error occurred while initializing: {e}")
        raise
    except Exception as e:
        # Handles any unexpected exceptions
        print(f"An unexpected error occurred: {e}")
        raise
    finally:
        print("Database initialization process completed.")


def execute_sql(statement: str, prog_sql_creds: dict|None=None, params=None):

    conn_str = load_sql_conn_str(prog_sql_creds)

    # connect to the database and execute the sql statement
    with psycopg2.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(statement, params)
            try:
                results = cur.fetchall()
                return results
            except psycopg2.ProgrammingError:
                return None
