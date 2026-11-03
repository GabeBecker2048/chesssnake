"""
Concurrency guarantees for ``apply_game_change``, on every backend.

This is the test that justifies the whole dialect-shim design. ``apply_game_change``
is a read-modify-write with the chess engine running in the middle, and it must be
serialized or two simultaneous moves will be computed against the same position and
one will be lost.

PostgreSQL gets that from ``SELECT … FOR UPDATE``. SQLite has no row locks, and —
importantly — SQLAlchemy compiles ``FOR UPDATE`` **away** on SQLite rather than
raising, so a naive port would look correct and silently lose moves. SQLite instead
takes the write lock for the whole transaction via ``BEGIN IMMEDIATE``.

These tests assert the observable consequence rather than the mechanism, so they
hold for whichever backend is under test.
"""

import threading
import time

import pytest

pytest.importorskip("sqlalchemy")

pytestmark = pytest.mark.integration

GROUP = 90


@pytest.fixture
def game(api_client, pair):
    """A freshly created game to mutate; returns its id."""
    white, black = pair
    resp = api_client.post("/v1/games", json={"group_id": GROUP, "white_id": white, "black_id": black})
    assert resp.status_code == 200
    return resp.json()["id"]


def _bump(game, observed, errors_seen, hold):
    """Run one no-op apply_game_change, recording the version it observed."""
    from chesssnake.db import operations as ops

    def mutate(row, _history, _now):
        observed.append(int(row["version"]))
        # Widen the window so an unserialized second caller would read the same
        # version before this one commits.
        time.sleep(hold)
        return ops.GameChange(fen=row["fen"], draw=row["draw"])

    try:
        ops.apply_game_change(game, mutate)
    except Exception as e:  # surfaced by the assertions below
        errors_seen.append(e)


def test_concurrent_changes_serialize(game):
    """Two simultaneous mutations must see different versions, not the same one."""
    observed: list[int] = []
    errors_seen: list[Exception] = []
    threads = [threading.Thread(target=_bump, args=(game, observed, errors_seen, 0.15)) for _ in range(2)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors_seen, f"apply_game_change raised: {errors_seen}"
    # If the read-modify-write were not serialized, both callers would read
    # version 1 and the second write would clobber the first.
    assert sorted(observed) == [1, 2], f"expected serialized versions [1, 2], got {sorted(observed)}"


def test_version_reflects_every_applied_change(game, api_client):
    """Each serialized mutation bumps the version exactly once."""
    observed: list[int] = []
    errors_seen: list[Exception] = []
    threads = [threading.Thread(target=_bump, args=(game, observed, errors_seen, 0.05)) for _ in range(4)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors_seen, f"apply_game_change raised: {errors_seen}"
    assert sorted(observed) == [1, 2, 3, 4]

    state = api_client.get(f"/v1/games/{game}").json()
    assert state["version"] == 5


def test_concurrent_moves_do_not_lose_a_ply(api_client, game):
    """The same guarantee through the public HTTP surface, with the real engine."""

    results: list[int] = []
    lock = threading.Lock()

    def play(move):
        resp = api_client.post(f"/v1/games/{game}/moves", json={"move": move})
        with lock:
            results.append(resp.status_code)

    # Both are legal opening moves for white; exactly one can be applied first, and
    # the other must then be rejected as illegal rather than silently overwriting it.
    threads = [threading.Thread(target=play, args=(m,)) for m in ("e4", "d4")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == [200, 400], f"expected one applied and one rejected, got {sorted(results)}"

    history = api_client.get(f"/v1/games/{game}/history").json()
    assert len(history["moves"]) == 1


def test_creating_a_game_while_a_move_is_in_flight(game, api_client, pair):
    """
    ``POST /v1/games`` must not fail while another request holds the write lock.

    Regression. ``game_get_or_create`` reads the latest generation and then
    inserts based on what it read, but it used to run under a plain (deferred)
    ``BEGIN``. On SQLite that starts the connection as a reader which must
    upgrade to a writer for the INSERT, and SQLite refuses that upgrade with
    SQLITE_BUSY *immediately* when another writer holds the lock, because
    ``busy_timeout`` does not apply to the upgrade path. The result was a 500
    ``database is locked`` from a perfectly ordinary request.

    It was invisible while every route ran on the event loop, because two
    requests could never be in the database at once. Moving the routes to the
    threadpool made it reachable, and deterministic: four out of four.
    """
    errors_seen: list[Exception] = []
    observed: list[int] = []

    # Hold the write lock on one game for long enough to overlap the creates.
    holder = threading.Thread(target=_bump, args=(game, observed, errors_seen, 0.4))
    holder.start()
    time.sleep(0.1)

    created: list[int] = []
    failed: list[tuple[int, int, str]] = []
    lock = threading.Lock()

    def create(i):
        # A different triple each time, so this is not contending for the same
        # row: it is purely the lock-upgrade path being exercised.
        white, black = pair
        resp = api_client.post("/v1/games", json={"group_id": 300 + i, "white_id": white, "black_id": black})
        with lock:
            (created if resp.status_code == 200 else failed).append(
                i if resp.status_code == 200 else (i, resp.status_code, resp.text[:120])
            )

    threads = [threading.Thread(target=create, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    holder.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "a create thread never finished"
    assert not errors_seen, f"the in-flight move failed: {errors_seen}"
    assert not failed, f"creating a game failed while a move was in flight: {failed}"
    assert sorted(created) == [0, 1, 2, 3]


def test_concurrent_user_creation_assigns_distinct_ids(api_client):
    """
    Server-assigned ids under contention: every create gets its own id.

    SQLite serializes the inserts through BEGIN IMMEDIATE and hands out rowids;
    PostgreSQL draws from the identity sequence. Either way no two concurrent
    creates may collide or fail.
    """
    ids: list[int] = []
    failed: list[str] = []
    lock = threading.Lock()

    def create(i):
        resp = api_client.post("/v1/users", json={"username": f"racer{i}"})
        with lock:
            if resp.status_code == 201:
                ids.append(resp.json()["id"])
            else:
                failed.append(resp.text[:200])

    threads = [threading.Thread(target=create, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not failed, failed
    assert len(set(ids)) == 8


def test_concurrent_duplicate_usernames_create_exactly_one(api_client):
    """The unique index is the guarantee; exactly one of the racers may win."""
    statuses: list[int] = []
    lock = threading.Lock()

    def create():
        resp = api_client.post("/v1/users", json={"username": "Popular"})
        with lock:
            statuses.append(resp.status_code)

    threads = [threading.Thread(target=create) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(statuses) == [201] + [409] * 5
