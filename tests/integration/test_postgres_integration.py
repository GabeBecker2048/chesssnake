"""
Integration tests for the PostgreSQL persistence layer.

These spin up a real, throwaway PostgreSQL instance via ``pgserver`` (no Docker or
system Postgres required), initialize the chesssnake schema against it, and
exercise the connector end-to-end: game creation, persistence round-trips,
en-passant state, draw persistence, and the challenge lifecycle.
"""

import tempfile

import pytest

pgserver = pytest.importorskip("pgserver")

from chesssnake.postgres import PSql_Utils as U
from chesssnake.postgres.Game import Game, Challenge


@pytest.fixture(scope="session")
def db():
    """Start an embedded Postgres, init the pool + schema, tear it all down after."""
    with tempfile.TemporaryDirectory() as pgdata:
        server = pgserver.get_server(pgdata)
        creds = {"conn_str": server.get_uri()}
        U.initialize_connection_pool(sql_creds=creds)
        U.psql_db_schema_init(sql_creds=creds)
        try:
            yield server
        finally:
            if U.connection_pool is not None:
                U.connection_pool.closeall()
            server.cleanup()


@pytest.fixture(autouse=True)
def clean_tables(db):
    """Start every test from empty tables so ids can be reused freely."""
    U.execute_psql("TRUNCATE Games, Challenges")
    yield


def test_schema_creates_expected_tables(db):
    rows = U.execute_psql(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    tables = {r["table_name"] for r in rows}
    assert {"games", "challenges"} <= tables


def test_game_is_persisted_and_reloaded(db):
    game = Game(white_id=1, black_id=2, group_id=10, white_name="Bob", black_name="Phil")
    game.move("e4")
    game.move("e5")
    game.move("Nc3")
    game.update_db()

    # A fresh Game with the same ids must load the persisted state, not a new board.
    reloaded = Game(white_id=1, black_id=2, group_id=10)
    assert str(reloaded) == str(game)
    assert reloaded.turn == game.turn == 1
    assert reloaded.wname == "Bob"
    assert reloaded.bname == "Phil"


def test_new_game_starts_from_initial_position(db):
    game = Game(white_id=3, black_id=4, group_id=10, white_name="A", black_name="B")
    assert str(game) == str(Game(white_id=99, black_id=98, group_id=11).board)
    assert game.turn == 0
    assert game.draw is None


def test_en_passant_target_round_trips(db):
    # A pawn double-step sets the en-passant target square (board.two_moveP);
    # it must survive a serialize -> store -> reload cycle (exercises get_coords()).
    game = Game(white_id=5, black_id=6, group_id=10, white_name="A", black_name="B")
    game.move("e4")
    game.update_db()
    assert game.board.two_moveP is not None

    reloaded = Game(white_id=5, black_id=6, group_id=10)
    assert reloaded.board.two_moveP is not None
    assert reloaded.board.two_moveP == game.board.two_moveP
    assert reloaded.board.two_moveP.c_notation == "e4"


def test_draw_offer_persists_with_auto_sql(db):
    game = Game(white_id=7, black_id=8, group_id=10, white_name="A", black_name="B", auto_sql=True)
    game.draw_offer(7)  # white (whose turn it is) offers a draw

    reloaded = Game(white_id=7, black_id=8, group_id=10)
    assert reloaded.draw == 0  # 0 == white offered


def test_challenge_lifecycle(db):
    # First challenge is created and pending.
    accepted = Challenge.challenge(challenger=100, opponent=200, gid=10)
    assert accepted is False
    assert Challenge.exists(100, 200, gid=10) is not None

    # The reciprocal challenge accepts (and clears) the pending one.
    accepted_back = Challenge.challenge(challenger=200, opponent=100, gid=10)
    assert accepted_back is True
    assert Challenge.exists(100, 200, gid=10) is None


def test_challenge_rejects_self(db):
    from chesssnake.postgres import GameError

    with pytest.raises(GameError.ChallengeError):
        Challenge.challenge(challenger=300, opponent=300, gid=10)