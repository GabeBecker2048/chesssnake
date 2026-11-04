"""
The listing routes the web UI browses with (0.14.0), against both backends.

- ``GET /v1/games/live``: every game in progress, most recently changed first;
- ``GET /v1/games/finished``: the archive, newest first, paged by id;
- ``GET /v1/users/search``: users by name prefix, ignoring case;
- ``GET /v1/info``: what a client needs to know before logging in.
"""

import pytest

pytestmark = pytest.mark.integration


def _start(api_client, white, black, group_id=0):
    resp = api_client.post("/v1/games", json={"group_id": group_id, "white_id": white, "black_id": black})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _resign(api_client, game_id, who):
    resp = api_client.post(f"/v1/games/{game_id}/resign", json={"player_id": who})
    assert resp.status_code == 200, resp.text


# --- /v1/games/live ------------------------------------------------------------


def test_live_lists_every_game_in_progress_most_recently_changed_first(api_client, users, as_user):
    a, b, c, d = users("ann", "ben", "cat", "dan")
    first = _start(api_client, a, b)
    second = _start(api_client, c, d, group_id=7)  # any group
    finished = _start(api_client, a, c)
    _resign(api_client, finished, a)
    # A move makes the first game the most recently changed.
    assert api_client.post(f"/v1/games/{first}/moves", json={"move": "e4"}).status_code == 200

    # Any logged-in user may browse them, not only the players.
    outsider = users("eve")[0]
    resp = api_client.get("/v1/games/live", headers=as_user(outsider))
    assert resp.status_code == 200
    assert [g["id"] for g in resp.json()["games"]] == [first, second]
    assert resp.json()["games"][0]["white_name"] == "ann"


def test_live_honours_limit_and_refuses_one_out_of_range(api_client, users):
    a, b, c, d = users("ann", "ben", "cat", "dan")
    _start(api_client, a, b)
    _start(api_client, c, d)
    assert len(api_client.get("/v1/games/live", params={"limit": 1}).json()["games"]) == 1
    for bad in (0, 201, "x"):
        assert api_client.get("/v1/games/live", params={"limit": bad}).status_code == 422


# --- /v1/games/finished ---------------------------------------------------------


def test_finished_is_newest_first_and_pages_back_by_id(api_client, users):
    a, b = users("ann", "ben")
    ids = []
    for _ in range(5):
        game = _start(api_client, a, b)
        _resign(api_client, game, b)
        ids.append(game)
    page = api_client.get("/v1/games/finished", params={"limit": 2}).json()["games"]
    assert [g["id"] for g in page] == ids[::-1][:2]
    assert page[0]["status"] == 1 and page[0]["termination"] == "resignation"
    nxt = api_client.get("/v1/games/finished", params={"limit": 2, "before": page[-1]["id"]}).json()["games"]
    assert [g["id"] for g in nxt] == ids[::-1][2:4]
    last = api_client.get("/v1/games/finished", params={"limit": 2, "before": nxt[-1]["id"]}).json()["games"]
    assert [g["id"] for g in last] == ids[:1]


def test_finished_narrows_to_one_player_either_colour(api_client, users):
    a, b, c = users("ann", "ben", "cat")
    as_white = _start(api_client, a, b)
    _resign(api_client, as_white, a)
    as_black = _start(api_client, c, a)
    _resign(api_client, as_black, c)
    other = _start(api_client, b, c)
    _resign(api_client, other, b)
    in_progress = _start(api_client, a, b, group_id=3)
    found = [g["id"] for g in api_client.get("/v1/games/finished", params={"player_id": a}).json()["games"]]
    assert found == [as_black, as_white]
    assert in_progress not in found


def test_finished_refuses_a_bad_id(api_client):
    assert api_client.get("/v1/games/finished", params={"before": 2**63}).status_code == 422
    assert api_client.get("/v1/games/finished", params={"player_id": "x"}).status_code == 422


# --- /v1/users/search -------------------------------------------------------------


def test_search_is_a_case_insensitive_prefix_ordered_by_name(api_client, users):
    users("Alice", "alfred", "bob", "ALINA")
    names = [u["username"] for u in api_client.get("/v1/users/search", params={"q": "AL"}).json()["users"]]
    assert names == ["alfred", "Alice", "ALINA"]


def test_search_takes_wildcards_literally(api_client, users):
    # "_" is a username character and a LIKE wildcard; "%" is only the latter.
    users("a_b", "axb", "abc")
    assert [u["username"] for u in api_client.get("/v1/users/search", params={"q": "a_"}).json()["users"]] == ["a_b"]
    assert api_client.get("/v1/users/search", params={"q": "a%"}).json()["users"] == []


def test_an_empty_search_lists_everyone_a_page_at_a_time(api_client, users):
    users("bob", "cat", "dan")
    everyone = [u["username"] for u in api_client.get("/v1/users/search").json()["users"]]
    assert everyone == ["admin", "bob", "cat", "dan"]
    page = api_client.get("/v1/users/search", params={"limit": 2, "offset": 2}).json()["users"]
    assert [u["username"] for u in page] == ["cat", "dan"]
    assert api_client.get("/v1/users/search", params={"offset": -1}).status_code == 422
    assert api_client.get("/v1/users/search", params={"q": "x" * 65}).status_code == 422


def test_search_shows_linked_ids_only_to_admins_and_the_user(api_client, users, as_user):
    from chesssnake.db import operations as ops

    alice, bob = users("alice", "bob")
    ops.identity_link(alice, "discord", "42")
    as_admin = api_client.get("/v1/users/search", params={"q": "alice"}).json()["users"][0]
    assert as_admin["identities"] == [{"provider": "discord", "external_id": "42"}]
    as_bob = api_client.get("/v1/users/search", params={"q": "alice"}, headers=as_user(bob)).json()["users"][0]
    assert as_bob["identities"] == []
    assert "password_hash" not in as_bob


# --- /v1/info -----------------------------------------------------------------------


def test_info_needs_no_token_and_says_what_the_server_allows(api_client):
    resp = api_client.get("/v1/info", headers={"Authorization": ""})
    assert resp.status_code == 200
    info = resp.json()
    assert info["registration"] == "closed"
    assert info["websocket"] is True  # the shared test app has websockets on
    assert isinstance(info["version"], str) and info["version"]
