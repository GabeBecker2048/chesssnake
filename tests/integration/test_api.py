"""Integration tests for the FastAPI api-endpoint, against both database backends.

The server runs the chess engine: clients POST moves and the server validates,
applies, stores, and returns the new state (or a mapped error). Players are
users, created first; their ids are assigned by the server.
"""

import pytest
from fastapi.testclient import TestClient

from chesssnake.engine import INITIAL_FEN

pytestmark = pytest.mark.integration

GROUP = 10


@pytest.fixture
def game(api_client, pair):
    """A fresh game between ``pair`` in ``GROUP``; yields its base URL."""
    white, black = pair
    resp = api_client.post("/v1/games", json={"group_id": GROUP, "white_id": white, "black_id": black})
    assert resp.status_code == 200, resp.text
    return f"/v1/games/{GROUP}/{white}/{black}"


def _create(api_client, white, black, group_id=GROUP):
    return api_client.post("/v1/games", json={"group_id": group_id, "white_id": white, "black_id": black}).json()


def _finish_game(api_client, url):
    for mv in ["f3", "e5", "g4", "Qh4"]:  # fool's mate -> black wins
        assert api_client.post(f"{url}/moves", json={"move": mv}).status_code == 200


def _table_count(table, **where):
    from sqlalchemy import func, select

    from chesssnake.db import engine, schema

    target = getattr(schema, table)
    stmt = select(func.count()).select_from(target)
    for column, value in where.items():
        stmt = stmt.where(target.c[column] == value)
    with engine.transaction() as conn:
        return conn.execute(stmt).scalar()


def test_health(api_client):
    assert api_client.get("/health").json() == {"status": "ok"}


# --- users -----------------------------------------------------------------


def test_create_user_assigns_an_id(api_client):
    resp = api_client.post("/v1/users", json={"username": "Alice"})
    assert resp.status_code == 201
    user = resp.json()
    assert isinstance(user["id"], int)
    assert user["username"] == "Alice"
    assert user["role"] == "user"
    assert user["identities"] == []
    assert user["created_at"].endswith("+00:00")
    assert "password_hash" not in user

    second = api_client.post("/v1/users", json={"username": "bob"}).json()
    assert second["id"] > user["id"]


def test_usernames_are_unique_ignoring_case(api_client):
    assert api_client.post("/v1/users", json={"username": "Alice"}).status_code == 201
    dup = api_client.post("/v1/users", json={"username": "alice"})
    assert dup.status_code == 409 and dup.json()["error_type"] == "UserExistsError"


@pytest.mark.parametrize("name", ["a", "has space", "x" * 33, "12345", "émile", ""])
def test_invalid_usernames_are_rejected(api_client, name):
    resp = api_client.post("/v1/users", json={"username": name})
    assert resp.status_code == 422 and resp.json()["error_type"] == "UserValidationError"


def test_get_user_by_id_and_by_name(api_client, users):
    (alice,) = users("Alice")
    assert api_client.get(f"/v1/users/{alice}").json()["username"] == "Alice"
    assert api_client.get("/v1/users", params={"username": "ALICE"}).json()["id"] == alice
    missing = api_client.get("/v1/users", params={"username": "nobody"})
    assert missing.status_code == 404 and missing.json()["error_type"] == "UserNotFoundError"
    assert api_client.get("/v1/users/999999").status_code == 404


def test_rename_user(api_client, users):
    alice, _ = users("alice", "bob")
    renamed = api_client.patch(f"/v1/users/{alice}", json={"username": "Alicia"}).json()
    assert renamed == {**renamed, "id": alice, "username": "Alicia"}
    # Renaming to your own name in another case is allowed; taking another's is not.
    assert api_client.patch(f"/v1/users/{alice}", json={"username": "ALICIA"}).status_code == 200
    taken = api_client.patch(f"/v1/users/{alice}", json={"username": "Bob"})
    assert taken.status_code == 409


def test_names_follow_the_account(api_client, game, pair):
    """Usernames live on the user, so a rename shows up on games already in progress."""
    white, _ = pair
    assert api_client.get(game).json()["white_name"] == "white"
    api_client.patch(f"/v1/users/{white}", json={"username": "Magnus"})
    assert api_client.get(game).json()["white_name"] == "Magnus"
    assert '[White "Magnus"]' in api_client.get(f"{game}/pgn").text


# --- external identities ---------------------------------------------------


def test_identity_get_or_create_is_idempotent(api_client):
    url = "/v1/users/discord/123456789012345678"
    first = api_client.post(url, json={"username": "gabe"})
    assert first.status_code == 200
    user = first.json()
    assert user["identities"] == [{"provider": "discord", "external_id": "123456789012345678"}]

    # Same external id, any name: the same user comes back, unchanged.
    again = api_client.post(url, json={"username": "someone-else"}).json()
    assert again == user
    assert api_client.get(url).json()["id"] == user["id"]
    assert api_client.get(f"/v1/users/{user['id']}").json()["identities"] == user["identities"]


def test_identity_lookup_404s_when_unlinked(api_client):
    resp = api_client.get("/v1/users/discord/1")
    assert resp.status_code == 404 and resp.json()["error_type"] == "UserNotFoundError"


def test_identity_create_with_a_taken_username_conflicts(api_client, users):
    users("gabe")
    resp = api_client.post("/v1/users/discord/42", json={"username": "Gabe"})
    assert resp.status_code == 409 and resp.json()["error_type"] == "UserExistsError"
    # Nothing was half-created: the external id is still unlinked.
    assert api_client.get("/v1/users/discord/42").status_code == 404


def test_link_identities_to_an_existing_user(api_client, users):
    alice, bob = users("alice", "bob")
    linked = api_client.put(f"/v1/users/{alice}/identities/discord/42").json()
    assert linked["identities"] == [{"provider": "discord", "external_id": "42"}]
    # Several providers per user, and relinking the same one is a no-op.
    api_client.put(f"/v1/users/{alice}/identities/slack/U024BE7LH")
    again = api_client.put(f"/v1/users/{alice}/identities/discord/42")
    assert again.status_code == 200
    assert len(again.json()["identities"]) == 2

    stolen = api_client.put(f"/v1/users/{bob}/identities/discord/42")
    assert stolen.status_code == 409 and stolen.json()["error_type"] == "UserExistsError"
    assert api_client.put("/v1/users/999999/identities/discord/7").status_code == 404


def test_identity_format_is_validated(api_client, users):
    (alice,) = users("alice")
    assert api_client.put(f"/v1/users/{alice}/identities/Discord/42").status_code == 422


# --- games -----------------------------------------------------------------


def test_create_game_is_idempotent(api_client, pair):
    white, black = pair
    first = _create(api_client, white, black)
    assert first["fen"] == INITIAL_FEN
    assert first["status"] == 0
    assert first["version"] == 1
    assert first["draw"] is None
    assert (first["white_id"], first["black_id"], first["group_id"]) == (white, black, GROUP)
    assert (first["white_name"], first["black_name"]) == ("white", "black")
    assert isinstance(first["id"], int)
    assert first["started_at"] == first["updated_at"]
    assert _create(api_client, white, black) == first


def test_creating_a_game_needs_real_distinct_users(api_client, pair):
    white, _ = pair
    unknown = api_client.post("/v1/games", json={"group_id": GROUP, "white_id": white, "black_id": 999999})
    assert unknown.status_code == 404 and unknown.json()["error_type"] == "UserNotFoundError"
    assert "999999" in unknown.json()["detail"]
    itself = api_client.post("/v1/games", json={"group_id": GROUP, "white_id": white, "black_id": white})
    assert itself.status_code == 422


def test_get_game_and_404(api_client, game):
    assert api_client.get(game).json()["fen"] == INITIAL_FEN
    missing = api_client.get("/v1/games/10/7/8")
    assert missing.status_code == 404
    assert missing.json()["error_type"] == "GameNotFoundError"


def test_get_game_by_id(api_client, game):
    state = api_client.get(game).json()
    assert api_client.get(f"/v1/games/{state['id']}").json() == state
    missing = api_client.get("/v1/games/999999")
    assert missing.status_code == 404 and missing.json()["error_type"] == "GameNotFoundError"


def test_move_is_applied_and_versioned(api_client, game):
    data = api_client.post(f"{game}/moves", json={"move": "e4"}).json()
    assert data["san"] == "e4"
    assert (data["from"], data["to"]) == ("e2", "e4")
    assert data["state"]["fen"] == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    assert data["state"]["version"] == 2
    reloaded = api_client.get(game).json()
    assert reloaded == data["state"], "the returned state is exactly what was stored, timestamps included"


def test_expected_version_conflict(api_client, game):
    api_client.post(f"{game}/moves", json={"move": "e4", "expected_version": 1})  # ok -> version 2
    stale = api_client.post(f"{game}/moves", json={"move": "e5", "expected_version": 1})
    assert stale.status_code == 409
    assert stale.json()["error_type"] == "VersionConflictError"
    # the correct version is accepted
    assert api_client.post(f"{game}/moves", json={"move": "e5", "expected_version": 2}).status_code == 200


def test_wrong_player_rejected(api_client, game, pair):
    _, black = pair
    resp = api_client.post(f"{game}/moves", json={"move": "e4", "player_id": black})  # black claims white's turn
    assert resp.status_code == 403
    assert resp.json()["error_type"] == "NotYourTurnError"


def test_illegal_and_invalid_moves(api_client, game):
    bad = api_client.post(f"{game}/moves", json={"move": "not-a-move"})
    assert bad.status_code == 400 and bad.json()["error_type"] == "InvalidNotationError"
    illegal = api_client.post(f"{game}/moves", json={"move": "e5"})
    assert illegal.status_code == 400 and illegal.json()["error_type"] == "PieceNotFoundError"


def test_move_after_game_over(api_client, game, pair):
    _finish_game(api_client, game)
    assert api_client.get(game).json()["status"] == 2  # BLACK_WON
    over = api_client.post(f"{game}/moves", json={"move": "a3"})
    assert over.status_code == 400 and over.json()["error_type"] == "GameOverError"
    # The same refusal whether or not the client names the game it means.
    named = api_client.post(f"{game}/moves", json={"move": "a3", "generation": 1})
    assert named.json()["error_type"] == "GameOverError"
    assert api_client.post(f"{game}/resign", json={"player_id": pair[0]}).json()["error_type"] == "GameOverError"


def test_resign(api_client, game, pair):
    _, black = pair
    api_client.post(f"{game}/moves", json={"move": "e4"})
    state = api_client.post(f"{game}/resign", json={"player_id": black}).json()
    assert state["status"] == 1  # WHITE_WON
    assert state["termination"] == "resignation"


def test_draw_offer_and_accept(api_client, game, pair):
    white, black = pair
    assert api_client.post(f"{game}/draw/offer", json={"player_id": white}).json()["draw"] == 0
    accepted = api_client.post(f"{game}/draw/accept", json={"player_id": black}).json()
    assert accepted["status"] == 3  # DRAW
    assert accepted["termination"] == "agreement"
    assert accepted["draw"] is None


def test_draw_out_of_turn_rejected(api_client, game, pair):
    _, black = pair
    resp = api_client.post(f"{game}/draw/offer", json={"player_id": black})  # black offers out of turn
    assert resp.status_code == 400 and resp.json()["error_type"] == "DrawWrongTurnError"


def test_legal_moves_history_pgn_fen(api_client, game):
    assert len(api_client.get(f"{game}/legal-moves").json()["moves"]) == 20
    api_client.post(f"{game}/moves", json={"move": "e4"})
    api_client.post(f"{game}/moves", json={"move": "e5"})

    history = api_client.get(f"{game}/history").json()["moves"]
    assert history == [{"ply": 1, "san": "e4"}, {"ply": 2, "san": "e5"}]

    pgn = api_client.get(f"{game}/pgn").text
    assert "1. e4 e5" in pgn and '[White "white"]' in pgn

    assert api_client.get(f"{game}/fen").text.startswith("rnbqkbnr/pppp1ppp")


def test_threefold_repetition_still_counts_the_starting_position(api_client, game):
    """The start is no longer stored as a move row; the server must still count it."""
    for mv in ["Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1"]:
        assert api_client.post(f"{game}/moves", json={"move": mv}).json()["state"]["status"] == 0
    final = api_client.post(f"{game}/moves", json={"move": "Ng8"}).json()["state"]
    assert (final["status"], final["termination"]) == (3, "threefold_repetition")


def test_image_endpoint_returns_png(api_client, game):
    resp = api_client.get(f"{game}/image")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_perspective(api_client, game):
    api_client.post(f"{game}/moves", json={"move": "e4"})
    white = api_client.get(f"{game}/image", params={"perspective": "white"})
    black = api_client.get(f"{game}/image", params={"perspective": "black"})
    assert white.status_code == 200 and white.headers["content-type"] == "image/png"
    assert white.content != black.content  # different orientations
    # an invalid perspective is rejected by request validation
    assert api_client.get(f"{game}/image", params={"perspective": "sideways"}).status_code == 422


# --- the archive -----------------------------------------------------------


def test_a_finished_game_moves_to_the_archive(api_client, game):
    game_id = api_client.get(game).json()["id"]
    _finish_game(api_client, game)

    assert _table_count("games", id=game_id) == 0
    assert _table_count("moves", game_id=game_id) == 0
    assert _table_count("finished_games", id=game_id) == 1

    # The same game, by the same id, through every read route.
    final = api_client.get(f"/v1/games/{game_id}").json()
    assert final == api_client.get(game).json()
    assert (final["id"], final["status"], final["termination"], final["version"]) == (game_id, 2, "checkmate", 5)
    assert [m["san"] for m in api_client.get(f"{game}/history").json()["moves"]] == ["f3", "e5", "g4", "Qh4#"]
    assert "Qh4#" in api_client.get(f"{game}/pgn").text
    assert api_client.get(f"{game}/fen").text == final["fen"]
    assert api_client.get(f"{game}/image").status_code == 200


def test_rematch_starts_new_generation(api_client, game, pair):
    first_id = api_client.get(game).json()["id"]
    _finish_game(api_client, game)
    assert api_client.get(game).json()["generation"] == 1

    rematch = _create(api_client, *pair)  # current game is over -> a fresh generation
    assert rematch["generation"] == 2
    assert rematch["id"] > first_id, "game ids are never reused"
    assert rematch["fen"] == INITIAL_FEN and rematch["status"] == 0
    assert api_client.get(game).json()["generation"] == 2  # "current" is now the new game


def test_old_generation_is_readable(api_client, game, pair):
    _finish_game(api_client, game)
    _create(api_client, *pair)  # start generation 2

    old = api_client.get(game, params={"generation": 1}).json()
    assert old["generation"] == 1 and old["status"] == 2
    assert "Qh4#" in api_client.get(f"{game}/pgn", params={"generation": 1}).text
    assert api_client.get(game, params={"generation": 99}).status_code == 404


def test_archive_lists_all_generations(api_client, game, pair):
    _finish_game(api_client, game)
    _create(api_client, *pair)
    archive = api_client.get(f"{game}/archive").json()["games"]
    assert [a["generation"] for a in archive] == [1, 2]
    assert [a["status"] for a in archive] == [2, 0]  # gen1 black-won, gen2 in play
    assert archive[0]["id"] < archive[1]["id"]


def test_a_stale_generation_cannot_act_on_the_rematch(api_client, game, pair):
    """Mutations pin the generation they are aimed at, so a stale client cannot reach the rematch."""
    white, black = pair
    api_client.post(f"{game}/resign", json={"player_id": white, "generation": 1})
    _create(api_client, white, black)  # generation 2
    api_client.post(f"{game}/moves", json={"move": "d4"})

    stale = api_client.post(f"{game}/moves", json={"move": "d5", "generation": 1})
    assert stale.status_code == 409 and stale.json()["error_type"] == "GenerationConflictError"
    future = api_client.post(f"{game}/moves", json={"move": "d5", "generation": 7})
    assert future.status_code == 409
    for action in ("resign", "draw/offer"):
        resp = api_client.post(f"{game}/{action}", json={"player_id": black, "generation": 1})
        assert resp.status_code == 409
    assert [m["san"] for m in api_client.get(f"{game}/history").json()["moves"]] == ["d4"]
    assert api_client.post(f"{game}/moves", json={"move": "d5", "generation": 2}).status_code == 200


def test_current_games_is_active_only(api_client, game, pair):
    white, black = pair
    current = api_client.get("/v1/games", params={"player_id": white, "group_id": GROUP}).json()["games"]
    assert [(g["white_id"], g["black_id"]) for g in current] == [(white, black)]
    _finish_game(api_client, game)  # now over -> no active game
    assert api_client.get("/v1/games", params={"player_id": white, "group_id": GROUP}).json()["games"] == []


def test_current_games_spans_groups_unless_one_is_named(api_client, users):
    me, a, b = users("me", "ann", "bea")
    _create(api_client, me, a, group_id=1)
    _create(api_client, b, me, group_id=2)
    everywhere = api_client.get("/v1/games", params={"player_id": me}).json()["games"]
    assert sorted(g["group_id"] for g in everywhere) == [1, 2]
    only_two = api_client.get("/v1/games", params={"player_id": me, "group_id": 2}).json()["games"]
    assert [(g["white_name"], g["black_name"]) for g in only_two] == [("bea", "me")]


def test_delete_game(api_client, game, pair):
    api_client.post(f"{game}/moves", json={"move": "e4"})
    assert api_client.delete(game).status_code == 200
    # recreated fresh (version back to 1, standard position)
    fresh = _create(api_client, *pair)
    assert fresh["fen"] == INITIAL_FEN and fresh["version"] == 1


def test_delete_a_finished_generation(api_client, game, pair):
    _finish_game(api_client, game)
    _create(api_client, *pair)
    assert api_client.delete(game, params={"generation": 1}).status_code == 200
    assert [a["generation"] for a in api_client.get(f"{game}/archive").json()["games"]] == [2]


def test_exists_returns_the_game(api_client, game, pair):
    white, black = pair
    found = api_client.get(f"/v1/games/{GROUP}/exists", params={"player1": black, "player2": white}).json()["game"]
    assert found == api_client.get(game).json()
    nothing = api_client.get("/v1/games/11/exists", params={"player1": black, "player2": white}).json()
    assert nothing == {"game": None}


def test_record(api_client, pair):
    p1, p2 = pair

    def base(w, b):
        return f"/v1/games/{GROUP}/{w}/{b}"

    # game 1: white=p1, black=p2, black resigns -> player 1 (white) wins
    _create(api_client, p1, p2)
    api_client.post(f"{base(p1, p2)}/moves", json={"move": "e4"})
    api_client.post(f"{base(p1, p2)}/resign", json={"player_id": p2})
    # game 2 (rematch, same triple): white=p1 resigns -> player 2 wins
    _create(api_client, p1, p2)
    api_client.post(f"{base(p1, p2)}/moves", json={"move": "e4"})
    api_client.post(f"{base(p1, p2)}/resign", json={"player_id": p1})
    # game 3 (swapped colors): white=p2, black=p1, black (player 1) resigns -> player 2 wins
    _create(api_client, p2, p1)
    api_client.post(f"{base(p2, p1)}/moves", json={"move": "e4"})
    api_client.post(f"{base(p2, p1)}/resign", json={"player_id": p1})
    # game 4: draw by agreement (white=p1, black=p2)
    _create(api_client, p1, p2)
    api_client.post(f"{base(p1, p2)}/moves", json={"move": "e4"})  # black to move
    api_client.post(f"{base(p1, p2)}/draw/offer", json={"player_id": p2})
    api_client.post(f"{base(p1, p2)}/draw/accept", json={"player_id": p1})
    # game 5: in play -> must NOT count
    _create(api_client, p1, p2)
    api_client.post(f"{base(p1, p2)}/moves", json={"move": "e4"})

    rec = api_client.get(f"/v1/games/{GROUP}/record", params={"player1": p1, "player2": p2}).json()
    assert rec == {"player1": p1, "player2": p2, "player1_wins": 1, "player2_wins": 2, "draws": 1}
    # symmetric: swapping the query players swaps the win tallies
    rec2 = api_client.get(f"/v1/games/{GROUP}/record", params={"player1": p2, "player2": p1}).json()
    assert rec2 == {"player1": p2, "player2": p1, "player1_wins": 2, "player2_wins": 1, "draws": 1}


def test_record_is_zero_when_no_finished_games(api_client):
    rec = api_client.get("/v1/games/10/record", params={"player1": 7, "player2": 8}).json()
    assert rec == {"player1": 7, "player2": 8, "player1_wins": 0, "player2_wins": 0, "draws": 0}


# --- challenges ------------------------------------------------------------


def test_challenge_lifecycle(api_client, pair):
    a, b = pair
    first = api_client.post("/v1/challenges", json={"group_id": GROUP, "challenger": a, "challenged": b})
    assert first.json()["accepted"] is False
    accept = api_client.post("/v1/challenges", json={"group_id": GROUP, "challenger": b, "challenged": a})
    assert accept.json()["accepted"] is True


def test_challenging_an_unknown_user_is_a_404(api_client, pair):
    a, _ = pair
    resp = api_client.post("/v1/challenges", json={"group_id": GROUP, "challenger": a, "challenged": 999999})
    assert resp.status_code == 404 and resp.json()["error_type"] == "UserNotFoundError"


def test_self_challenge_conflicts(api_client):
    resp = api_client.post("/v1/challenges", json={"group_id": 10, "challenger": 5, "challenged": 5})
    assert resp.status_code == 409 and resp.json()["error_type"] == "ChallengeError"


def test_invalid_id_returns_422(api_client, pair):
    resp = api_client.post("/v1/games", json={"group_id": 0, "white_id": 10**19, "black_id": pair[1]})
    assert resp.status_code == 422 and resp.json()["error_type"] == "SQLIdError"


# --- auth ------------------------------------------------------------------


@pytest.fixture
def auth_client(api_client, settings):
    """
    A second app that requires an API key, sharing the already-initialized pool.

    Two apps with different settings can coexist because settings live on the app
    rather than in the environment; ``api_client`` is requested first so the
    connection pool already exists when this app's lifespan runs.
    """
    from chesssnake.api.server import create_app
    from chesssnake.config import Settings

    auth = Settings(
        api={"require_auth": True, "api_key": "s3cret"},
        database={"url": settings.database.url},
    )
    with TestClient(create_app(auth)) as client:
        yield client


def test_api_key_enforced_when_required(auth_client, pair):
    game = {"group_id": 10, "white_id": pair[0], "black_id": pair[1]}
    assert auth_client.get("/health").status_code == 200  # health stays open

    rejected = auth_client.post("/v1/games", json=game)
    assert rejected.status_code == 401
    assert rejected.json()["error_type"] == "AuthError"
    assert auth_client.post("/v1/users", json={"username": "eve"}).status_code == 401

    assert auth_client.post("/v1/games", json=game, headers={"X-API-Key": "s3cret"}).status_code == 200


def test_no_api_key_required_by_default(api_client, pair):
    """A key set without require_auth must not silently start enforcing auth."""
    game = {"group_id": 11, "white_id": pair[0], "black_id": pair[1]}
    assert api_client.post("/v1/games", json=game).status_code == 200
