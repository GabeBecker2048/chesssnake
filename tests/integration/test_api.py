"""Integration tests for the FastAPI api-endpoint, against both database backends.

The server runs the chess engine: clients POST moves and the server validates,
applies, stores, and returns the new state (or a mapped error). These run as the
test administrator (see ``conftest.clean_tables``); what plain users may do is
covered by ``test_permissions.py``, logging in by ``test_auth.py``, and creating
games through challenges by ``test_challenges.py``.
"""

import pytest

from chesssnake.engine import INITIAL_FEN

pytestmark = pytest.mark.integration

GROUP = 10


def _create(api_client, white, black, group_id=GROUP):
    resp = api_client.post("/v1/games", json={"group_id": group_id, "white_id": white, "black_id": black})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def game(api_client, pair):
    """A fresh game between ``pair`` in ``GROUP``; returns its URL."""
    return f"/v1/games/{_create(api_client, *pair)['id']}"


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


# --- users (as admin) --------------------------------------------------------


def test_admin_creates_users(api_client):
    resp = api_client.post("/v1/users", json={"username": "Alice", "password": "a-long-password"})
    assert resp.status_code == 201
    user = resp.json()
    assert isinstance(user["id"], int) and user["username"] == "Alice"
    assert user["role"] == "user" and user["has_password"] is True
    assert user["created_at"].endswith("+00:00")
    assert "password_hash" not in user and "password" not in user

    bot = api_client.post("/v1/users", json={"username": "bot", "role": "admin"}).json()
    assert bot["id"] > user["id"] and bot["role"] == "admin" and bot["has_password"] is False


def test_usernames_are_unique_ignoring_case(api_client, users):
    users("Alice")
    dup = api_client.post("/v1/users", json={"username": "alice"})
    assert dup.status_code == 409 and dup.json()["error_type"] == "UserExistsError"


@pytest.mark.parametrize("name", ["a", "has space", "x" * 33, "12345", "émile", ""])
def test_invalid_usernames_are_rejected(api_client, name):
    resp = api_client.post("/v1/users", json={"username": name})
    assert resp.status_code == 422 and resp.json()["error_type"] == "UserValidationError"


def test_short_passwords_are_rejected(api_client):
    resp = api_client.post("/v1/users", json={"username": "alice", "password": "short"})
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
    assert (renamed["id"], renamed["username"]) == (alice, "Alicia")
    assert api_client.patch(f"/v1/users/{alice}", json={"username": "ALICIA"}).status_code == 200
    assert api_client.patch(f"/v1/users/{alice}", json={"username": "Bob"}).status_code == 409


def test_names_follow_the_account(api_client, game, pair):
    """Usernames live on the user, so a rename shows up on games already in progress."""
    white, _ = pair
    assert api_client.get(game).json()["white_name"] == "white"
    api_client.patch(f"/v1/users/{white}", json={"username": "Magnus"})
    assert api_client.get(game).json()["white_name"] == "Magnus"
    assert '[White "Magnus"]' in api_client.get(f"{game}/pgn").text


def test_last_admin_cannot_be_demoted_or_disabled(api_client, admin_id, users):
    for change in ({"role": "user"}, {"disabled": True}):
        resp = api_client.patch(f"/v1/users/{admin_id}", json=change)
        assert resp.status_code == 403 and "last" in resp.json()["detail"]
    (other,) = users("deputy", role=1)
    assert api_client.patch(f"/v1/users/{admin_id}", json={"role": "user"}).status_code == 200
    assert api_client.get(f"/v1/users/{other}").json()["role"] == "admin"


# --- external identities (admin) --------------------------------------------


def test_identity_get_or_create_is_idempotent(api_client):
    url = "/v1/users/discord/123456789012345678"
    first = api_client.post(url, json={"username": "gabe"})
    assert first.status_code == 200
    user = first.json()
    assert user["identities"] == [{"provider": "discord", "external_id": "123456789012345678"}]
    assert user["has_password"] is False, "a bot-made account cannot log in"
    again = api_client.post(url, json={"username": "someone-else"}).json()
    assert again == user
    assert api_client.get(url).json()["id"] == user["id"]


def test_identity_create_with_a_taken_username_conflicts(api_client, users):
    users("gabe")
    resp = api_client.post("/v1/users/discord/42", json={"username": "Gabe"})
    assert resp.status_code == 409 and resp.json()["error_type"] == "UserExistsError"
    assert api_client.get("/v1/users/discord/42").status_code == 404


def test_link_and_unlink_identities(api_client, users):
    alice, bob = users("alice", "bob")
    linked = api_client.put(f"/v1/users/{alice}/identities/discord/42").json()
    assert linked["identities"] == [{"provider": "discord", "external_id": "42"}]
    api_client.put(f"/v1/users/{alice}/identities/slack/U024BE7LH")
    assert len(api_client.put(f"/v1/users/{alice}/identities/discord/42").json()["identities"]) == 2
    assert api_client.put(f"/v1/users/{bob}/identities/discord/42").status_code == 409
    unlinked = api_client.delete(f"/v1/users/{alice}/identities/discord/42").json()
    assert unlinked["identities"] == [{"provider": "slack", "external_id": "U024BE7LH"}]
    assert api_client.get("/v1/users/discord/42").status_code == 404
    assert api_client.put(f"/v1/users/{alice}/identities/Discord/42").status_code == 422


# --- games -------------------------------------------------------------------


def test_admin_creates_a_game_directly(api_client, pair):
    white, black = pair
    first = _create(api_client, white, black)
    assert first["fen"] == INITIAL_FEN and first["status"] == 0 and first["version"] == 1
    assert (first["white_id"], first["black_id"], first["group_id"]) == (white, black, GROUP)
    assert (first["white_name"], first["black_name"]) == ("white", "black")
    assert first["started_at"] == first["updated_at"]
    assert _create(api_client, white, black) == first, "get-or-create"


def test_creating_a_game_needs_real_distinct_users(api_client, pair):
    white, _ = pair
    unknown = api_client.post("/v1/games", json={"group_id": GROUP, "white_id": white, "black_id": 999999})
    assert unknown.status_code == 404 and unknown.json()["error_type"] == "UserNotFoundError"
    itself = api_client.post("/v1/games", json={"group_id": GROUP, "white_id": white, "black_id": white})
    assert itself.status_code == 422


def test_get_game_and_404(api_client, game):
    assert api_client.get(game).json()["fen"] == INITIAL_FEN
    missing = api_client.get("/v1/games/999999")
    assert missing.status_code == 404 and missing.json()["error_type"] == "GameNotFoundError"


def test_move_is_applied_and_versioned(api_client, game):
    data = api_client.post(f"{game}/moves", json={"move": "e4"}).json()
    assert data["san"] == "e4"
    assert (data["from"], data["to"]) == ("e2", "e4")
    assert data["state"]["fen"] == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    assert data["state"]["version"] == 2
    assert api_client.get(game).json() == data["state"], "the returned state is what was stored"


def test_expected_version_conflict(api_client, game):
    api_client.post(f"{game}/moves", json={"move": "e4", "expected_version": 1})
    stale = api_client.post(f"{game}/moves", json={"move": "e5", "expected_version": 1})
    assert stale.status_code == 409 and stale.json()["error_type"] == "VersionConflictError"
    assert api_client.post(f"{game}/moves", json={"move": "e5", "expected_version": 2}).status_code == 200


def test_acting_for_the_wrong_side(api_client, game, pair):
    _, black = pair
    resp = api_client.post(f"{game}/moves", json={"move": "e4", "player_id": black})
    assert resp.status_code == 403 and resp.json()["error_type"] == "NotYourTurnError"


def test_illegal_and_invalid_moves(api_client, game):
    bad = api_client.post(f"{game}/moves", json={"move": "not-a-move"})
    assert bad.status_code == 400 and bad.json()["error_type"] == "InvalidNotationError"
    illegal = api_client.post(f"{game}/moves", json={"move": "e5"})
    assert illegal.status_code == 400 and illegal.json()["error_type"] == "PieceNotFoundError"


def test_move_after_game_over(api_client, game, pair):
    _finish_game(api_client, game)
    assert api_client.get(game).json()["status"] == 2
    over = api_client.post(f"{game}/moves", json={"move": "a3"})
    assert over.status_code == 400 and over.json()["error_type"] == "GameOverError"
    resigned = api_client.post(f"{game}/resign", json={"player_id": pair[0]})
    assert resigned.json()["error_type"] == "GameOverError"


def test_resign(api_client, game, pair):
    _, black = pair
    api_client.post(f"{game}/moves", json={"move": "e4"})
    state = api_client.post(f"{game}/resign", json={"player_id": black}).json()
    assert state["status"] == 1 and state["termination"] == "resignation"


def test_an_admin_outside_the_game_must_name_who_resigns(api_client, game):
    resp = api_client.post(f"{game}/resign")
    assert resp.status_code == 422 and "player_id" in resp.json()["detail"]


def test_draw_offer_and_accept(api_client, game, pair):
    white, black = pair
    assert api_client.post(f"{game}/draw/offer", json={"player_id": white}).json()["draw"] == 0
    accepted = api_client.post(f"{game}/draw/accept", json={"player_id": black}).json()
    assert (accepted["status"], accepted["termination"], accepted["draw"]) == (3, "agreement", None)


def test_draw_out_of_turn_rejected(api_client, game, pair):
    resp = api_client.post(f"{game}/draw/offer", json={"player_id": pair[1]})
    assert resp.status_code == 400 and resp.json()["error_type"] == "DrawWrongTurnError"


def test_legal_moves_history_pgn_fen(api_client, game):
    assert len(api_client.get(f"{game}/legal-moves").json()["moves"]) == 20
    api_client.post(f"{game}/moves", json={"move": "e4"})
    api_client.post(f"{game}/moves", json={"move": "e5"})
    assert api_client.get(f"{game}/history").json()["moves"] == [{"ply": 1, "san": "e4"}, {"ply": 2, "san": "e5"}]
    pgn = api_client.get(f"{game}/pgn").text
    assert "1. e4 e5" in pgn and '[White "white"]' in pgn
    assert api_client.get(f"{game}/fen").text.startswith("rnbqkbnr/pppp1ppp")


def test_threefold_repetition_still_counts_the_starting_position(api_client, game):
    for mv in ["Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1"]:
        assert api_client.post(f"{game}/moves", json={"move": mv}).json()["state"]["status"] == 0
    final = api_client.post(f"{game}/moves", json={"move": "Ng8"}).json()["state"]
    assert (final["status"], final["termination"]) == (3, "threefold_repetition")


def test_image_endpoint_returns_png(api_client, game):
    resp = api_client.get(f"{game}/image")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_perspective(api_client, game):
    api_client.post(f"{game}/moves", json={"move": "e4"})
    white = api_client.get(f"{game}/image", params={"perspective": "white"})
    black = api_client.get(f"{game}/image", params={"perspective": "black"})
    assert white.status_code == 200 and white.content != black.content
    assert api_client.get(f"{game}/image", params={"perspective": "sideways"}).status_code == 422


# --- the archive -------------------------------------------------------------


def test_a_finished_game_moves_to_the_archive(api_client, game):
    game_id = api_client.get(game).json()["id"]
    _finish_game(api_client, game)
    assert _table_count("games", id=game_id) == 0
    assert _table_count("moves", game_id=game_id) == 0
    assert _table_count("finished_games", id=game_id) == 1
    final = api_client.get(game).json()
    assert (final["id"], final["status"], final["termination"], final["version"]) == (game_id, 2, "checkmate", 5)
    assert [m["san"] for m in api_client.get(f"{game}/history").json()["moves"]] == ["f3", "e5", "g4", "Qh4#"]
    assert "Qh4#" in api_client.get(f"{game}/pgn").text
    assert api_client.get(f"{game}/fen").text == final["fen"]
    assert api_client.get(f"{game}/image").status_code == 200


def test_a_rematch_is_a_new_game_and_generation(api_client, game, pair):
    first = api_client.get(game).json()
    _finish_game(api_client, game)
    rematch = _create(api_client, *pair)
    assert rematch["generation"] == 2 and rematch["id"] > first["id"]
    assert api_client.get(game).json()["status"] == 2, "the old id still names the old game"
    assert api_client.post(f"{game}/moves", json={"move": "d4"}).json()["error_type"] == "GameOverError"


def test_games_between(api_client, game, pair):
    white, black = pair
    _finish_game(api_client, game)
    swapped = _create(api_client, black, white)  # the rematch, colours swapped
    between = api_client.get(
        "/v1/games/between", params={"player1": white, "player2": black, "group_id": GROUP}
    ).json()["games"]
    assert [(g["status"], g["white_id"]) for g in between] == [(2, white), (0, black)]
    active = api_client.get(
        "/v1/games/between", params={"player1": black, "player2": white, "group_id": GROUP, "status": "active"}
    ).json()["games"]
    assert [g["id"] for g in active] == [swapped["id"]]
    elsewhere = api_client.get("/v1/games/between", params={"player1": white, "player2": black, "group_id": 11})
    assert elsewhere.json() == {"games": []}


def test_current_games(api_client, users):
    me, a, b = users("me", "ann", "bea")
    _create(api_client, me, a, group_id=1)
    _create(api_client, b, me, group_id=2)
    everywhere = api_client.get("/v1/games", params={"player_id": me}).json()["games"]
    assert sorted(g["group_id"] for g in everywhere) == [1, 2]
    only_two = api_client.get("/v1/games", params={"player_id": me, "group_id": 2}).json()["games"]
    assert [(g["white_name"], g["black_name"]) for g in only_two] == [("bea", "me")]
    assert api_client.get("/v1/games").json() == {"games": []}, "default: the caller's own games"


def test_delete_game(api_client, game):
    api_client.post(f"{game}/moves", json={"move": "e4"})
    assert api_client.delete(game).status_code == 204
    assert api_client.get(game).status_code == 404
    assert api_client.delete(game).status_code == 404


def test_delete_a_finished_game(api_client, game):
    _finish_game(api_client, game)
    assert api_client.delete(game).status_code == 204
    assert api_client.get(game).status_code == 404


def test_record(api_client, pair):
    p1, p2 = pair

    def play(white, black, *actions):
        url = f"/v1/games/{_create(api_client, white, black)['id']}"
        api_client.post(f"{url}/moves", json={"move": "e4"})
        for action, actor in actions:
            api_client.post(f"{url}/{action}", json={"player_id": actor})

    play(p1, p2, ("resign", p2))  # p1 wins as white
    play(p1, p2, ("resign", p1))  # p2 wins as black
    play(p2, p1, ("resign", p1))  # p2 wins as white
    play(p1, p2, ("draw/offer", p2), ("draw/accept", p1))  # draw
    _create(api_client, p1, p2)  # in play: does not count

    params = {"player1": p1, "player2": p2, "group_id": GROUP}
    assert api_client.get("/v1/games/record", params=params).json() == {
        "player1": p1,
        "player2": p2,
        "player1_wins": 1,
        "player2_wins": 2,
        "draws": 1,
    }


def test_invalid_id_returns_422(api_client, pair):
    resp = api_client.post("/v1/games", json={"group_id": 0, "white_id": 10**19, "black_id": pair[1]})
    assert resp.status_code == 422 and resp.json()["error_type"] == "SQLIdError"
