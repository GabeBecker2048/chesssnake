"""
Database operations for the chesssnake API — backend-agnostic.

These are the queries that back the REST API, written as SQLAlchemy Core
expressions so one definition compiles correctly for both PostgreSQL and SQLite.
They deal only in primitive values (ints, strings, dicts): the chess engine runs
on the server, and **nothing here imports it** — engine-derived values like the
initial FEN are passed in, and the engine logic itself arrives as the ``mutate``
callback of :func:`apply_game_change`.

Result rows come back keyed by lowercase column name on both backends (see
:mod:`chesssnake.db.schema` for why the schema is declared lowercase), which is
what :class:`chesssnake.dto.GameState` expects.

Each public function opens its own transaction. The private ``_`` variants take a
connection instead, so a caller that needs several operations to be atomic — as
:func:`challenge` does — can run them together.
"""

from sqlalchemy import case, delete, func, select, update

from . import errors
from .engine import backend, locked_transaction, transaction
from .schema import challenges, games, moves

#: The columns ``apply_game_change``'s mutate callback returns to persist.
_STATE_COLUMNS = ("fen", "draw", "status", "termination")

#: PostgreSQL BIGINT bounds. SQLite's INTEGER is also a signed 64-bit value, so
#: the same range applies to both backends.
_BIGINT_MIN = -9223372036854775808
_BIGINT_MAX = 9223372036854775807


def validate_ids(*ids: int) -> None:
    """
    Validate that all provided ids are integers within the 64-bit signed range.

    :param ids: The ids to check (player ids, group ids).
    :raises errors.SQLIdError: If any id is not an int or is out of range.
    """
    for id_ in ids:
        if not isinstance(id_, int) or isinstance(id_, bool):
            raise errors.SQLIdError(id_)
        if not (_BIGINT_MIN <= id_ <= _BIGINT_MAX):
            raise errors.SQLIdError(id_)


def _triple(table, group_id, white_id, black_id):
    """The WHERE clause matching one ``(group, white, black)`` triple."""
    return (table.c.groupid == group_id) & (table.c.whiteid == white_id) & (table.c.blackid == black_id)


def _current_game_select(group_id, white_id, black_id, *columns):
    """Select the current (highest-generation) game row for a triple."""
    return (
        select(*(columns or [games]))
        .where(_triple(games, group_id, white_id, black_id))
        .order_by(games.c.generation.desc())
        .limit(1)
    )


def _row_to_dict(row):
    return dict(row) if row is not None else None


# --- Initialization --------------------------------------------------------


def db_init(url, create_database=False, **engine_kwargs):
    """
    Initialize the database environment: optionally create the database, create the
    engine, and create the schema.

    :param url: The database URL.
    :param create_database: Whether to create the database if it is missing.
    :raises errors.GameError: If any step of initialization fails.
    """
    from . import engine as engine_module
    from . import schema

    try:
        if create_database:
            parsed = engine_module.parse_url(url)
            print(engine_module.backend_module(parsed.get_backend_name()).create_database(parsed))
        eng = engine_module.initialize_engine(url, **engine_kwargs)
        schema.create_all(eng)
        print("Database initialized successfully.")
    except errors.GameError:
        # Already a well-formed persistence error (e.g. SQLAuthError, whose message
        # explains exactly how to configure the URL); don't flatten its type.
        raise
    except Exception as e:
        raise errors.GameError(f"Database initialization error:\n{str(e)}")


# --- Games -----------------------------------------------------------------


def game_get_or_create(group_id, white_id, black_id, initial_fen, initial_key, white_name="", black_name=""):
    """
    Load the **current** game for ``(group_id, white_id, black_id)`` — creating a
    fresh one when there is none, or when the current game is already over (a new
    generation, so past games are preserved).

    The engine-derived ``initial_fen``/``initial_key`` are passed in so this layer
    stays engine-free.

    :return: The raw current game row as a plain dict.
    :rtype: dict
    """
    validate_ids(white_id, black_id, group_id)
    insert = backend().insert

    with transaction() as conn:
        latest = (
            conn.execute(_current_game_select(group_id, white_id, black_id, games.c.generation, games.c.status))
            .mappings()
            .first()
        )

        if latest is None:
            generation, create = 1, True
        elif int(latest["status"]) == 0:  # current game is still in play -> return it
            generation, create = int(latest["generation"]), False
        else:  # current game is over -> start the next generation
            generation, create = int(latest["generation"]) + 1, True

        if create:
            ids = {"groupid": group_id, "whiteid": white_id, "blackid": black_id, "generation": generation}
            # ON CONFLICT DO NOTHING makes this race-safe: a concurrent creator may
            # have inserted the same generation, and the re-select below is what
            # settles which row we return.
            conn.execute(
                insert(games)
                .values(
                    **ids,
                    fen=initial_fen,
                    draw=None,
                    status=0,
                    termination=None,
                    version=1,
                    wname=white_name,
                    bname=black_name,
                )
                .on_conflict_do_nothing(index_elements=["groupid", "whiteid", "blackid", "generation"])
            )
            conn.execute(
                insert(moves)
                .values(**ids, ply=0, san=None, positionkey=initial_key)
                .on_conflict_do_nothing(index_elements=["groupid", "whiteid", "blackid", "generation", "ply"])
            )

        # Re-select the current game: authoritative after any insert.
        row = conn.execute(_current_game_select(group_id, white_id, black_id)).mappings().first()
        return _row_to_dict(row)


def game_get(group_id, white_id, black_id, generation=None):
    """Return the game row (current if ``generation`` is ``None``, else that one), or ``None``."""
    validate_ids(white_id, black_id, group_id)
    if generation is None:
        stmt = _current_game_select(group_id, white_id, black_id)
    else:
        stmt = select(games).where(_triple(games, group_id, white_id, black_id) & (games.c.generation == generation))
    with transaction() as conn:
        return _row_to_dict(conn.execute(stmt).mappings().first())


def game_archive(group_id, white_id, black_id):
    """Return a summary of every game (generation) for a triple, oldest first."""
    validate_ids(white_id, black_id, group_id)
    stmt = (
        select(games.c.generation, games.c.fen, games.c.status, games.c.termination, games.c.updatedat)
        .where(_triple(games, group_id, white_id, black_id))
        .order_by(games.c.generation)
    )
    with transaction() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [
        {
            "generation": r["generation"],
            "fen": r["fen"],
            "status": int(r["status"]),
            "termination": r["termination"],
            "updated_at": r["updatedat"].isoformat() if r["updatedat"] is not None else None,
        }
        for r in rows
    ]


def game_history(group_id, white_id, black_id, generation):
    """Return the played moves (``[{"ply", "san"}]``, ordered) for one game generation."""
    validate_ids(white_id, black_id, group_id)
    stmt = (
        select(moves.c.ply, moves.c.san)
        .where(
            _triple(moves, group_id, white_id, black_id) & (moves.c.generation == generation) & moves.c.san.is_not(None)
        )
        .order_by(moves.c.ply)
    )
    with transaction() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [{"ply": r["ply"], "san": r["san"]} for r in rows]


def apply_game_change(group_id, white_id, black_id, mutate, expected_version=None):
    """
    Atomically read a game (with its move history), transform it, and write it back.

    Locks the current game row, loads the ``moves`` history, optionally enforces
    ``expected_version`` (optimistic concurrency), calls ``mutate(row, history)`` —
    which runs the engine — then persists the new columns (bumping ``version``) and
    appends any new move rows. The whole read-modify-write is one transaction, so
    concurrent actions on the same game cannot clobber each other.

    How the lock is taken differs by backend and is deliberately explicit: see
    :func:`chesssnake.db.postgres.lock_current_game` (``SELECT … FOR UPDATE``) and
    :func:`chesssnake.db.sqlite.lock_current_game` (already exclusive, because the
    transaction opened with ``BEGIN IMMEDIATE``).

    :param mutate: ``(row_dict, history) -> (columns, new_move_rows, result)`` where
        ``history`` is ``{"position_keys": [...], "move_sans": [...], "max_ply": int}``,
        ``columns`` holds the state columns, and ``new_move_rows`` is a list of
        ``{"ply", "san", "position_key"}`` to insert.
    :param expected_version: if given and it doesn't match the stored version, raise.
    :return: the ``result`` returned by ``mutate``.
    :raises errors.GameNotFoundError: if the game does not exist.
    :raises errors.VersionConflictError: if ``expected_version`` is stale.
    """
    validate_ids(white_id, black_id, group_id)
    module = backend()

    with locked_transaction() as conn:
        row = module.lock_current_game(conn, _current_game_select(group_id, white_id, black_id)).mappings().first()
        if row is None:
            raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
        if expected_version is not None and int(row["version"]) != int(expected_version):
            raise errors.VersionConflictError(
                f"Expected version {expected_version} but the game is at version {row['version']}"
            )
        generation = int(row["generation"])

        move_rows = (
            conn.execute(
                select(moves.c.ply, moves.c.san, moves.c.positionkey)
                .where(_triple(moves, group_id, white_id, black_id) & (moves.c.generation == generation))
                .order_by(moves.c.ply)
            )
            .mappings()
            .all()
        )
        history = {
            "position_keys": [r["positionkey"] for r in move_rows],
            "move_sans": [r["san"] for r in move_rows if r["san"] is not None],
            "max_ply": max((r["ply"] for r in move_rows), default=0),
        }

        columns, new_move_rows, result = mutate(dict(row), history)

        conn.execute(
            update(games)
            .where(_triple(games, group_id, white_id, black_id) & (games.c.generation == generation))
            .values(
                **{column: columns[column] for column in _STATE_COLUMNS},
                version=games.c.version + 1,
            )
        )
        for move in new_move_rows:
            conn.execute(
                moves.insert().values(
                    groupid=group_id,
                    whiteid=white_id,
                    blackid=black_id,
                    generation=generation,
                    ply=move["ply"],
                    san=move["san"],
                    positionkey=move["position_key"],
                )
            )
    return result


def game_delete(group_id, white_id, black_id, generation=None):
    """
    Delete a game and its moves — the current game if ``generation`` is ``None``,
    else the specified generation.
    """
    validate_ids(white_id, black_id, group_id)

    # Resolving "the current generation" and deleting it must be atomic, or two
    # concurrent deletes can both resolve the same generation.
    with locked_transaction() as conn:
        target = generation
        if target is None:
            target = conn.execute(
                select(func.max(games.c.generation)).where(_triple(games, group_id, white_id, black_id))
            ).scalar()
        if target is None:
            return

        # Two statements rather than one: a single execute containing both, as the
        # pre-0.9.0 SQL did, is rejected outright by SQLite's driver.
        conn.execute(delete(moves).where(_triple(moves, group_id, white_id, black_id) & (moves.c.generation == target)))
        conn.execute(delete(games).where(_triple(games, group_id, white_id, black_id) & (games.c.generation == target)))


def current_games(player_id, group_id=0):
    """
    Return the opponent ids that ``player_id`` has an **active** (in-play) game with.

    Only games with ``status = 0`` count, so a finished game does not keep showing
    up as current.
    """
    validate_ids(player_id, group_id)
    # The opponent is whichever side the player is not. Restricting to games the
    # player is actually in makes the old query's "ELSE NULL … WHERE IS NOT NULL"
    # filter unnecessary.
    opponent = case(
        (games.c.whiteid == player_id, games.c.blackid),
        (games.c.blackid == player_id, games.c.whiteid),
    ).label("opponentid")
    stmt = select(opponent).where(
        (games.c.groupid == group_id)
        & (games.c.status == 0)
        & ((games.c.whiteid == player_id) | (games.c.blackid == player_id))
    )
    with transaction() as conn:
        rows = conn.execute(stmt).mappings().all()
    return [r["opponentid"] for r in rows]


def game_exists(player1, player2, group_id=0):
    """
    Return ``{"white_id", "black_id"}`` for an **active** game between two players,
    or ``None``. Finished games don't count, so a rematch is allowed.
    """
    validate_ids(player1, player2, group_id)
    with transaction() as conn:
        return _game_exists(conn, player1, player2, group_id)


def _game_exists(conn, player1, player2, group_id):
    stmt = select(games.c.whiteid, games.c.blackid).where(
        (games.c.groupid == group_id)
        & (games.c.status == 0)
        & (
            ((games.c.whiteid == player1) & (games.c.blackid == player2))
            | ((games.c.whiteid == player2) & (games.c.blackid == player1))
        )
    )
    row = conn.execute(stmt).mappings().first()
    return None if row is None else {"white_id": row["whiteid"], "black_id": row["blackid"]}


def game_record(player1, player2, group_id=0):
    """
    Win/draw/loss record between two players across all **finished** games (any
    generation, either color arrangement) in a group.

    Status values: 1 = white won, 2 = black won, 3 = draw (0 = in play, excluded).

    :return: ``{"player1", "player2", "player1_wins", "player2_wins", "draws"}``.
    :rtype: dict
    """
    validate_ids(player1, player2, group_id)

    def wins(player):
        return func.count().filter(
            ((games.c.whiteid == player) & (games.c.status == 1))
            | ((games.c.blackid == player) & (games.c.status == 2))
        )

    stmt = select(
        wins(player1).label("p1_wins"),
        wins(player2).label("p2_wins"),
        func.count().filter(games.c.status == 3).label("draws"),
    ).where(
        (games.c.groupid == group_id)
        & (games.c.status != 0)
        & (
            ((games.c.whiteid == player1) & (games.c.blackid == player2))
            | ((games.c.whiteid == player2) & (games.c.blackid == player1))
        )
    )
    with transaction() as conn:
        row = conn.execute(stmt).mappings().one()
    return {
        "player1": player1,
        "player2": player2,
        "player1_wins": int(row["p1_wins"]),
        "player2_wins": int(row["p2_wins"]),
        "draws": int(row["draws"]),
    }


# --- Challenges ------------------------------------------------------------


def challenge_exists(player1, player2, group_id=0):
    """Return ``{"challenger", "challenged"}`` for a pending challenge, or ``None``."""
    validate_ids(player1, player2, group_id)
    with transaction() as conn:
        return _challenge_exists(conn, player1, player2, group_id)


def _challenge_exists(conn, player1, player2, group_id):
    stmt = select(challenges.c.challenger, challenges.c.challenged).where(
        (challenges.c.groupid == group_id)
        & (
            ((challenges.c.challenger == player1) & (challenges.c.challenged == player2))
            | ((challenges.c.challenger == player2) & (challenges.c.challenged == player1))
        )
    )
    row = conn.execute(stmt).mappings().first()
    return None if row is None else {"challenger": row["challenger"], "challenged": row["challenged"]}


def challenge_create(challenger, challenged, group_id=0):
    """Create a pending challenge (no-op if it already exists)."""
    validate_ids(challenger, challenged, group_id)
    with transaction() as conn:
        _challenge_create(conn, challenger, challenged, group_id)


def _challenge_create(conn, challenger, challenged, group_id):
    conn.execute(
        backend()
        .insert(challenges)
        .values(groupid=group_id, challenger=challenger, challenged=challenged)
        .on_conflict_do_nothing(index_elements=["groupid", "challenger", "challenged"])
    )


def challenge_delete(challenger, challenged, group_id=0):
    """Delete a pending challenge."""
    validate_ids(challenger, challenged, group_id)
    with transaction() as conn:
        _challenge_delete(conn, challenger, challenged, group_id)


def _challenge_delete(conn, challenger, challenged, group_id):
    """Delete a challenge, returning how many rows that removed."""
    result = conn.execute(
        delete(challenges).where(
            (challenges.c.groupid == group_id)
            & (challenges.c.challenger == challenger)
            & (challenges.c.challenged == challenged)
        )
    )
    return result.rowcount


def challenge(challenger, opponent, group_id=0):
    """
    Issue (or accept) a challenge between two players.

    If a reciprocal challenge already exists it is accepted (deleted) and ``True``
    is returned; otherwise a new challenge is created and ``False`` is returned.

    The whole check-and-mutate runs in **one** transaction. Before 0.9.0 these were
    four separate connections, so two players challenging each other simultaneously
    could both observe "no existing challenge" and each create one, leaving a
    reciprocal pair that nobody had accepted.

    :raises errors.ChallengeError: On self-challenge, an existing game, or a
        duplicate outstanding challenge.
    """
    validate_ids(challenger, opponent, group_id)

    if challenger == opponent:
        raise errors.ChallengeError("You can't challenge yourself.")

    with locked_transaction() as conn:
        if _game_exists(conn, challenger, opponent, group_id):
            raise errors.ChallengeError(f"There is an unresolved game between {challenger} and {opponent} already!")

        existing = _challenge_exists(conn, challenger, opponent, group_id)
        if existing is None:
            _challenge_create(conn, challenger, opponent, group_id)
            return False
        if challenger == existing["challenger"]:
            raise errors.ChallengeError(f"You have already challenged {opponent}! Wait for them to accept.")

        # A reciprocal challenge exists: accept it by deleting the stored challenge.
        # Two concurrent accepts can both read the same pending row on PostgreSQL
        # (SQLite serializes them), so the row count is what decides which one won.
        if _challenge_delete(conn, existing["challenger"], existing["challenged"], group_id) == 0:
            raise errors.ChallengeError("That challenge is no longer pending; refresh and try again.")
        return True
