"""Integration tests for the FastAPI api-endpoint hitting a real Postgres.

The server now runs the chess engine: clients POST moves and the server validates,
applies, stores, and returns the new state (or a mapped error).
"""

import os

import pytest

from chesssnake.db import INITIAL_BOARD

pytestmark = pytest.mark.integration

GAME = "/v1/games/10/1/2"


def _create(api_client, group_id=10, white_id=1, black_id=2, **names):
    body = {"group_id": group_id, "white_id": white_id, "black_id": black_id, **names}
    return api_client.post("/v1/games", json=body).json()


def test_health(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_game_is_idempotent(api_client):
    first = _create(api_client, white_name="Bob", black_name="Phil")
    assert first["board"] == INITIAL_BOARD
    assert first["turn"] == 0
    assert first["draw"] is None
    assert first["wname"] == "Bob"

    second = _create(api_client, white_name="Bob", black_name="Phil")
    assert second == first


def test_get_game_and_404(api_client):
    _create(api_client)
    got = api_client.get(GAME)
    assert got.status_code == 200
    assert got.json()["board"] == INITIAL_BOARD

    missing = api_client.get("/v1/games/10/7/8")
    assert missing.status_code == 404
    assert missing.json()["error_type"] == "GameNotFoundError"


def test_move_is_applied_by_the_server(api_client):
    _create(api_client)
    resp = api_client.post(f"{GAME}/moves", json={"move": "e4"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["from"] == "e2"
    assert data["to"] == "e4"
    assert data["check"] is False
    # the server advanced the turn and stored the new board
    assert data["state"]["turn"] == 1
    assert data["state"]["pawnmove"] == "e4"  # double push sets en-passant target
    reloaded = api_client.get(GAME).json()
    assert reloaded["turn"] == 1
    assert reloaded["board"] == data["state"]["board"]


def test_two_sequential_moves(api_client):
    _create(api_client)
    api_client.post(f"{GAME}/moves", json={"move": "e4"})
    r2 = api_client.post(f"{GAME}/moves", json={"move": "e5"}).json()
    assert r2["state"]["turn"] == 0  # back to white


def test_invalid_notation_rejected(api_client):
    _create(api_client)
    resp = api_client.post(f"{GAME}/moves", json={"move": "not-a-move"})
    assert resp.status_code == 400
    assert resp.json()["error_type"] == "InvalidNotationError"


def test_illegal_move_rejected(api_client):
    _create(api_client)
    # No white pawn can reach e5 in one move from the start.
    resp = api_client.post(f"{GAME}/moves", json={"move": "e5"})
    assert resp.status_code == 400
    assert resp.json()["error_type"] == "PieceNotFoundError"


def test_move_after_game_over_rejected(api_client):
    _create(api_client)
    for mv in ["f3", "e5", "g4", "Qh4"]:  # fool's mate
        api_client.post(f"{GAME}/moves", json={"move": mv})
    assert api_client.get(GAME).json()["status"] == 1  # checkmate stored

    resp = api_client.post(f"{GAME}/moves", json={"move": "a3"})
    assert resp.status_code == 400
    assert resp.json()["error_type"] == "GameOverError"


def test_draw_offer_accept(api_client):
    _create(api_client)
    offered = api_client.post(f"{GAME}/draw/offer", json={"player_id": 1}).json()
    assert offered["draw"] == 0  # white offered

    accepted = api_client.post(f"{GAME}/draw/accept", json={"player_id": 2}).json()
    assert accepted["status"] == 2  # draw


def test_draw_offer_decline(api_client):
    _create(api_client)
    api_client.post(f"{GAME}/draw/offer", json={"player_id": 1})
    declined = api_client.post(f"{GAME}/draw/decline", json={"player_id": 2}).json()
    assert declined["draw"] is None
    assert declined["status"] == 0


def test_draw_offer_out_of_turn_rejected(api_client):
    _create(api_client)  # white to move
    resp = api_client.post(f"{GAME}/draw/offer", json={"player_id": 2})  # black offers
    assert resp.status_code == 400
    assert resp.json()["error_type"] == "DrawWrongTurnError"


def test_image_endpoint_returns_png(api_client):
    _create(api_client)
    api_client.post(f"{GAME}/moves", json={"move": "e4"})
    resp = api_client.get(f"{GAME}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_delete_game(api_client):
    _create(api_client)
    api_client.post(f"{GAME}/moves", json={"move": "e4"})
    assert api_client.delete(GAME).status_code == 200
    # recreated fresh after deletion
    assert _create(api_client)["board"] == INITIAL_BOARD


def test_current_games_and_exists(api_client):
    _create(api_client)
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
    resp = api_client.post("/v1/games", json={"group_id": 0, "white_id": 10**19, "black_id": 2})
    assert resp.status_code == 422
    assert resp.json()["error_type"] == "SQLIdError"


def test_api_key_enforced_when_configured(api_client):
    os.environ["CHESSSNAKE_API_KEY"] = "s3cret"
    try:
        assert api_client.get("/health").status_code == 200  # health stays open
        assert api_client.post("/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2}).status_code == 401
        ok = api_client.post(
            "/v1/games", json={"group_id": 10, "white_id": 1, "black_id": 2}, headers={"X-API-Key": "s3cret"}
        )
        assert ok.status_code == 200
    finally:
        del os.environ["CHESSSNAKE_API_KEY"]
