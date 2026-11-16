"""
The follow feeds of ``/v1/ws`` (0.15.4): administrators follow every game, a
group's admins that group's games, without subscribing to each. And the
``actor_id``/``requested_by`` fields every game event carries since then.
"""

import pytest

from chesssnake.db import operations as ops
from tests.integration.test_websocket import WS, nothing_else, ready, subscribe, token_for

pytestmark = pytest.mark.integration


@pytest.fixture
def people(users, api_client):
    alice, bob, mod, carol = users("alice", "bob", "mod", "carol")
    ops.group_admin_add(7, mod)
    return {"alice": alice, "bob": bob, "mod": mod, "carol": carol, "admin": api_client.admin_id}


@pytest.fixture
def broker(api_client):
    return api_client.app.state.broker


def follow(ws, **target):
    ws.send_json({"type": "follow", **target})
    return ws.receive_json()


def test_admin_follows_everything_and_hears_new_games(api_client, remote_client, people):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, token_for(people["admin"])[0])
        assert follow(ws, all=True) == {"type": "following", "all": True}
        game = remote_client.create_game(people["alice"], people["bob"], group_id=3)
        started = ws.receive_json()
        assert started["type"] == "game_started" and started["state"]["id"] == game.id
        assert started["requested_by"] == people["admin"] and started["actor_id"] is None
        remote_client.move(game.id, "e4", player_id=people["alice"])
        event = ws.receive_json()
        assert event["type"] == "game" and event["state"]["version"] == 2
        assert event["actor_id"] == people["alice"] and event["requested_by"] == people["admin"]
        nothing_else(ws)


def test_only_admins_follow_everything(api_client, people):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, token_for(people["carol"])[0])
        assert follow(ws, all=True)["code"] == "forbidden"
        assert follow(ws, group=7)["code"] == "forbidden"
        nothing_else(ws)


def test_a_group_admin_follows_their_group_only(api_client, remote_client, people):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, token_for(people["mod"])[0])
        assert follow(ws, group=7) == {"type": "following", "group": 7}
        assert follow(ws, group=8)["code"] == "forbidden"
        remote_client.create_game(people["alice"], people["bob"], group_id=8)  # not theirs
        game = remote_client.create_game(people["alice"], people["bob"], group_id=7)
        assert ws.receive_json()["state"]["id"] == game.id
        challenge = remote_client.challenge(people["carol"], group_id=7, player_id=people["alice"])
        heard = ws.receive_json()
        assert heard["type"] == "challenge" and heard["challenge"]["id"] == challenge.id
        nothing_else(ws)


def test_a_player_who_follows_hears_each_event_once(api_client, remote_client, user_client, people):
    """Their user topic, their game subscription and the feed all carry the event."""
    ops.group_admin_add(7, people["alice"])
    with api_client.websocket_connect(WS) as ws:
        ready(ws, token_for(people["alice"])[0])
        follow(ws, group=7)
        game = remote_client.create_game(people["alice"], people["bob"], group_id=7)
        assert ws.receive_json()["type"] == "game_started"
        assert subscribe(ws, game.id)["type"] == "subscribed"
        user_client(people["bob"]).resign(game.id)
        assert ws.receive_json()["type"] == "game"
        nothing_else(ws)


def test_a_fed_game_can_still_be_subscribed_for_a_snapshot(api_client, remote_client, people):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, token_for(people["admin"])[0])
        follow(ws, all=True)
        game = remote_client.create_game(people["alice"], people["bob"], group_id=7)
        ws.receive_json()  # game_started
        assert subscribe(ws, game.id) == {"type": "subscribed", "game": game.id, "state": game.to_dict()}


def test_unfollow(api_client, remote_client, people):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, token_for(people["admin"])[0])
        follow(ws, all=True)
        ws.send_json({"type": "unfollow", "all": True})
        assert ws.receive_json() == {"type": "unfollowed", "all": True}
        remote_client.create_game(people["alice"], people["bob"], group_id=7)
        nothing_else(ws)


def test_a_bad_follow_is_an_error(api_client, people):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, token_for(people["admin"])[0])
        for bad in ({}, {"group": "7"}, {"all": True, "group": 7}, {"all": False}):
            ws.send_json({"type": "follow", **bad})
            assert ws.receive_json()["code"] == "bad_feed", bad
        nothing_else(ws)


def test_removing_a_group_admin_ends_their_feed_at_the_recheck(api_client, remote_client, people, broker):
    raw, _token_id = token_for(people["mod"])
    with api_client.websocket_connect(WS) as ws:
        ready(ws, raw)
        follow(ws, group=7)
        ops.group_admin_remove(7, people["mod"])
        broker.recheck_user(people["mod"])
        assert ws.receive_json() == {"type": "unfollowed", "group": 7, "reason": "no longer a group admin"}
        remote_client.create_game(people["alice"], people["bob"], group_id=7)
        nothing_else(ws)


def test_identity_links_reach_the_admin_feed(api_client, remote_client, people):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, token_for(people["admin"])[0])
        follow(ws, all=True)
        code, _ = ops.link_code_create(people["carol"], 10)
        remote_client.redeem_link_code("discord", "99", code)
        event = ws.receive_json()
        assert event == {
            "type": "identity_linked",
            "user_id": people["carol"],
            "provider": "discord",
            "external_id": "99",
            "previous_user_id": None,
        }


def test_a_draw_offer_says_who_made_it(api_client, remote_client, user_client, people):
    game = remote_client.create_game(people["alice"], people["bob"], group_id=7)
    with api_client.websocket_connect(WS) as ws:
        ready(ws, token_for(people["bob"])[0])
        subscribe(ws, game.id)
        user_client(people["alice"]).offer_draw(game.id)
        event = ws.receive_json()
        assert event["actor_id"] == people["alice"] and event["requested_by"] == people["alice"]
        assert event["move"] is None
