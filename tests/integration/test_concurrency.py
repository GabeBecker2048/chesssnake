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

GROUP, WHITE, BLACK = 90, 91, 92


@pytest.fixture
def game(api_client):
    """A freshly created game to mutate."""
    resp = api_client.post("/v1/games", json={"group_id": GROUP, "white_id": WHITE, "black_id": BLACK})
    assert resp.status_code == 200
    return resp.json()


def _bump(observed, errors_seen, hold):
    """Run one no-op apply_game_change, recording the version it observed."""
    from chesssnake.db import operations as ops

    def mutate(row, _history):
        observed.append(int(row["version"]))
        # Widen the window so an unserialized second caller would read the same
        # version before this one commits.
        time.sleep(hold)
        columns = {
            "fen": row["fen"],
            "draw": row["draw"],
            "status": row["status"],
            "termination": row["termination"],
        }
        return columns, [], None

    try:
        ops.apply_game_change(GROUP, WHITE, BLACK, mutate)
    except Exception as e:  # surfaced by the assertions below
        errors_seen.append(e)


def test_concurrent_changes_serialize(game):
    """Two simultaneous mutations must see different versions, not the same one."""
    observed: list[int] = []
    errors_seen: list[Exception] = []
    threads = [threading.Thread(target=_bump, args=(observed, errors_seen, 0.15)) for _ in range(2)]

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
    threads = [threading.Thread(target=_bump, args=(observed, errors_seen, 0.05)) for _ in range(4)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors_seen, f"apply_game_change raised: {errors_seen}"
    assert sorted(observed) == [1, 2, 3, 4]

    state = api_client.get(f"/v1/games/{GROUP}/{WHITE}/{BLACK}").json()
    assert state["version"] == 5


def test_concurrent_moves_do_not_lose_a_ply(api_client):
    """The same guarantee through the public HTTP surface, with the real engine."""
    group, white, black = 93, 94, 95
    api_client.post("/v1/games", json={"group_id": group, "white_id": white, "black_id": black})

    results: list[int] = []
    lock = threading.Lock()

    def play(move):
        resp = api_client.post(f"/v1/games/{group}/{white}/{black}/moves", json={"move": move})
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

    history = api_client.get(f"/v1/games/{group}/{white}/{black}/history").json()
    assert len(history["moves"]) == 1
