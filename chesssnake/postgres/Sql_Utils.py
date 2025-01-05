import psycopg2
from psycopg2 import pool
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
import importlib.resources
from os import getenv
from . import GameError

# Initialize the database connection pool
connection_pool = None


def load_env_sql_creds():
    """
    Loads SQL credentials from environment variables.
    :return: A dictionary with the SQL credentials.
    """
    return {
        "conn_str": getenv("CHESSDB_CONN_STR"),
        "name": getenv("CHESSDB_NAME"),
        "user": getenv("CHESSDB_USER"),
        "password": getenv("CHESSDB_PASS"),
        "host": getenv("CHESSDB_HOST", "localhost"),
        "port": getenv("CHESSDB_PORT", "5432")
    }

def load_sql_conn_str(sql_creds=None):
    """
    Constructs an SQL connection string from programmatic or environment-provided credentials.
    :param sql_creds: Optional programmatic SQL credentials.
    :return: A valid PostgreSQL connection string.
    """
    env_sql_creds = load_env_sql_creds()
    sql_creds = sql_creds or {}

    # Merge dictionaries, with sql_creds having priority
    sql_creds = {**env_sql_creds, **sql_creds}

    # create the connection string
    if sql_creds.get("conn_str"):
        return sql_creds["conn_str"]
    elif sql_creds.get("name") and sql_creds.get("user") and sql_creds.get("password"):
        return (
            "dbname='{name}' user='{user}' password='{password}' host='{host}' port='{port}'"
            .format(**sql_creds)
        )
    elif sql_creds.get("user") and sql_creds.get("password"):
        return (
            "user='{user}' password='{password}' host='{host}' port='{port}'"
            .format(**sql_creds)
        )
    else:
        raise GameError.SQLAuthError()

def initialize_connection_pool(minconn=1, maxconn=10, sql_creds=None):
    """
    Initializes a connection pool for PostgreSQL. To be called once at the application startup.
    :param minconn: Minimum number of connections in the pool.
    :param maxconn: Maximum number of connections in the pool.
    :param sql_creds: Dictionary of SQL credentials.
    """
    global connection_pool
    try:
        connection_pool = pool.SimpleConnectionPool(
            minconn=minconn,
            maxconn=maxconn,
            dsn=load_sql_conn_str(sql_creds=sql_creds)
        )
        if connection_pool:
            print("Database connection pool successfully initialized.")
    except psycopg2.Error as e:
        print(f"Error initializing connection pool: {e}")
        raise GameError.SQLAuthError("Failed to initialize database connection pool.")


def get_connection():
    """
    Retrieves a connection from the connection pool.
    :return: A connection object from the pool.
    """
    if not connection_pool:
        raise GameError.SQLAuthError("Connection pool is not initialized.")
    return connection_pool.getconn()


def release_connection(conn):
    """
    Releases a database connection back to the pool.
    :param conn: The connection object to release.
    """
    if connection_pool and conn:
        connection_pool.putconn(conn)


def create_database_if_not_exists(sql_creds=None):
    """
    Checks if the database exists and creates it if it does not, provided the user has sufficient permissions.

    Requires proper permissions to create the database.

    :param sql_creds: Dictionary of SQL credentials, including the "name" of the database to be created. Example:
                      {"name": str, "user": str, "password": str, "host": str, "port": str}.
                      If not provided, environment variables are used.
    :type sql_creds: dict or None
    :raises GameError: If there is a failure due to missing permissions or other SQL errors.
    """
    # Use modified credentials without a database name to connect to the PostgreSQL server
    admin_conn_creds = sql_creds.copy() if sql_creds else load_env_sql_creds()
    admin_conn_creds["name"] = None  # Remove db-name for admin-level connection

    db_name = sql_creds.get("name") if sql_creds else admin_conn_creds.get("name")
    if not db_name:
        raise ValueError("Database name is not provided in the credentials.")

    try:
        # Establish a connection to the server (not to a specific database)
        with psycopg2.connect(load_sql_conn_str(admin_conn_creds)) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                # Check if the database exists
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                exists = cur.fetchone()

                if not exists:
                    # Attempt to create the database
                    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
                    print(f"Database '{db_name}' created successfully.")
                else:
                    print(f"Database '{db_name}' already exists.")
    except psycopg2.errors.InsufficientPrivilege:
        raise GameError.SQLAuthError(
            f"Insufficient privileges to create the database '{db_name}'. Ensure the user has appropriate permissions."
        )
    except psycopg2.Error as e:
        print(f"Error while checking/creating database: {e}")
        raise GameError.GameError(f"Database creation error: {str(e)}")

def sql_db_init():
    """
    Initializes the database schema by executing the `init.sql` script.
    """
    conn = None
    try:
        conn = get_connection()
        db_init_fp = str(importlib.resources.files('chesssnake').joinpath('data/init.sql'))
        with open(db_init_fp, 'r') as db_init_file:
            init_script = db_init_file.read()

        # Execute the schema initialization script
        with conn.cursor() as cur:
            cur.execute(init_script)
            conn.commit()

        print("Database schema initialized successfully.")

    except FileNotFoundError:
        raise GameError.GameError("Database initialization file not found. Please provide an 'init.sql' file.")
    except psycopg2.Error as e:
        print(f"Error during database initialization: {e}")
        raise GameError.GameError(f"Database initialization error: {e}")
    finally:
        if conn:
            release_connection(conn)


def execute_sql(statement, params=None):
    """
    Executes a SQL statement using a connection from the pool.
    :param statement: SQL query string, can include placeholders (%(placeholder)s).
    :param params: Dictionary of parameters for the query (optional).
    :return: Query results in case of SELECT queries, or None otherwise.
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(statement, params)
            # Fetch results if the query is a SELECT
            if cur.description:
                return cur.fetchall()
            conn.commit()
    except psycopg2.Error as e:
        print(f"SQL execution error: {e}")
        raise GameError.GameError(f"SQL execution error: {e}")
    finally:
        if conn:
            release_connection(conn)