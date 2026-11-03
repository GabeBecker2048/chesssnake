"""
Challenges: how games are normally created, on both backends.

A user challenges another; accepting it creates the game, in the same transaction
that consumes the challenge. The concurrency tests at the bottom are the ones that
matter most: two accepts of one challenge, an accept racing a withdrawal, and two
players challenging each other at the same moment must each end in exactly one
consistent outcome, which on PostgreSQL depends on the delete-first accept and the
pair lock (see ``ops.challenge_accept`` and ``db.postgres.lock_pair``).
"""

import threading

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def alice_bob(users, as_user):
    alice, bob = users("alice", "bob")
    return alice, bob, as_user(alice), as_user(bob)


def _challenge(api_client, headers, opponent, **extra):
    return api_client.post("/v1/challenges", json={"opponent_id": opponent, **extra}, headers=headers)


def test_challenge_then_accept_creates_the_game(api_client, alice_bob):
    alice, bob, as_alice, as_bob = alice_bob
    resp = _challenge(api_client, as_alice, bob, color="white", group_id=3)
    assert resp.status_code == 201
    challenge = resp.json()
    assert challenge["challenger_id"] == alice and challenge["challenged_id"] == bob
    assert (challenge["challenger_name"], challenge["challenged_name"]) == ("alice", "bob")
    assert challenge["color"] == "white" and challenge["group_id"] == 3

    incoming = api_client.get("/v1/challenges", params={"direction": "incoming"}, headers=as_bob).json()["challenges"]
    outgoing = api_client.get("/v1/challenges", params={"direction": "outgoing"}, headers=as_alice).json()["challenges"]
    assert [c["id"] for c in incoming] == [c["id"] for c in outgoing] == [challenge["id"]]
    assert api_client.get("/v1/challenges", params={"direction": "outgoing"}, headers=as_bob).json() == {
        "challenges": []
    }

    accepted = api_client.post(f"/v1/challenges/{challenge['id']}/accept", headers=as_bob)
    assert accepted.status_code == 201
    game = accepted.json()
    assert (game["white_id"], game["black_id"], game["group_id"], game["status"]) == (alice, bob, 3, 0)
    assert api_client.get(f"/v1/challenges/{challenge['id']}", headers=as_bob).status_code == 404, "consumed"
    assert api_client.post(f"/v1/games/{game['id']}/moves", json={"move": "e4"}, headers=as_alice).status_code == 200


@pytest.mark.parametrize("color,alice_is_white", [("white", True), ("black", False)])
def test_the_challenger_gets_the_colour_they_asked_for(api_client, alice_bob, color, alice_is_white):
    alice, bob, as_alice, as_bob = alice_bob
    cid = _challenge(api_client, as_alice, bob, color=color).json()["id"]
    game = api_client.post(f"/v1/challenges/{cid}/accept", headers=as_bob).json()
    assert (game["white_id"] == alice) is alice_is_white


def test_random_colours_are_decided_on_acceptance(api_client, users, as_user):
    alice, *others = users("alice", "b1", "b2", "b3", "b4", "b5", "b6", "b7", "b8")
    whites = set()
    for other in others:
        cid = _challenge(api_client, as_user(alice), other).json()["id"]
        whites.add(api_client.post(f"/v1/challenges/{cid}/accept", headers=as_user(other)).json()["white_id"] == alice)
    assert whites == {True, False}, "eight random draws all came out the same (1 in 128)"


def test_decline_and_withdraw(api_client, users, as_user):
    alice, bob, carol = users("alice", "bob", "carol")
    first = _challenge(api_client, as_user(alice), bob).json()["id"]
    assert api_client.delete(f"/v1/challenges/{first}", headers=as_user(bob)).status_code == 204  # declined
    second = _challenge(api_client, as_user(alice), bob).json()["id"]
    assert api_client.delete(f"/v1/challenges/{second}", headers=as_user(carol)).status_code == 404  # not hers
    assert api_client.delete(f"/v1/challenges/{second}", headers=as_user(alice)).status_code == 204  # withdrawn
    assert api_client.post(f"/v1/challenges/{second}/accept", headers=as_user(bob)).status_code == 404


def test_refused_challenges(api_client, alice_bob, users):
    alice, bob, as_alice, as_bob = alice_bob
    (carol,) = users("carol")

    def refused(resp, status, fragment):
        assert resp.status_code == status, resp.text
        assert fragment in resp.json()["detail"]

    refused(_challenge(api_client, as_alice, alice), 409, "yourself")
    refused(_challenge(api_client, as_alice, 999999), 404, "999999")
    first = _challenge(api_client, as_alice, bob).json()["id"]
    refused(_challenge(api_client, as_alice, bob), 409, "already challenged")
    refused(_challenge(api_client, as_bob, alice), 409, f"accept challenge {first}")
    assert _challenge(api_client, as_bob, alice, group_id=2).status_code == 201, "another group is another matter"

    api_client.post(f"/v1/challenges/{first}/accept", headers=as_bob)
    refused(_challenge(api_client, as_bob, alice), 409, "in progress")

    api_client.patch(f"/v1/users/{carol}", json={"disabled": True})
    refused(_challenge(api_client, as_alice, carol), 409, "disabled")


def test_only_the_challenged_player_accepts(api_client, alice_bob):
    alice, bob, as_alice, _ = alice_bob
    cid = _challenge(api_client, as_alice, bob).json()["id"]
    resp = api_client.post(f"/v1/challenges/{cid}/accept", headers=as_alice)
    assert resp.status_code == 403
    assert api_client.get(f"/v1/challenges/{cid}", headers=as_alice).status_code == 200, "and it is still pending"


def test_an_accept_after_the_game_already_started_keeps_the_challenge(api_client, alice_bob):
    alice, bob, as_alice, as_bob = alice_bob
    cid = _challenge(api_client, as_alice, bob).json()["id"]
    api_client.post("/v1/games", json={"white_id": bob, "black_id": alice})  # an admin starts one meanwhile
    resp = api_client.post(f"/v1/challenges/{cid}/accept", headers=as_bob)
    assert resp.status_code == 409 and "already in progress" in resp.json()["detail"]
    assert api_client.get(f"/v1/challenges/{cid}", headers=as_bob).status_code == 200


def test_an_admin_challenges_and_accepts_on_behalf(api_client, alice_bob):
    alice, bob, *_ = alice_bob
    challenge = api_client.post("/v1/challenges", json={"opponent_id": bob, "player_id": alice}).json()
    assert challenge["challenger_id"] == alice
    game = api_client.post(f"/v1/challenges/{challenge['id']}/accept").json()  # as bob, the only one who can
    assert {game["white_id"], game["black_id"]} == {alice, bob}


# --- races -----------------------------------------------------------------------


def _race(*calls):
    """Run the calls at the same moment; return their status codes in call order."""
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def run(i, call):
        barrier.wait()
        results[i] = call().status_code

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def test_a_double_accept_creates_one_game(api_client, alice_bob):
    alice, bob, as_alice, as_bob = alice_bob
    cid = _challenge(api_client, as_alice, bob, color="random").json()["id"]

    def accept():
        return api_client.post(f"/v1/challenges/{cid}/accept", headers=as_bob)

    assert sorted(_race(accept, accept)) == [201, 404]
    games = api_client.get("/v1/games/between", params={"player1": alice, "player2": bob, "status": "active"}).json()[
        "games"
    ]
    assert len(games) == 1


def test_an_accept_racing_a_withdrawal_is_consistent(api_client, alice_bob):
    alice, bob, as_alice, as_bob = alice_bob
    cid = _challenge(api_client, as_alice, bob).json()["id"]
    accept_status, withdraw_status = _race(
        lambda: api_client.post(f"/v1/challenges/{cid}/accept", headers=as_bob),
        lambda: api_client.delete(f"/v1/challenges/{cid}", headers=as_alice),
    )
    games = api_client.get("/v1/games/between", params={"player1": alice, "player2": bob, "status": "active"}).json()[
        "games"
    ]
    if accept_status == 201:
        assert len(games) == 1 and withdraw_status == 404
    else:
        assert accept_status == 404 and withdraw_status == 204 and games == []


def test_crossing_challenges_leave_one(api_client, alice_bob):
    alice, bob, as_alice, as_bob = alice_bob
    statuses = _race(lambda: _challenge(api_client, as_alice, bob), lambda: _challenge(api_client, as_bob, alice))
    assert sorted(statuses) == [201, 409]
    pending = api_client.get("/v1/challenges", headers=as_alice).json()["challenges"]
    assert len(pending) == 1
