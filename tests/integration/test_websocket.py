"""
Live updates over ``/v1/ws``: the protocol in ``docs/realtime-websockets.md``.

These run against the shared ``api_client`` app, which ``conftest`` builds with
websockets on, so the REST calls that cause an event and the sockets that receive
it go through one app and one broker. Settings that need other values (short
timeouts, small limits, websockets off) get a second app sharing the same pool.

A ``TestClient`` websocket's ``receive`` blocks until something arrives, so no
test here waits for a message that might not come. To show that nothing *else*
arrived, a test sends ``ping`` and expects the very next message to be ``pong``:
an event published before the ping is queued on the loop before the ping is
handled, so it would come first.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chesssnake.api import realtime
from chesssnake.db import errors
from chesssnake.db import operations as ops

pytestmark = pytest.mark.integration

WS = "/v1/ws"


# --- helpers ---------------------------------------------------------------------


def token_for(user_id):
    """A fresh api token for a user: ``(raw, token_id)``."""
    raw, row = ops.token_create(user_id, ops.TOKEN_API, name="ws-tests")
    return raw, row["id"]


def ready(ws, token):
    """Authenticate a just-opened socket; return the ``ready`` message."""
    ws.send_json({"type": "auth", "token": token})
    message = ws.receive_json()
    assert message["type"] == "ready", message
    return message


def subscribe(ws, game_id):
    ws.send_json({"type": "subscribe", "game": game_id})
    return ws.receive_json()


def nothing_else(ws):
    """Nothing is waiting on this socket (see the module docstring)."""
    ws.send_json({"type": "ping"})
    assert ws.receive_json() == {"type": "pong"}


def closed_with(ws, code):
    """The next thing on the socket is a close with ``code``."""
    with pytest.raises(WebSocketDisconnect) as caught:
        ws.receive_json()
    assert caught.value.code == code, caught.value
    return caught.value


@pytest.fixture
def other_app(settings):
    """``other_app(**websocket_settings)``: a second app on the already-open pool."""
    from contextlib import ExitStack

    from chesssnake.api.server import create_app
    from chesssnake.config import Settings

    stack = ExitStack()

    def make(**ws):
        app = create_app(Settings(database={"url": settings.database.url}, websocket=ws))
        return stack.enter_context(TestClient(app))

    with stack:
        yield make


@pytest.fixture
def broker(api_client):
    return api_client.app.state.broker


@pytest.fixture
def players(users):
    """alice and bob, each with a token: ``players.alice.id`` / ``.token``."""

    class Player:
        def __init__(self, uid):
            self.id = uid
            self.token, self.token_id = token_for(uid)

    class Players:
        pass

    p = Players()
    for name, uid in zip(("alice", "bob", "carol"), users("alice", "bob", "carol"), strict=True):
        setattr(p, name, Player(uid))
    return p


# --- connecting -------------------------------------------------------------------


def test_off_by_default(other_app):
    client = other_app()  # no websocket settings at all
    assert client.app.state.broker.enabled is False
    with pytest.raises(WebSocketDisconnect), client.websocket_connect(WS) as ws:
        ws.receive_json()


def test_ready_names_the_user_and_the_limits(api_client, players):
    with api_client.websocket_connect(WS) as ws:
        message = ready(ws, players.alice.token)
    assert message["user"]["username"] == "alice"
    assert message["limits"] == {"max_subscriptions": 64, "max_message_bytes": 65536}


def test_a_bad_token_is_refused(api_client):
    with api_client.websocket_connect(WS) as ws:
        ws.send_json({"type": "auth", "token": "css_not-a-real-token"})
        closed_with(ws, realtime.CLOSE_UNAUTHORIZED)


def test_auth_must_come_first(api_client, players):
    with api_client.websocket_connect(WS) as ws:
        ws.send_json({"type": "subscribe", "game": 1})
        closed_with(ws, realtime.CLOSE_UNAUTHORIZED)


def test_auth_without_a_token_is_refused(api_client):
    with api_client.websocket_connect(WS) as ws:
        ws.send_json({"type": "auth", "token": 12})
        closed_with(ws, realtime.CLOSE_UNAUTHORIZED)


def test_no_auth_in_time_closes(other_app):
    client = other_app(enabled=True, auth_timeout_seconds=0.1)
    with client.websocket_connect(WS) as ws:
        closed_with(ws, realtime.CLOSE_AUTH_TIMEOUT)


def test_origin_not_allowed_closes_after_accepting(other_app, players):
    client = other_app(enabled=True, allowed_origins=["https://chess.example"])
    with client.websocket_connect(WS, headers={"origin": "https://evil.example"}) as ws:
        closed_with(ws, realtime.CLOSE_ORIGIN)
    with client.websocket_connect(WS, headers={"origin": "https://Chess.Example/"}) as ws:
        ready(ws, players.alice.token)  # normalized: case and a trailing slash do not matter
    with client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)  # no Origin: not a browser; the token is the gate


def test_connection_limits(other_app, players):
    client = other_app(enabled=True, max_connections=2, max_pending_auth=1, max_connections_per_user=1)
    broker = client.app.state.broker
    with client.websocket_connect(WS) as first:
        # One socket waiting to authenticate fills the pending-auth allowance.
        with client.websocket_connect(WS) as second:
            closed_with(second, realtime.CLOSE_LIMIT)
        ready(first, players.alice.token)
        # alice's one allowed socket is in use.
        with client.websocket_connect(WS) as second:
            second.send_json({"type": "auth", "token": players.alice.token})
            closed_with(second, realtime.CLOSE_LIMIT)
        with client.websocket_connect(WS) as second:
            ready(second, players.bob.token)
            # Two open: the total is reached, and a third is refused at once.
            with client.websocket_connect(WS) as third:
                closed_with(third, realtime.CLOSE_LIMIT)
    assert broker.stats() == {"connections": 0, "pending_auth": 0, "topics": 0}


# --- game updates -----------------------------------------------------------------


def test_subscribe_sends_a_snapshot(api_client, remote_client, players):
    game = remote_client.create_game("alice", "bob")
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.carol.token)  # anyone logged in may follow any game
        message = subscribe(ws, game.id)
    assert message["type"] == "subscribed" and message["game"] == game.id
    assert message["state"]["version"] == game.version and message["state"]["fen"] == game.fen


def test_the_opponents_move_arrives_with_the_move(api_client, remote_client, user_client, players):
    game = remote_client.create_game("alice", "bob")
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.bob.token)  # connected after the game began: no game_started
        subscribe(ws, game.id)
        user_client(players.alice.id).move(game.id, "e4")
        message = ws.receive_json()
    assert message["type"] == "game"
    assert message["move"] == {"san": "e4", "from": "e2", "to": "e4", "check": False}
    assert message["state"]["version"] == game.version + 1 and message["state"]["fen"].split()[1] == "b"


def test_draws_resignation_and_the_end_arrive(api_client, remote_client, user_client, players):
    game = remote_client.create_game("alice", "bob")
    alice, bob = user_client(players.alice.id), user_client(players.bob.id)
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.carol.token)
        subscribe(ws, game.id)
        alice.offer_draw(game.id)
        offered = ws.receive_json()
        bob.decline_draw(game.id)
        declined = ws.receive_json()
        bob.resign(game.id)
        over = ws.receive_json()
    assert offered["state"]["draw"] == 0 and offered["move"] is None
    assert declined["state"]["draw"] is None
    assert over["state"]["status"] == 1 and over["state"]["termination"] == "resignation"


def test_a_checkmate_arrives_as_the_last_game_event(api_client, remote_client, user_client, players):
    game = remote_client.create_game("alice", "bob")
    alice, bob = user_client(players.alice.id), user_client(players.bob.id)
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.carol.token)
        subscribe(ws, game.id)
        for mover, san in ((alice, "f3"), (bob, "e5"), (alice, "g4"), (bob, "Qh4")):
            mover.move(game.id, san)
        events = [ws.receive_json() for _ in range(4)]
    assert [e["move"]["san"] for e in events] == ["f3", "e5", "g4", "Qh4#"]
    assert events[-1]["move"]["check"] is True
    assert events[-1]["state"]["status"] == 2 and events[-1]["state"]["termination"] == "checkmate"
    assert [e["state"]["version"] for e in events] == sorted({e["state"]["version"] for e in events})


def test_a_move_event_carries_the_next_players_legal_moves(api_client, remote_client, user_client, players):
    game = remote_client.create_game("alice", "bob")
    alice, bob = user_client(players.alice.id), user_client(players.bob.id)
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.carol.token)
        subscribe(ws, game.id)
        alice.move(game.id, "e4")
        after_e4 = ws.receive_json()
        listed = api_client.get(f"/v1/games/{game.id}/legal-moves").json()["moves"]
        bob.offer_draw(game.id)  # the position does not change: no list
        offered = ws.receive_json()
        for mover, san in ((bob, "e5"), (alice, "Qh5"), (bob, "Nc6"), (alice, "Bc4"), (bob, "Nf6"), (alice, "Qxf7")):
            mover.move(game.id, san)
        mate = [ws.receive_json() for _ in range(6)][-1]
    assert after_e4["legal_moves"] == listed and len(listed) == 20
    assert "legal_moves" not in offered
    assert mate["state"]["termination"] == "checkmate" and mate["legal_moves"] == []


def test_unsubscribe_stops_updates(api_client, remote_client, user_client, players):
    game = remote_client.create_game("alice", "bob")
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.carol.token)
        subscribe(ws, game.id)
        ws.send_json({"type": "unsubscribe", "game": game.id})
        user_client(players.alice.id).move(game.id, "e4")
        nothing_else(ws)


def test_subscribing_twice_is_one_subscription(api_client, remote_client, user_client, players):
    game = remote_client.create_game("alice", "bob")
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.carol.token)
        subscribe(ws, game.id)
        ws.send_json({"type": "subscribe", "game": game.id})  # no second snapshot
        user_client(players.alice.id).move(game.id, "e4")
        assert ws.receive_json()["type"] == "game"
        nothing_else(ws)


def test_a_finished_game_can_be_followed(api_client, remote_client, user_client, players):
    game = remote_client.create_game("alice", "bob")
    user_client(players.bob.id).resign(game.id)
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.carol.token)
        message = subscribe(ws, game.id)
    assert message["type"] == "subscribed" and message["state"]["status"] == 1


def test_bad_game_ids_are_errors_not_closes(api_client, players):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        for bad in (True, "7", 1.5, None, 2**63):
            assert subscribe(ws, bad) == {
                "type": "error",
                "code": "bad_game",
                "detail": "game must be an integer id",
            }, bad
        assert subscribe(ws, 999_999)["code"] == "not_found"
        nothing_else(ws)  # still open


def test_the_subscription_limit(other_app, remote_client, players):
    client = other_app(enabled=True, max_subscriptions=1)
    first = remote_client.create_game("alice", "bob")
    second = remote_client.create_game("alice", "carol")
    with client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        assert subscribe(ws, first.id)["type"] == "subscribed"
        assert subscribe(ws, second.id)["code"] == "too_many_subscriptions"
        ws.send_json({"type": "unsubscribe", "game": first.id})
        assert subscribe(ws, second.id)["type"] == "subscribed"


# --- the user's own events ------------------------------------------------------


def test_a_game_created_by_an_admin_is_announced_to_both_players(api_client, remote_client, players):
    with api_client.websocket_connect(WS) as a, api_client.websocket_connect(WS) as c:
        ready(a, players.alice.token)
        ready(c, players.carol.token)
        game = remote_client.create_game("alice", "bob")
        started = a.receive_json()
        nothing_else(c)  # not carol's game
    assert started == {"type": "game_started", "state": started["state"]}
    assert started["state"]["id"] == game.id


def test_challenges_reach_both_parties_and_nobody_else(api_client, user_client, players):
    sockets = {name: api_client.websocket_connect(WS) for name in ("alice", "bob", "carol")}
    with sockets["alice"] as a, sockets["bob"] as b, sockets["carol"] as c:
        for ws, name in ((a, "alice"), (b, "bob"), (c, "carol")):
            ready(ws, getattr(players, name).token)
        challenge = user_client(players.alice.id).challenge("bob", color="white")
        created = [a.receive_json(), b.receive_json()]
        nothing_else(c)

        game = user_client(players.bob.id).accept_challenge(challenge.id)
        for ws in (a, b):
            removed, started = ws.receive_json(), ws.receive_json()
            assert removed["type"] == "challenge" and removed["event"] == "removed"
            assert removed["challenge"]["id"] == challenge.id
            assert started["type"] == "game_started" and started["state"]["id"] == game.id
        nothing_else(c)
    for message in created:
        assert message["type"] == "challenge" and message["event"] == "created"
        assert message["challenge"]["id"] == challenge.id


def test_a_declined_challenge_is_removed_for_the_challenger(api_client, user_client, players):
    challenge = user_client(players.alice.id).challenge("bob")
    with api_client.websocket_connect(WS) as a:
        ready(a, players.alice.token)
        user_client(players.bob.id).decline_challenge(challenge.id)
        message = a.receive_json()
    assert message["event"] == "removed" and message["challenge"]["id"] == challenge.id


def test_a_deleted_game_is_announced_and_unsubscribed(api_client, remote_client, players):
    game = remote_client.create_game("alice", "bob")
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.carol.token)
        subscribe(ws, game.id)
        remote_client.delete_game(game.id)
        assert ws.receive_json() == {"type": "game_removed", "game": game.id}
        nothing_else(ws)
    assert api_client.app.state.broker.stats()["topics"] == 0


# --- revocation ---------------------------------------------------------------------


def test_logging_out_closes_that_tokens_sockets_at_once(api_client, user_client, players):
    from chesssnake.remote.client import ApiClient

    with api_client.websocket_connect(WS) as mine, api_client.websocket_connect(WS) as other:
        ready(mine, players.alice.token)
        ready(other, token_for(players.alice.id)[0])  # alice, another token
        ApiClient("", session=api_client, token=players.alice.token).logout()
        closed_with(mine, realtime.CLOSE_UNAUTHORIZED)
        nothing_else(other)  # the other login is untouched


def test_revoking_a_token_closes_its_sockets(api_client, remote_client, players):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        remote_client.revoke_token(players.alice.token_id)
        closed_with(ws, realtime.CLOSE_UNAUTHORIZED)


def test_disabling_a_user_closes_their_sockets(api_client, remote_client, players):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        remote_client.update_user(players.alice.id, disabled=True)
        closed_with(ws, realtime.CLOSE_UNAUTHORIZED)


def test_an_admin_password_reset_closes_their_sockets(api_client, remote_client, players):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        remote_client.update_user(players.alice.id, password="a-brand-new-password")
        closed_with(ws, realtime.CLOSE_UNAUTHORIZED)


def test_a_database_error_while_rechecking_keeps_the_socket(other_app, players, monkeypatch):
    client = other_app(enabled=True, reauth_interval_seconds=0.02)
    calls = threading.Semaphore(0)

    def busy(_token):
        calls.release()
        raise errors.SQLBusyError("database is locked")

    with client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        monkeypatch.setattr(realtime, "authenticate", busy)
        for _ in range(3):
            assert calls.acquire(timeout=5), "the token is re-checked on the interval"
        nothing_else(ws)
        monkeypatch.undo()


def test_the_periodic_recheck_closes_a_revoked_token(other_app, players):
    # Revoked straight in the database, so no route tells the broker: only the
    # interval can notice. This is the backstop for every path that is not a route.
    client = other_app(enabled=True, reauth_interval_seconds=0.05)
    with client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        ops.token_delete(players.alice.token_id, players.alice.id)
        closed_with(ws, realtime.CLOSE_UNAUTHORIZED)


# --- bad input ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "frame",
    ["not json", "[]", '{"no": "type"}', '{"type": 7}', "[" * 5_000],
    ids=["not-json", "array", "no-type", "type-not-a-string", "deeply-nested"],
)
def test_malformed_messages_close(api_client, players, frame):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        ws.send_text(frame)
        closed_with(ws, realtime.CLOSE_MALFORMED)


def test_binary_frames_close(api_client, players):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        ws.send_bytes(b'{"type": "ping"}')
        closed_with(ws, realtime.CLOSE_MALFORMED)


def test_unknown_message_types_close(api_client, players):
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        ws.send_json({"type": "move", "game": 1, "move": "e4"})  # moves are REST, not here
        closed_with(ws, realtime.CLOSE_MALFORMED)


def test_an_oversized_message_closes(other_app, players):
    client = other_app(enabled=True, max_message_bytes=1024)
    with client.websocket_connect(WS) as ws:
        ready(ws, players.alice.token)
        ws.send_text('{"type": "ping", "pad": "' + "x" * 1024 + '"}')
        closed_with(ws, realtime.CLOSE_TOO_BIG)


def test_a_full_send_queue_closes_the_socket(other_app, players, monkeypatch):
    # TestClient sends never block, so a slow reader cannot be simulated; a sender
    # that never sends is the same thing from the queue's point of view.
    async def stuck(self):
        import anyio

        await anyio.sleep_forever()

    monkeypatch.setattr(realtime.Connection, "_sender", stuck)
    client = other_app(enabled=True, send_queue_size=2)
    with client.websocket_connect(WS) as ws:
        ws.send_json({"type": "auth", "token": players.alice.token})  # "ready": 1 queued
        ws.send_json({"type": "ping"})  # 2
        ws.send_json({"type": "ping"})  # 3: over
        closed_with(ws, realtime.CLOSE_TRY_LATER)


# --- bookkeeping --------------------------------------------------------------------


def test_counters_return_to_zero(api_client, remote_client, broker, players):
    game = remote_client.create_game("alice", "bob")
    for _ in range(3):
        with api_client.websocket_connect(WS) as ws:
            ready(ws, players.alice.token)
            subscribe(ws, game.id)
    deadline = time.monotonic() + 5
    while broker.stats()["connections"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert broker.stats() == {"connections": 0, "pending_auth": 0, "topics": 0}
    assert broker._per_user == {}


def test_publishing_with_nobody_connected_costs_nothing(api_client, user_client, remote_client, broker, players):
    game = remote_client.create_game("alice", "bob")
    assert broker.stats()["connections"] == 0
    user_client(players.alice.id).move(game.id, "e4")  # must not raise or queue anything


def test_publishing_never_fails_a_request(api_client, user_client, remote_client, broker, players, monkeypatch):
    """The move is committed before publishing; a broken publish must not make it a 500."""
    game = remote_client.create_game("alice", "bob")
    with api_client.websocket_connect(WS) as ws:
        ready(ws, players.carol.token)

        class ClosedLoop:
            def call_soon_threadsafe(self, *args):
                raise RuntimeError("Event loop is closed")

        monkeypatch.setattr(broker, "_loop", ClosedLoop())
        result = user_client(players.alice.id).move(game.id, "e4")
        monkeypatch.undo()
        nothing_else(ws)
    assert result.san == "e4"


# --- ordering: a connection never goes backwards ------------------------------------


class _Sink:
    """A stand-in for a websocket and broker: records what would have been sent."""

    def __init__(self):
        from chesssnake.config import WebsocketSettings

        self.settings = WebsocketSettings(enabled=True)
        self.topics = {}

    def subscribe(self, conn, topic):
        pass

    def unsubscribe(self, conn, topic):
        pass


def _connection():
    import json

    conn = realtime.Connection(websocket=None, broker=_Sink())
    sent = []

    def out():
        while not conn.queue.empty():
            sent.append(json.loads(conn.queue.get_nowait()))
        return sent

    return conn, out


def _game(version):
    return {"type": "game", "state": {"id": 1, "version": version}, "move": None}


def _deliver(conn, version):
    import json

    message = _game(version)
    conn.deliver("game", json.dumps(message), message["state"], None)


def test_an_older_state_never_follows_a_newer_one():
    conn, out = _connection()
    conn.seen[1] = 4
    for version in (6, 5, 6, 7):  # two worker threads publishing out of order
        _deliver(conn, version)
    assert [m["state"]["version"] for m in out()] == [6, 7]


def test_events_during_a_snapshot_read_are_held_and_the_newest_kept():
    conn, out = _connection()
    conn.pending[1] = None  # the snapshot read is in flight
    for version in (6, 8, 7):
        _deliver(conn, version)
    assert out() == [], "nothing is sent before the snapshot"
    assert conn.pending[1]["version"] == 8, "the snapshot will be upgraded to this"
