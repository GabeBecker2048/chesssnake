"""
Server-side database operations for the chesssnake API.

These are the pure PostgreSQL operations that back the REST API. They deal only
in primitive values (ints, strings, dicts) — the chess engine lives on the
client, so nothing here imports the ``engine``. Every operation goes through
``execute_psql`` (parameterized, committing, RealDictCursor rows keyed by
lowercase column name).
"""

from . import errors
from .sql import execute_psql, initialize_connection_pool, psql_db_init, transaction, validate_ids


def db_init(sql_creds=None, create_database=False):
    """
    Initializes the database environment: optionally creates the database, sets up
    the connection pool, and initializes the schema.

    If ``create_database`` is True, attempts to create the database if it does not
    exist (requires appropriate permissions). If ``sql_creds`` is not provided,
    credentials are read from the ``CHESSDB_*`` environment variables.

    :raises errors.GameError: If any step of initialization fails.
    """
    try:
        if create_database:
            psql_db_init(sql_creds=sql_creds)
        initialize_connection_pool(sql_creds=sql_creds)
        print("Database initialized successfully.")
    except Exception as e:
        raise errors.GameError(f"Database initialization error:\n{str(e)}")


# --- Games -----------------------------------------------------------------


# A triple can own many games (one per Generation); the "current" game is the row
# with the highest Generation. `_IDS` is the shared WHERE clause matching the triple.
_IDS = "GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s"


def game_get_or_create(group_id, white_id, black_id, initial_fen, initial_key, white_name="", black_name=""):
    """
    Load the **current** game for ``(group_id, white_id, black_id)`` — creating a
    fresh one when there is none, or when the current game is already over (a new
    Generation, so past games are preserved).

    The engine-derived ``initial_fen``/``initial_key`` are passed in so this layer
    stays engine-free.

    :return: The raw current game row as a plain dict.
    :rtype: dict
    """
    validate_ids(white_id, black_id, group_id)
    ids = {"group_id": group_id, "white_id": white_id, "black_id": black_id}

    with transaction() as cur:
        cur.execute(f"SELECT Generation, Status FROM Games WHERE {_IDS} ORDER BY Generation DESC LIMIT 1", ids)
        latest = cur.fetchone()
        if latest is None:
            generation, create = 1, True
        elif int(latest["status"]) == 0:  # current game is still in play -> return it
            generation, create = int(latest["generation"]), False
        else:  # current game is over -> start the next generation
            generation, create = int(latest["generation"]) + 1, True

        if create:
            params = {
                **ids,
                "gen": generation,
                "fen": initial_fen,
                "key": initial_key,
                "wname": white_name,
                "bname": black_name,
            }
            cur.execute(
                """
                INSERT INTO Games (GroupId, WhiteId, BlackId, Generation, Fen, Draw, Status, Termination, Version, WName, BName)
                VALUES (%(group_id)s, %(white_id)s, %(black_id)s, %(gen)s, %(fen)s, NULL, 0, NULL, 1, %(wname)s, %(bname)s)
                ON CONFLICT (GroupId, WhiteId, BlackId, Generation) DO NOTHING
                """,
                params,
            )
            cur.execute(
                """
                INSERT INTO Moves (GroupId, WhiteId, BlackId, Generation, Ply, San, PositionKey)
                VALUES (%(group_id)s, %(white_id)s, %(black_id)s, %(gen)s, 0, NULL, %(key)s)
                ON CONFLICT (GroupId, WhiteId, BlackId, Generation, Ply) DO NOTHING
                """,
                params,
            )

        # re-select the current (max-generation) game — authoritative after any insert
        cur.execute(f"SELECT * FROM Games WHERE {_IDS} ORDER BY Generation DESC LIMIT 1", ids)
        return dict(cur.fetchone())


def game_get(group_id, white_id, black_id, generation=None):
    """Return the game row (current if ``generation`` is ``None``, else that one), or ``None``."""
    validate_ids(white_id, black_id, group_id)
    ids = {"group_id": group_id, "white_id": white_id, "black_id": black_id}
    if generation is None:
        rows = execute_psql(f"SELECT * FROM Games WHERE {_IDS} ORDER BY Generation DESC LIMIT 1", params=ids)
    else:
        rows = execute_psql(
            f"SELECT * FROM Games WHERE {_IDS} AND Generation = %(gen)s", params={**ids, "gen": generation}
        )
    return dict(rows[0]) if rows else None


def game_archive(group_id, white_id, black_id):
    """Return a summary of every game (generation) for a triple, oldest first."""
    validate_ids(white_id, black_id, group_id)
    ids = {"group_id": group_id, "white_id": white_id, "black_id": black_id}
    rows = execute_psql(
        f"SELECT Generation, Fen, Status, Termination, UpdatedAt FROM Games WHERE {_IDS} ORDER BY Generation",
        params=ids,
    )
    return [
        {
            "generation": r["generation"],
            "fen": r["fen"],
            "status": int(r["status"]),
            "termination": r["termination"],
            "updated_at": r["updatedat"].isoformat() if r["updatedat"] is not None else None,
        }
        for r in (rows or [])
    ]


def game_history(group_id, white_id, black_id, generation):
    """Return the played moves (``[{"ply", "san"}]``, ordered) for one game generation."""
    validate_ids(white_id, black_id, group_id)
    query = f"""
        SELECT Ply, San FROM Moves
        WHERE {_IDS} AND Generation = %(gen)s AND San IS NOT NULL
        ORDER BY Ply
    """
    rows = execute_psql(
        query, params={"group_id": group_id, "white_id": white_id, "black_id": black_id, "gen": generation}
    )
    return [{"ply": r["ply"], "san": r["san"]} for r in (rows or [])]


# The Games columns apply_game_change's mutate callback returns to persist.
_STATE_COLUMNS = ("fen", "draw", "status", "termination")


def apply_game_change(group_id, white_id, black_id, mutate, expected_version=None):
    """
    Atomically read a game (with its move history), transform it, and write it back.

    Locks the game row with ``SELECT ... FOR UPDATE``, loads the ``Moves`` history,
    optionally enforces ``expected_version`` (optimistic concurrency), calls
    ``mutate(row, history)`` — which runs the engine — then persists the new game
    columns (bumping ``Version``) and appends any new ``Moves`` rows. The whole
    read-modify-write is one transaction, so concurrent actions on the same game
    can't clobber each other. This layer stays engine-free; the chess logic lives
    entirely in the ``mutate`` callback.

    :param mutate: ``(row_dict, history) -> (columns, new_move_rows, result)`` where
        ``history`` is ``{"position_keys": [...], "move_sans": [...], "max_ply": int}``,
        ``columns`` holds the :data:`_STATE_COLUMNS`, and ``new_move_rows`` is a list
        of ``{"ply", "san", "position_key"}`` to insert.
    :param expected_version: if given and it doesn't match the stored version, raise.
    :return: the ``result`` returned by ``mutate``.
    :raises errors.GameNotFoundError: if the game does not exist.
    :raises errors.VersionConflictError: if ``expected_version`` is stale.
    """
    validate_ids(white_id, black_id, group_id)
    ids = {"group_id": group_id, "white_id": white_id, "black_id": black_id}

    with transaction() as cur:
        # lock the current (max-generation) game — mutations always target it
        cur.execute(f"SELECT * FROM Games WHERE {_IDS} ORDER BY Generation DESC LIMIT 1 FOR UPDATE", ids)
        row = cur.fetchone()
        if row is None:
            raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
        if expected_version is not None and int(row["version"]) != int(expected_version):
            raise errors.VersionConflictError(
                f"Expected version {expected_version} but the game is at version {row['version']}"
            )
        gen = {**ids, "gen": int(row["generation"])}

        cur.execute(f"SELECT Ply, San, PositionKey FROM Moves WHERE {_IDS} AND Generation = %(gen)s ORDER BY Ply", gen)
        move_rows = cur.fetchall()
        history = {
            "position_keys": [r["positionkey"] for r in move_rows],
            "move_sans": [r["san"] for r in move_rows if r["san"] is not None],
            "max_ply": max((r["ply"] for r in move_rows), default=0),
        }

        columns, new_move_rows, result = mutate(dict(row), history)

        cur.execute(
            f"""
            UPDATE Games
            SET Fen = %(fen)s, Draw = %(draw)s, Status = %(status)s, Termination = %(termination)s,
                Version = Version + 1
            WHERE {_IDS} AND Generation = %(gen)s
            """,
            {**{c: columns[c] for c in _STATE_COLUMNS}, **gen},
        )
        for mv in new_move_rows:
            cur.execute(
                """
                INSERT INTO Moves (GroupId, WhiteId, BlackId, Generation, Ply, San, PositionKey)
                VALUES (%(group_id)s, %(white_id)s, %(black_id)s, %(gen)s, %(ply)s, %(san)s, %(key)s)
                """,
                {**gen, "ply": mv["ply"], "san": mv["san"], "key": mv["position_key"]},
            )
    return result


def game_delete(group_id, white_id, black_id, generation=None):
    """Delete a game and its moves — the current game if ``generation`` is ``None``,
    else the specified generation."""
    validate_ids(white_id, black_id, group_id)
    # COALESCE picks the given generation, or the current (max) one when it is NULL
    query = f"""
        DELETE FROM Moves
        WHERE {_IDS} AND Generation = COALESCE(%(gen)s, (SELECT MAX(Generation) FROM Games WHERE {_IDS}));

        DELETE FROM Games
        WHERE {_IDS} AND Generation = COALESCE(%(gen)s, (SELECT MAX(Generation) FROM Games WHERE {_IDS}))
    """
    params = {"group_id": group_id, "white_id": white_id, "black_id": black_id, "gen": generation}
    execute_psql(query, params=params)


def current_games(player_id, group_id=0):
    """Returns the opponent ids that ``player_id`` has an **active** (in-play) game with.

    Only games with ``Status = 0`` count (a triple has at most one active game), so a
    finished game is excluded and no opponent is listed more than once.
    """
    validate_ids(player_id, group_id)
    query = """
        WITH PlayerResult AS (
            SELECT
                CASE
                    WHEN WhiteId = %s THEN BlackId
                    WHEN BlackId = %s THEN WhiteId
                    ELSE NULL
                END AS OpponentId
            FROM Games
            WHERE GroupId = %s AND Status = 0
        )
        SELECT OpponentId
        FROM PlayerResult
        WHERE OpponentId IS NOT NULL;
    """
    rows = execute_psql(query, params=(player_id, player_id, group_id))
    return [r["opponentid"] for r in rows]


def game_exists(player1, player2, group_id=0):
    """
    Returns ``{"white_id", "black_id"}`` for an **active** (in-play) game between the
    two players, or ``None``. Finished games don't count — so a rematch is allowed
    once the previous game ends.
    """
    validate_ids(player1, player2, group_id)
    query = """
        SELECT WhiteId, BlackId
        FROM Games
        WHERE GroupId = %s AND Status = 0 AND (
            (WhiteId = %s AND BlackId = %s) OR
            (WhiteId = %s AND BlackId = %s)
        )
    """
    rows = execute_psql(query, params=(group_id, player1, player2, player2, player1))
    if rows:
        return {"white_id": rows[0]["whiteid"], "black_id": rows[0]["blackid"]}
    return None


# --- Challenges ------------------------------------------------------------


def challenge_exists(player1, player2, group_id=0):
    """Returns ``{"challenger", "challenged"}`` for a pending challenge, or ``None``."""
    validate_ids(player1, player2, group_id)
    query = """
        SELECT Challenger, Challenged
        FROM Challenges
        WHERE GroupId = %(gid)s AND (
            (Challenger = %(player1)s AND Challenged = %(player2)s) OR
            (Challenger = %(player2)s AND Challenged = %(player1)s)
        )
    """
    rows = execute_psql(query, params={"gid": group_id, "player1": player1, "player2": player2})
    if rows:
        return {"challenger": rows[0]["challenger"], "challenged": rows[0]["challenged"]}
    return None


def challenge_create(challenger, challenged, group_id=0):
    """Creates a pending challenge (no-op if it already exists)."""
    validate_ids(challenger, challenged, group_id)
    query = """
        INSERT INTO Challenges (GroupId, Challenger, Challenged)
        VALUES (%(gid)s, %(challenger)s, %(challenged)s)
        ON CONFLICT (GroupId, Challenger, Challenged) DO NOTHING
    """
    execute_psql(query, params={"gid": group_id, "challenger": challenger, "challenged": challenged})


def challenge_delete(challenger, challenged, group_id=0):
    """Deletes a pending challenge."""
    validate_ids(challenger, challenged, group_id)
    query = """
        DELETE FROM Challenges
        WHERE GroupId = %(gid)s AND Challenger = %(challenger)s AND Challenged = %(challenged)s
    """
    execute_psql(query, params={"gid": group_id, "challenger": challenger, "challenged": challenged})


def challenge(challenger, opponent, group_id=0):
    """
    Issues (or accepts) a challenge between two players.

    If a reciprocal challenge already exists it is accepted (deleted) and ``True``
    is returned; otherwise a new challenge is created and ``False`` is returned.
    Runs the whole check-and-mutate sequence server-side so concurrent clients
    stay consistent.

    :raises errors.ChallengeError: On self-challenge, an existing game, or a
        duplicate outstanding challenge.
    """
    validate_ids(challenger, opponent, group_id)

    if challenger == opponent:
        raise errors.ChallengeError("You can't challenge yourself.")

    if game_exists(challenger, opponent, group_id):
        raise errors.ChallengeError(f"There is an unresolved game between {challenger} and {opponent} already!")

    existing = challenge_exists(challenger, opponent, group_id)
    if existing is None:
        challenge_create(challenger, opponent, group_id)
        return False
    elif challenger == existing["challenger"]:
        raise errors.ChallengeError(f"You have already challenged {opponent}! Wait for them to accept.")

    # A reciprocal challenge exists: accept it by deleting the stored challenge.
    challenge_delete(existing["challenger"], existing["challenged"], group_id)
    return True
