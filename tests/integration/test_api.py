"""Integration tests for the FastAPI api-endpoint hitting a real Postgres.

The server runs the chess engine: clients POST moves and the server validates,
applies, stores, and returns the new state (or a mapped error).
"""

import os

import pytest

from chesssnake.engine import INITIAL_FEN

pytestmark = pytest.mark.integration

GAME = "/v1/games/10/1/2"


def _create(api_client, group_id=10, white_id=1, black_id=2, **names):
    body = {"group_id": group_id, "white_id": white_id, "black_id": black_id, **names}
    return api_client.post("/v1/games", json=body).json()


def test_health(api_client):
    assert api_client.get("/health").json() == {"status": "ok"}


def test_create_game_is_idempotent(api_client):
    first = _create(api_client, white_name="Bob", black_name="Phil")
    assert first["fen"] == INITIAL_FEN
    assert first["status"] == 0
    assert first["version"] == 1
    assert first["draw"] is None
    assert first["wname"] == "Bob"
    assert _create(api_client, white_name="Bob", black_name="Phil") == first


def test_get_game_and_404(api_client):
    _create(api_client)
    assert api_client.get(GAME).json()["fen"] == INITIAL_FEN
    missing = api_client.get("/v1/games/10/7/8")
    assert missing.status_code == 404
    assert missing.json()["error_type"] == "GameNotFoundError"


def test_move_is_applied_and_versioned(api_client):
    _create(api_client)
    data = api_client.post(f"{GAME}/moves", json={"move": "e4"}).json()
    assert data["san"] == "e4"
    assert (data["from"], data["to"]) == ("e2", "e4")
    assert data["state"]["fen"] == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    assert data["state"]["version"] == 2
    reloaded = api_client.get(GAME).json()
    assert reloaded["fen"] == data["state"]["fen"]
    assert reloaded["version"] == 2


def test_expected_version_conflict(api_client):
    _create(api_client)
    api_client.post(f"{GAME}/moves", json={"move": "e4", "expected_version": 1})  # ok -> version 2
    stale = api_client.post(f"{GAME}/moves", json={"move": "e5", "expected_version": 1})
    assert stale.status_code == 409
    assert stale.json()["error_type"] == "VersionConflictError"
    # the correct version is accepted
    assert api_client.post(f"{GAME}/moves", json={"move": "e5", "expected_version": 2}).status_code == 200


def test_wrong_player_rejected(api_client):
    _create(api_client)  # white=1 to move
    resp = api_client.post(f"{GAME}/moves", json={"move": "e4", "player_id": 2})  # black claims
    assert resp.status_code == 403
    assert resp.json()["error_type"] == "NotYourTurnError"


def test_illegal_and_invalid_moves(api_client):
    _create(api_client)
    bad = api_client.post(f"{GAME}/moves", json={"move": "not-a-move"})
    assert bad.status_code == 400 and bad.json()["error_type"] == "InvalidNotationError"
    illegal = api_client.post(f"{GAME}/moves", json={"move": "e5"})
    assert illegal.status_code == 400 and illegal.json()["error_type"] == "PieceNotFoundError"


def test_move_after_game_over(api_client):
    _create(api_client)
    for mv in ["f3", "e5", "g4", "Qh4"]:  # fool's mate -> black wins
        api_client.post(f"{GAME}/moves", json={"move": mv})
    assert api_client.get(GAME).json()["status"] == 2  # BLACK_WON
    over = api_client.post(f"{GAME}/moves", json={"move": "a3"})
    assert over.status_code == 400 and over.json()["error_type"] == "GameOverError"


def test_resign(api_client):
    _create(api_client)
    api_client.post(f"{GAME}/moves", json={"move": "e4"})
    state = api_client.post(f"{GAME}/resign", json={"player_id": 2}).json()  # black resigns
    assert state["status"] == 1  # WHITE_WON
    assert state["termination"] == "resignation"


def test_draw_offer_and_accept(api_client):
    _create(api_client)
    assert api_client.post(f"{GAME}/draw/offer", json={"player_id": 1}).json()["draw"] == 0
    accepted = api_client.post(f"{GAME}/draw/accept", json={"player_id": 2}).json()
    assert accepted["status"] == 3  # DRAW
    assert accepted["termination"] == "agreement"


def test_draw_out_of_turn_rejected(api_client):
    _create(api_client)  # white to move
    resp = api_client.post(f"{GAME}/draw/offer", json={"player_id": 2})  # black offers out of turn
    assert resp.status_code == 400 and resp.json()["error_type"] == "DrawWrongTurnError"


def test_legal_moves_history_pgn_fen(api_client):
    _create(api_client, white_name="A", black_name="B")
    assert len(api_client.get(f"{GAME}/legal-moves").json()["moves"]) == 20
    api_client.post(f"{GAME}/moves", json={"move": "e4"})
    api_client.post(f"{GAME}/moves", json={"move": "e5"})

    history = api_client.get(f"{GAME}/history").json()["moves"]
    assert [m["san"] for m in history] == ["e4", "e5"]

    pgn = api_client.get(f"{GAME}/pgn").text
    assert "1. e4 e5" in pgn and '[White "A"]' in pgn

    assert api_client.get(f"{GAME}/fen").text.startswith("rnbqkbnr/pppp1ppp")


def test_image_endpoint_returns_png(api_client):
    _create(api_client)
    resp = api_client.get(f"{GAME}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_delete_game(api_client):
    _create(api_client)
    api_client.post(f"{GAME}/moves", json={"move": "e4"})
    assert api_client.delete(GAME).status_code == 200
    # recreated fresh (version back to 1, standard position)
    fresh = _create(api_client)
    assert fresh["fen"] == INITIAL_FEN and fresh["version"] == 1


def test_current_games_and_exists(api_client):
    _create(api_client)
    assert api_client.get("/v1/games", params={"player_id": 1, "group_id": 10}).json()["opponents"] == [2]
    game = api_client.get("/v1/games/10/exists", params={"player1": 2, "player2": 1}).json()["game"]
    assert game == {"white_id": 1, "black_id": 2}


def test_challenge_lifecycle(api_client):
    first = api_client.post("/v1/challenges", json={"group_id": 10, "challenger": 100, "challenged": 200})
    assert first.json()["accepted"] is False
    accept = api_client.post("/v1/challenges", json={"group_id": 10, "challenger": 200, "challenged": 100})
    assert accept.json()["accepted"] is True


def test_self_challenge_conflicts(api_client):
    resp = api_client.post("/v1/challenges", json={"group_id": 10, "challenger": 5, "challenged": 5})
    assert resp.status_code == 409 and resp.json()["error_type"] == "ChallengeError"


def test_invalid_id_returns_422(api_client):
    resp = api_client.post("/v1/games", json={"group_id": 0, "white_id": 10**19, "black_id": 2})
    assert resp.status_code == 422 and resp.json()["error_type"] == "SQLIdError"


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
