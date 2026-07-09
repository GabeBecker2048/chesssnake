"""Integration tests for the FastAPI api-endpoint hitting a real Postgres."""

import os

import pytest

from chesssnake.db import INITIAL_BOARD

pytestmark = pytest.mark.integration


def test_health(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_game_is_idempotent(api_client):
    body = {"group_id": 10, "white_id": 1, "black_id": 2, "white_name": "Bob", "black_name": "Phil"}
    first = api_client.post("/v1/games", json=body).json()
    assert first["board"] == INITIAL_BOARD
    assert first["turn"] == 0
    assert first["draw"] is None
    assert first["wname"] == "Bob"

    # Requesting the same game again returns the existing row, not a new one.
    second = api_client.post("/v1/games", json=body).json()
    assert second == first


def test_update_and_reload_game(api_client):
    api_client.post("/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2})
    state = {
        "board": "updated-board-string",
        "turn": 1,
        "pawnmove": "e4",
        "draw": None,
        "moved": "000000",
        "status": 0,
        "wname": "W",
        "bname": "B",
    }
    r = api_client.put("/v1/games/10/1/2", json=state)
    assert r.status_code == 200

    reloaded = api_client.post("/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2}).json()
    assert reloaded["board"] == "updated-board-string"
    assert reloaded["turn"] == 1
    assert reloaded["pawnmove"] == "e4"


def test_draw_patch_and_clear(api_client):
    api_client.post("/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2})

    api_client.patch("/v1/games/10/1/2/draw", json={"draw": 0, "status": 0})
    assert api_client.post("/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2}).json()["draw"] == 0

    api_client.delete("/v1/games/10/1/2/draw")
    assert api_client.post("/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2}).json()["draw"] is None


def test_delete_game(api_client):
    api_client.post("/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2})
    api_client.patch("/v1/games/10/1/2/draw", json={"draw": 1, "status": 0})

    assert api_client.delete("/v1/games/10/1/2").status_code == 200

    # Recreated fresh after deletion (draw back to None).
    fresh = api_client.post("/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2}).json()
    assert fresh["draw"] is None


def test_current_games_and_exists(api_client):
    api_client.post("/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2})

    opponents = api_client.get("/v1/games", params={"player_id": 1, "group_id": 10}).json()["opponents"]
    assert opponents == [2]

    game = api_client.get("/v1/games/10/exists", params={"player1": 2, "player2": 1}).json()["game"]
    assert game == {"white_id": 1, "black_id": 2}

    missing = api_client.get("/v1/games/10/exists", params={"player1": 7, "player2": 8}).json()["game"]
    assert missing is None


def test_challenge_lifecycle(api_client):
    first = api_client.post("/v1/challenges", json={"group_id": 10, "challenger": 100, "challenged": 200})
    assert first.json()["accepted"] is False
    assert (
        api_client.get("/v1/challenges/10/exists", params={"player1": 100, "player2": 200}).json()["challenge"]
        is not None
    )

    accept = api_client.post("/v1/challenges", json={"group_id": 10, "challenger": 200, "challenged": 100})
    assert accept.json()["accepted"] is True
    assert (
        api_client.get("/v1/challenges/10/exists", params={"player1": 100, "player2": 200}).json()["challenge"] is None
    )


def test_self_challenge_conflicts(api_client):
    resp = api_client.post("/v1/challenges", json={"group_id": 10, "challenger": 5, "challenged": 5})
    assert resp.status_code == 409
    assert resp.json()["error_type"] == "ChallengeError"


def test_invalid_id_returns_422(api_client):
    # Beyond PostgreSQL BIGINT range -> SQLIdError -> 422.
    resp = api_client.post("/v1/games", json={"group_id": 0, "white_id": 10**19, "black_id": 2})
    assert resp.status_code == 422
    assert resp.json()["error_type"] == "SQLIdError"


def test_health_is_unversioned_and_open(api_client):
    # /health stays at the root (no /v1) and never requires auth.
    assert api_client.get("/health").status_code == 200
    assert api_client.get("/v1/games", params={"player_id": 1, "group_id": 10}).status_code == 200


def test_api_key_enforced_when_configured(api_client):
    # When CHESSSNAKE_API_KEY is set, /v1 routes require a matching X-API-Key.
    os.environ["CHESSSNAKE_API_KEY"] = "s3cret"
    try:
        # health stays open regardless
        assert api_client.get("/health").status_code == 200

        # missing / wrong key -> 401
        assert api_client.get("/v1/games", params={"player_id": 1, "group_id": 10}).status_code == 401
        assert (
            api_client.get(
                "/v1/games", params={"player_id": 1, "group_id": 10}, headers={"X-API-Key": "wrong"}
            ).status_code
            == 401
        )

        # correct key -> allowed
        ok = api_client.get("/v1/games", params={"player_id": 1, "group_id": 10}, headers={"X-API-Key": "s3cret"})
        assert ok.status_code == 200
    finally:
        del os.environ["CHESSSNAKE_API_KEY"]


def test_client_sends_api_key(api_client):
    # An ApiClient configured with an api_key authenticates against a keyed server.
    from chesssnake.remote.client import ApiClient

    os.environ["CHESSSNAKE_API_KEY"] = "s3cret"
    try:
        keyed = ApiClient("", session=api_client, api_key="s3cret")
        # get_or_create goes through the authenticated /v1 route without raising
        state = keyed.get_or_create_game(10, 1, 2, "A", "B")
        assert state.board == INITIAL_BOARD
    finally:
        del os.environ["CHESSSNAKE_API_KEY"]
