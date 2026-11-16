"""
The Python clients, sync and async, against the real app on both backends (0.15.4).

Every test here runs twice: with :class:`ApiClient` and with :class:`AsyncApiClient`
(over ``httpx.ASGITransport``, driven to completion with ``asyncio.run``). Both get
their routes from one definition, and these tests are what show they behave the
same: same payloads, same errors, same chaining (a username resolved to an id
before the request that needs it).
"""

import asyncio

import pytest

from chesssnake import AsyncApiClient, Color, GameStatus, PlayerClient, Termination
from chesssnake.db import errors
from chesssnake.db import operations as ops
from chesssnake.engine import errors as chess_errors
from chesssnake.remote.client import ApiClient

pytestmark = pytest.mark.integration


class Blocking:
    """An ``AsyncApiClient`` made to look blocking: each call awaited to completion.

    A fresh ``httpx.AsyncClient`` per call, because each ``asyncio.run`` is a new
    event loop and a client's connections belong to the loop that made them.
    """

    def __init__(self, app, token):
        self._app, self.token = app, token
        self.base_url = "http://testserver"

    def _make(self):
        import httpx

        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self._app))
        return AsyncApiClient(self.base_url, token=self.token, http=http), http

    def __getattr__(self, name):
        def call(*args, **kwargs):
            async def go():
                client, http = self._make()
                try:
                    result = getattr(client, name)(*args, **kwargs)
                    if isinstance(result, PlayerClient):
                        return BlockingPlayer(self, result)
                    return await result
                finally:
                    self.token = client.token  # login/logout change it
                    await http.aclose()

            return asyncio.run(go())

        return call


class BlockingPlayer:
    """A ``PlayerClient`` over the async client, each call awaited (with its own client)."""

    def __init__(self, parent, player):
        self._parent, self._spec = parent, (player._spec, player.identity, player.create_as)

    def __getattr__(self, name):
        def call(*args, **kwargs):
            async def go():
                client, http = self._parent._make()
                user, identity, create_as = self._spec
                player = PlayerClient(client, user=user, identity=identity, create_as=create_as)
                try:
                    return await getattr(player, name)(*args, **kwargs)
                finally:
                    await http.aclose()

            return asyncio.run(go())

        return call


@pytest.fixture(params=["sync", "async"])
def make_client(request, api_client):
    """``make_client(user_id=None)``: a client of the parametrized kind, as that user or the admin."""

    def make(user_id=None):
        if user_id is None:
            token = api_client.headers["Authorization"].split()[1]
        else:
            token, _ = ops.token_create(user_id, ops.TOKEN_API, name="tests")
        if request.param == "sync":
            return ApiClient("", session=api_client, token=token)
        return Blocking(api_client.app, token)

    return make


@pytest.fixture
def client(make_client):
    return make_client()


def test_a_whole_game(client, users):
    alice, bob = users("alice", "bob")
    game = client.create_game("alice", "bob", group_id=4)  # usernames resolved first
    assert (game.white_id, game.black_id, game.group_id) == (alice, bob, 4)
    assert game.to_move is Color.WHITE and game.last_move is None and not game.is_over

    result = client.move(game, "e4", player_id=alice, expected_version=game.version)
    assert result.san == "e4" and result.state.last_move == {"from": "e2", "to": "e4", "san": "e4", "promotion": None}
    assert result.state.to_move is Color.BLACK
    assert {m["san"] for m in client.legal_moves(game)} >= {"e5", "Nf6"}
    assert client.history(game) == [{"ply": 1, "san": "e4"}]
    assert "1. e4" in client.pgn(game)
    assert client.fen(game) == result.state.fen
    assert client.image(game, perspective="white").startswith(b"\x89PNG")

    with pytest.raises(errors.NotYourTurnError):
        client.move(game, "e5", player_id=alice)
    with pytest.raises(chess_errors.ChessError):
        client.move(game, "e4", player_id=bob)

    state = client.offer_draw(game, player_id=bob)
    assert state.draw_offered_by is Color.BLACK
    assert state.last_move["san"] == "e4", "a draw offer does not change the last move"
    state = client.resign(game, player_id=bob)
    assert state.result is GameStatus.WHITE_WON and state.winner is Color.WHITE
    assert state.ending is Termination.RESIGNATION and state.is_over
    archived = client.get_game(game)
    assert archived.last_move["san"] == "e4", "the archive keeps the last move"
    assert client.record("alice", "bob", group_id=4)["player1_wins"] == 1


def test_listings_filter_by_group(client, users):
    alice, bob, carol = users("alice", "bob", "carol")
    in_one = client.create_game(alice, bob, group_id=1)
    in_two = client.create_game(alice, carol, group_id=2)
    assert [g.id for g in client.live_games(group_id=1)] == [in_one.id]
    assert {g.id for g in client.live_games()} >= {in_one.id, in_two.id}
    client.resign(in_two, player_id=carol)
    assert [g.id for g in client.finished_games(group_id=2)] == [in_two.id]
    assert client.finished_games(group_id=1) == []
    assert [g.id for g in client.finished_games("carol")] == [in_two.id]
    assert [u.username for u in client.search_users("ca")] == ["carol"]


def test_info_needs_no_login(make_client):
    info = make_client().info()
    assert set(info) >= {"version", "registration", "websocket"}


def test_challenges_through_the_scoped_client(client, users):
    alice, bob = users("alice", "bob")
    a, b = client.as_user("alice"), client.as_user(bob)
    challenge = a.challenge("bob", group_id=6, color="white")
    assert [c.id for c in b.challenges("incoming", group_id=6)] == [challenge.id]
    assert b.challenges("incoming", group_id=7) == []
    game = b.accept_challenge(challenge)
    assert game.white_id == alice
    assert a.game_against(bob, group_id=6).id == game.id
    assert a.game_against(group_id=5) is None
    result = a.move(game, "d4")
    assert result.state.version == game.version + 1
    with pytest.raises(errors.NotYourTurnError):
        a.move(result.state, "d5")
    b.resign(result.state)
    assert a.record_against(bob, group_id=6)["player1_wins"] == 1
    assert [g.id for g in a.games_with(bob, group_id=6)] == [game.id]


def test_as_identity_creates_and_caches(client, users):
    users("alice")  # the name is taken: the identity's user becomes alice_1
    player = client.as_identity("discord", 111, create_as="alice")
    user = player.user()
    assert user.username == "alice_1" and user.identities == [{"provider": "discord", "external_id": "111"}]
    assert client.as_identity("discord", "111").user().id == user.id  # found, not made again
    with pytest.raises(errors.UserNotFoundError):
        client.as_identity("discord", "222").user()


def test_suffixes_and_fallback_names(client, users):
    users("bob")
    made = [client.get_or_create_user_by_identity("discord", str(n), "bob", on_conflict="suffix") for n in range(3)]
    assert [u.username for u in made] == ["bob_1", "bob_2", "bob_3"]
    assert client.get_or_create_user_by_identity("discord", "77", "1234", on_conflict="suffix").username == "discord_77"
    odd = client.get_or_create_user_by_identity("discord", "78", "zoë the great!", on_conflict="suffix")
    assert odd.username == "zo_the_great"
    with pytest.raises(errors.UserExistsError):
        client.get_or_create_user_by_identity("discord", "79", "bob")  # on_conflict="error", the default
    with pytest.raises(errors.UserValidationError):
        client.get_or_create_user_by_identity("discord", "80", "bob", on_conflict="rename")


def test_link_codes(make_client, users):
    carol, dave = users("carol", "dave")
    admin, as_carol = make_client(), make_client(carol)
    auto = admin.get_or_create_user_by_identity("discord", "5", "auto")
    made = as_carol.link_code()
    assert len(made["code"]) == 9 and made["code"][4] == "-"

    user, previous = admin.redeem_link_code("discord", "5", made["code"].lower().replace("-", " "))
    assert user.id == carol and previous == auto.id
    assert admin.get_user_by_identity("discord", "5").id == carol
    with pytest.raises(errors.LinkCodeError):
        admin.redeem_link_code("discord", "5", made["code"])  # used
    with pytest.raises(errors.ForbiddenError):
        make_client(dave).redeem_link_code("discord", "6", as_carol.link_code()["code"])  # only admins redeem

    first = as_carol.link_code()["code"]
    second = as_carol.link_code()["code"]
    with pytest.raises(errors.LinkCodeError):
        admin.redeem_link_code("discord", "6", first)  # replaced by the second
    with pytest.raises(errors.UserExistsError):
        admin.redeem_link_code("discord", "6", second)  # carol already has a discord id
    admin.unlink_identity(carol, "discord", "5")
    assert admin.redeem_link_code("discord", "6", second)[0].id == carol  # not spent by the refusal


def test_an_expired_link_code(client, users):
    (carol,) = users("carol")
    code, _ = ops.link_code_create(carol, -1)
    with pytest.raises(errors.LinkCodeError, match="expired"):
        client.redeem_link_code("discord", "1", code)


def test_group_admins(make_client, users):
    alice, bob, mod = users("alice", "bob", "mod")
    admin = make_client()
    assert admin.add_group_admin(7, "mod").admin_groups == [7]
    assert [u.id for u in admin.group_admins(7)] == [mod]
    moderator = make_client(mod)
    assert moderator.me().admin_groups == [7]

    game = moderator.create_game(alice, bob, group_id=7)
    moderator.as_user(alice).move(game, "e4")
    moderator.offer_draw(game.id, player_id=bob)
    with pytest.raises(errors.ForbiddenError):
        moderator.create_game(alice, bob, group_id=8)
    with pytest.raises(errors.ForbiddenError):
        moderator.add_group_admin(7, alice)  # granting stays with global admins
    with pytest.raises(errors.ForbiddenError):
        moderator.create_user("eve")
    other = admin.create_game(alice, bob, group_id=8)
    with pytest.raises(errors.ForbiddenError):
        moderator.move(other, "e4", player_id=alice)
    moderator.delete_game(game)

    admin.remove_group_admin(7, mod)
    with pytest.raises(errors.ForbiddenError):
        moderator.create_game(alice, bob, group_id=7)
    assert make_client(alice).get_user(mod).admin_groups == [], "hidden from other users"


def test_two_redeems_of_one_code_link_once(api_client, users):
    """The delete is the claim: of two simultaneous redeems, one wins."""
    from concurrent.futures import ThreadPoolExecutor

    (carol,) = users("carol")
    code, _ = ops.link_code_create(carol, 10)
    outcomes = []

    def redeem(external_id):
        try:
            ops.link_code_redeem(code, "discord", external_id)
            outcomes.append("ok")
        except (errors.LinkCodeError, errors.UserExistsError):
            outcomes.append("refused")

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(redeem, ["1", "2"]))
    assert sorted(outcomes) == ["ok", "refused"]
    assert len([i for i in ops.user_get(carol)["identities"] if i["provider"] == "discord"]) == 1


def test_the_image_highlights_the_last_move(client, users):
    alice, bob = users("alice", "bob")
    game = client.create_game(alice, bob)
    before = client.image(game)
    for player, move in ((alice, "Nf3"), (bob, "Nf6"), (alice, "Ng1"), (bob, "Ng8")):
        client.move(game, move, player_id=player)
    # The starting position again, but now with Ng8's squares highlighted.
    assert client.get_game(game).fen.split()[0] == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
    assert client.image(game) != before
