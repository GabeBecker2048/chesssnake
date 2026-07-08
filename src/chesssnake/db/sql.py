from os import getenv

import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor

from ..assets import asset_path
from . import errors

# Initialize the database connection pool
connection_pool = None


def load_env_psql_creds():
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


def load_psql_conn_str(sql_creds=None):
    """
    Constructs an SQL connection string from programmatic or environment-provided credentials.
    :param sql_creds: Optional programmatic SQL credentials.
    :return: A valid PostgreSQL connection string.
    """
    env_sql_creds = load_env_psql_creds()
    sql_creds = sql_creds or {}

    # Merge dictionaries, with sql_creds having priority
    _sql_creds = {**env_sql_creds, **sql_creds}

    # create the connection string
    if _sql_creds.get("conn_str"):
        return _sql_creds["conn_str"]
    elif _sql_creds.get("name") and _sql_creds.get("user") and _sql_creds.get("password"):
        return "dbname='{name}' user='{user}' password='{password}' host='{host}' port='{port}'".format(**_sql_creds)
    else:
        raise errors.SQLAuthError()


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
            dsn=load_psql_conn_str(sql_creds=sql_creds)
        )
        if connection_pool:
            print("Database connection pool successfully initialized.")
    except psycopg2.Error as e:
        raise errors.SQLError(f"Failed to initialize database connection pool: {str(e)}")


def get_connection():
    """
    Retrieves a connection from the connection pool.
    :return: A connection object from the pool.
    """
    if not connection_pool:
        raise errors.SQLError("Connection pool is not initialized.\n"
                                 "    Use chesssnake.db.sql.initialize_connection_pool")
    return connection_pool.getconn()


def release_connection(conn):
    """
    Releases a database connection back to the pool.
    :param conn: The connection object to release.
    """
    if connection_pool and conn:
        connection_pool.putconn(conn)


def psql_db_init(sql_creds=None, schema_init=True):
    """
    Checks if the database exists and creates it if it does not, provided the user has sufficient permissions.

    Requires proper permissions to create the database.

    :param sql_creds: Dictionary of SQL credentials, including the "name" of the database to be created.
                      {"name": str, "user": str, "password": str, "host": str, "port": str}.
                      If not provided, environment variables are used.
    :param schema_init: Boolean flag indicating whether to initialize the database schema after creating or ensuring
                        the database exists. If set to `True`, the function will call `db_schema_init`, which runs
                        the schema initialization script to set up the necessary database structure.
                        If `False`, the function will only ensure the database exists and will skip the schema
                        initialization step.
    :type sql_creds: dict or None
    :raises GameError: If there is a failure due to missing permissions or other SQL errors.
    """
    # Merge provided credentials over the environment defaults so the database
    # name can come from either source.
    creds = {**load_env_psql_creds(), **(sql_creds or {})}

    db_name = creds.get("name")
    if not db_name:
        raise ValueError("Database name is not provided in the credentials.")

    # Use modified credentials without a database name to connect to the PostgreSQL server
    admin_conn_creds = creds.copy()
    admin_conn_creds["name"] = None  # Remove db-name for admin-level connection

    try:
        # Establish a connection to the server (not to a specific database)
        with psycopg2.connect(load_psql_conn_str(admin_conn_creds)) as conn:
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
    except psycopg2.errors.InsufficientPrivilege as e:
        raise errors.SQLError(
            f"Insufficient privileges to create the database '{db_name}'. Ensure the user has appropriate permissions:\n{e}"
        )
    except psycopg2.Error as e:
        raise errors.SQLError(f"Database creation error: {e}")

    if schema_init:
        psql_db_schema_init(sql_creds=sql_creds)


def psql_db_schema_init(sql_creds=None):
    """
    Initializes the database schema by executing the `init.sql` script.

    Connects independently to the database and executes the
    schema initialization script, and disconnects afterward.
    The initialization script is required to set up the database schema for chesssnake.

    :param sql_creds: Dictionary of SQL credentials, including the "name" of the database to connect to and initialize.
                      Example: {"name": str, "user": str, "password": str, "host": str, "port": str}.
                      If not provided, environment variables are used to load the credentials.
    :type sql_creds: dict or None
    :raises GameError: If the initialization file is not found, if there are connection issues,
                       or if there are SQL errors during initialization.
    """
    conn = None
    try:
        # Establish a direct connection using environment-based or provided credentials
        conn = psycopg2.connect(load_psql_conn_str(sql_creds=sql_creds))
        db_init_fp = asset_path('init.sql')
        with open(db_init_fp) as db_init_file:
            init_script = db_init_file.read()

        # Execute the schema initialization script
        with conn.cursor() as cur:
            cur.execute(init_script)
            conn.commit()

        print("Database schema initialized successfully.")

    except FileNotFoundError as e:
        raise errors.SQLError(
            f"{e}\n"
            f"Database initialization file not found, likely due to corrupt or modified installation.\n"
            f"Try reinstalling chesssnake.")
    except psycopg2.Error as e:
        raise errors.SQLError(f"Database initialization error:\n{e}")
    finally:
        if conn:
            conn.close()

def validate_ids(*ids: int):
    """
    Validates that all provided IDs are integers and within the PostgreSQL BIGINT range.

    :param ids: Variable-length list of IDs (challenger, challenged, gid).
    :raises ValueError: If any ID is invalid.
    """

    BIGINT_MIN = -9223372036854775808
    BIGINT_MAX = 9223372036854775807

    for id_ in ids:
        if not isinstance(id_, int):
            raise errors.SQLIdError(id_)
        if not (BIGINT_MIN <= id_ <= BIGINT_MAX):
            raise errors.SQLIdError(id_)

def execute_psql(statement, params=None):
    """
    Executes a SQL statement using a connection from the pool.

    The statement is always committed on success and rolled back on failure, so
    writes are persisted (even when the statement also returns rows, e.g. an
    ``INSERT ... RETURNING`` or a combined ``INSERT; SELECT``) and a failed
    transaction is never handed back to the pool.

    :param statement: SQL query string, can include placeholders (%(placeholder)s).
    :param params: Dictionary of parameters for the query (optional).
    :return: A list of result rows for statements that return data, otherwise None.
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(statement, params)
            # Fetch results if the statement returned any rows (e.g. a SELECT)
            result = cur.fetchall() if cur.description else None
        conn.commit()
        return result
    except psycopg2.Error as e:
        if conn is not None:
            conn.rollback()
        raise errors.SQLError(f"SQL execution error: {e}")
    finally:
        if conn is not None:
            release_connection(conn)
