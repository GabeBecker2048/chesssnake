from contextlib import contextmanager

import psycopg2
from psycopg2 import pool, sql
from psycopg2.extensions import make_dsn, parse_dsn
from psycopg2.extras import RealDictCursor

from ..assets import asset_path
from . import errors

# Initialize the database connection pool
connection_pool = None

#: Database connected to when creating another database, since a connection must
#: target *some* database. Every PostgreSQL cluster has this one.
MAINTENANCE_DB = "postgres"


def require_dsn(dsn):
    """
    Validate that a database DSN was configured.

    This layer no longer reads the environment; the DSN is resolved by
    :mod:`chesssnake.config` and passed in. This is the one place that turns a
    missing value into the actionable :class:`~chesssnake.db.errors.SQLAuthError`.

    :param dsn: The configured database DSN, possibly ``None``.
    :type dsn: str or None
    :return: The DSN, unchanged.
    :rtype: str
    :raises errors.SQLAuthError: If no DSN is configured.
    """
    if not dsn:
        raise errors.SQLAuthError()
    return dsn


def admin_dsn(dsn, admin_db=MAINTENANCE_DB):
    """
    Derive a DSN for the maintenance database, plus the name of the target database.

    ``CREATE DATABASE`` cannot run on a connection to the database being created,
    so the target is swapped for the maintenance database. Every other connection
    parameter — credentials, port, ``sslmode``, a unix-socket ``host`` — is carried
    over untouched, because ``parse_dsn``/``make_dsn`` understand both the URL and
    the keyword forms of a libpq connection string.

    :param dsn: The configured database DSN, in either URL or keyword form.
    :type dsn: str
    :param admin_db: Database to connect to instead of the target one.
    :type admin_db: str
    :return: ``(admin_dsn, target_database_name)``.
    :rtype: tuple[str, str]
    :raises errors.SQLError: If the DSN cannot be parsed or names no database.
    """
    try:
        parsed = parse_dsn(require_dsn(dsn))
    except psycopg2.Error as e:
        raise errors.SQLError(f"Could not parse the database DSN: {e}")

    target = parsed.get("dbname")
    if not target:
        raise errors.SQLError("The database DSN does not name a database, so there is nothing to create.")
    return make_dsn(**{**parsed, "dbname": admin_db}), target


def initialize_connection_pool(dsn, minconn=1, maxconn=10):
    """
    Initializes a connection pool for PostgreSQL. To be called once at application startup.

    :param dsn: The database connection string.
    :type dsn: str
    :param minconn: Minimum number of connections in the pool.
    :param maxconn: Maximum number of connections in the pool.
    :raises errors.SQLAuthError: If no DSN is configured.
    :raises errors.SQLError: If the pool cannot be created.
    """
    global connection_pool
    try:
        connection_pool = pool.SimpleConnectionPool(minconn=minconn, maxconn=maxconn, dsn=require_dsn(dsn))
        if connection_pool:
            print("Database connection pool successfully initialized.")
    except psycopg2.Error as e:
        raise errors.SQLError(f"Failed to initialize database connection pool: {str(e)}")


def close_connection_pool():
    """
    Close every pooled connection and reset the pool.

    Safe to call when no pool was ever created, so teardown paths don't need to
    inspect the module global themselves.
    """
    global connection_pool
    if connection_pool is not None:
        connection_pool.closeall()
        connection_pool = None


def get_connection():
    """
    Retrieves a connection from the connection pool.
    :return: A connection object from the pool.
    """
    if not connection_pool:
        raise errors.SQLError(
            "Connection pool is not initialized.\n    Use chesssnake.db.sql.initialize_connection_pool"
        )
    return connection_pool.getconn()


def release_connection(conn):
    """
    Releases a database connection back to the pool.
    :param conn: The connection object to release.
    """
    if connection_pool and conn:
        connection_pool.putconn(conn)


def psql_db_init(dsn, schema_init=True):
    """
    Checks if the database exists and creates it if it does not, provided the user has sufficient permissions.

    Requires proper permissions to create the database.

    :param dsn: A URL-form database DSN naming the database to create.
    :type dsn: str
    :param schema_init: Boolean flag indicating whether to initialize the database schema after creating or ensuring
                        the database exists. If set to `True`, the function will call `db_schema_init`, which runs
                        the schema initialization script to set up the necessary database structure.
                        If `False`, the function will only ensure the database exists and will skip the schema
                        initialization step.
    :raises GameError: If there is a failure due to missing permissions or other SQL errors.
    """
    admin, db_name = admin_dsn(dsn)

    conn = None
    try:
        # Not `with psycopg2.connect(...)`: that context manager wraps the block in a
        # transaction, and CREATE DATABASE cannot run inside one. Autocommit has to be
        # set before any statement opens a transaction.
        conn = psycopg2.connect(admin)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone():
                print(f"Database '{db_name}' already exists.")
            else:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
                print(f"Database '{db_name}' created successfully.")
    except psycopg2.errors.InsufficientPrivilege as e:
        raise errors.SQLError(
            f"Insufficient privileges to create the database '{db_name}'. Ensure the user has appropriate permissions:\n{e}"
        )
    except psycopg2.Error as e:
        raise errors.SQLError(f"Database creation error: {e}")
    finally:
        if conn is not None:
            conn.close()

    if schema_init:
        psql_db_schema_init(dsn)


def psql_db_schema_init(dsn):
    """
    Initializes the database schema by executing the `init.sql` script.

    Connects independently to the database and executes the
    schema initialization script, and disconnects afterward.
    The initialization script is required to set up the database schema for chesssnake.

    :param dsn: The database connection string.
    :type dsn: str
    :raises GameError: If the initialization file is not found, if there are connection issues,
                       or if there are SQL errors during initialization.
    """
    conn = None
    try:
        # Connect directly rather than through the pool: the schema may need to
        # exist before the pool is created.
        conn = psycopg2.connect(require_dsn(dsn))
        db_init_fp = asset_path("init.sql")
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
            f"Try reinstalling chesssnake."
        )
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


@contextmanager
def transaction():
    """
    Run several statements in one transaction on a single pooled connection.

    Yields a ``RealDictCursor``. Commits when the ``with`` block exits cleanly and
    rolls back on any exception, then returns the connection to the pool. Use this
    when a read and a dependent write must be atomic (e.g. ``SELECT ... FOR UPDATE``
    followed by an ``UPDATE`` with an engine computation in between).

    :raises errors.SQLError: on any ``psycopg2`` error (after rolling back).
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except psycopg2.Error as e:
        if conn is not None:
            conn.rollback()
        raise errors.SQLError(f"SQL execution error: {e}")
    except Exception:
        # Non-SQL error (e.g. a ChessError from the engine mutate): roll back the
        # transaction but let the original exception propagate unchanged.
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            release_connection(conn)
