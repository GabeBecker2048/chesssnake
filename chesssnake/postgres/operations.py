"""
Server-side database operations for the chesssnake API.

These are the pure PostgreSQL operations that back the REST API. They deal only
in primitive values (ints, strings, dicts) — the chess engine lives on the
client, so nothing here imports ``chesslib``. Every operation goes through
``execute_psql`` (parameterized, committing, RealDictCursor rows keyed by
lowercase column name).
"""

from . import GameError
from .PSql_Utils import execute_psql, initialize_connection_pool, psql_db_init, validate_ids

# The serialized starting position, matching Board.disassemble_board's format.
INITIAL_BOARD = (
    "R1 N1 B1 Q1 K1 B1 N1 R1;P1 P1 P1 P1 P1 P1 P1 P1;-- -- -- -- -- -- -- --;"
    "-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;"
    "P0 P0 P0 P0 P0 P0 P0 P0;R0 N0 B0 Q0 K0 B0 N0 R0"
)


def db_init(sql_creds=None, create_database=False):
    """
    Initializes the database environment: optionally creates the database, sets up
    the connection pool, and initializes the schema.

    If ``create_database`` is True, attempts to create the database if it does not
    exist (requires appropriate permissions). If ``sql_creds`` is not provided,
    credentials are read from the ``CHESSDB_*`` environment variables.

    :raises GameError.GameError: If any step of initialization fails.
    """
    try:
        if create_database:
            psql_db_init(sql_creds=sql_creds)
        initialize_connection_pool(sql_creds=sql_creds)
        print("Database initialized successfully.")
    except Exception as e:
        raise GameError.GameError(f"Database initialization error:\n{str(e)}")


# --- Games -----------------------------------------------------------------

def game_get_or_create(group_id, white_id, black_id, white_name="", black_name=""):
    """
    Loads the game for ``(group_id, white_id, black_id)``, creating a fresh one if
    it does not exist.

    :return: The raw game row as a plain dict (keys: ``board``, ``turn``,
        ``pawnmove``, ``draw``, ``moved``, ``status``, ``wname``, ``bname`` and the
        id columns).
    :rtype: dict
    """
    validate_ids(white_id, black_id, group_id)

    query = """
        INSERT INTO Games (GroupId, WhiteId, BlackId, Board, Turn, PawnMove, Draw, Moved, Status, WName, BName)
        VALUES (%(group_id)s, %(white_id)s, %(black_id)s, %(board)s, %(turn)s, %(pawnmove)s, %(draw)s, %(moved)s, %(status)s, %(wname)s, %(bname)s)
        ON CONFLICT (GroupId, WhiteId, BlackId) DO NOTHING;

        SELECT * FROM Games WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
    """
    params = {
        "group_id": group_id,
        "white_id": white_id,
        "black_id": black_id,
        "board": INITIAL_BOARD,
        "turn": 0,
        "pawnmove": None,
        "draw": None,
        "moved": "000000",
        "status": 0,
        "wname": white_name,
        "bname": black_name,
    }
    row = execute_psql(query, params=params)[0]
    return dict(row)


def game_update(group_id, white_id, black_id, board, turn, pawnmove, draw, moved, status, wname, bname):
    """Persists the full state of a game."""
    validate_ids(white_id, black_id, group_id)

    query = """
        UPDATE Games
        SET Board = %(board)s,
            Turn = %(turn)s,
            PawnMove = %(pawnmove)s,
            Draw = %(draw)s,
            Moved = %(moved)s,
            Status = %(status)s,
            WName = %(wname)s,
            BName = %(bname)s
        WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
    """
    params = {
        "board": board, "turn": turn, "pawnmove": pawnmove, "draw": draw,
        "moved": moved, "status": status, "wname": wname, "bname": bname,
        "group_id": group_id, "white_id": white_id, "black_id": black_id,
    }
    execute_psql(query, params=params)


def game_update_draw(group_id, white_id, black_id, draw, status):
    """Updates only the draw offer and status of a game."""
    validate_ids(white_id, black_id, group_id)
    query = """
        UPDATE Games
        SET Draw = %(draw)s, Status = %(status)s
        WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
    """
    params = {"draw": draw, "status": status, "group_id": group_id, "white_id": white_id, "black_id": black_id}
    execute_psql(query, params=params)


def game_clear_draw(group_id, white_id, black_id):
    """Clears any pending draw offer on a game."""
    validate_ids(white_id, black_id, group_id)
    query = """
        UPDATE Games
        SET Draw = NULL
        WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
    """
    params = {"group_id": group_id, "white_id": white_id, "black_id": black_id}
    execute_psql(query, params=params)


def game_delete(group_id, white_id, black_id):
    """Deletes a game."""
    validate_ids(white_id, black_id, group_id)
    query = """
        DELETE FROM Games
        WHERE GroupId = %(group_id)s AND WhiteId = %(white_id)s AND BlackId = %(black_id)s
    """
    params = {"group_id": group_id, "white_id": white_id, "black_id": black_id}
    execute_psql(query, params=params)


def current_games(player_id, group_id=0):
    """Returns the list of opponent ids that ``player_id`` has active games with."""
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
            WHERE GroupId = %s
        )
        SELECT OpponentId
        FROM PlayerResult
        WHERE OpponentId IS NOT NULL;
    """
    rows = execute_psql(query, params=(player_id, player_id, group_id))
    return [r["opponentid"] for r in rows]


def game_exists(player1, player2, group_id=0):
    """
    Returns ``{"white_id", "black_id"}`` for an existing game between the two
    players, or ``None``.
    """
    validate_ids(player1, player2, group_id)
    query = """
        SELECT WhiteId, BlackId
        FROM Games
        WHERE GroupId = %s AND (
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

    :raises GameError.ChallengeError: On self-challenge, an existing game, or a
        duplicate outstanding challenge.
    """
    validate_ids(challenger, opponent, group_id)

    if challenger == opponent:
        raise GameError.ChallengeError("You can't challenge yourself.")

    if game_exists(challenger, opponent, group_id):
        raise GameError.ChallengeError(
            f"There is an unresolved game between {challenger} and {opponent} already!"
        )

    existing = challenge_exists(challenger, opponent, group_id)
    if existing is None:
        challenge_create(challenger, opponent, group_id)
        return False
    elif challenger == existing["challenger"]:
        raise GameError.ChallengeError(
            f"You have already challenged {opponent}! Wait for them to accept."
        )

    # A reciprocal challenge exists: accept it by deleting the stored challenge.
    challenge_delete(existing["challenger"], existing["challenged"], group_id)
    return True
