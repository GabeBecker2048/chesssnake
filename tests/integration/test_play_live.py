"""
``chesssnake play`` with live updates, against a real server.

Everything else in this directory uses ``TestClient``, which has no network. Live
updates are a client opening a real websocket next to its REST session, so these
start uvicorn on a pre-bound localhost socket in a thread (sharing the suite's
database pool) and drive the real :class:`~chesssnake.remote.realtime.EventStream`
and the real ``play`` loop against it. The session's stdin is an ``os.pipe``, so
its ``select`` has a real fd and nothing here polls.
"""

import io
import os
import socket
import threading
import time

import pytest

from chesssnake.db import operations as ops

pytest.importorskip("websockets")
pytest.importorskip("requests")

pytestmark = pytest.mark.integration


class LiveServer:
    """uvicorn serving one app in a thread, on a port the OS picked."""

    def __init__(self, app, port=0):
        import uvicorn

        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        self.port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(app, log_config=None, log_level="warning", lifespan="on", timeout_graceful_shutdown=2)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [sock]}, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert self.thread.is_alive() and time.monotonic() < deadline, "the server did not start"
            time.sleep(0.01)

    def stop(self):
        """Shut down; return how long it took."""
        started = time.monotonic()
        self.server.should_exit = True
        self.thread.join(timeout=10)
        assert not self.thread.is_alive(), "the server did not shut down"
        return time.monotonic() - started


@pytest.fixture
def serve(api_client, settings):
    """``serve(port=0, **websocket_settings)`` -> a running :class:`LiveServer` on the suite's database."""
    from chesssnake.api.server import create_app
    from chesssnake.config import Settings

    servers = []

    def start(port=0, **ws):
        app = create_app(Settings(database={"url": settings.database.url}, websocket=ws))
        servers.append(LiveServer(app, port))
        return servers[-1]

    yield start
    for server in servers:
        if server.thread.is_alive():
            server.stop()


@pytest.fixture
def people(users):
    """alice and bob, each with a token."""
    ids = dict(zip(("alice", "bob"), users("alice", "bob"), strict=True))
    return {name: (uid, ops.token_create(uid, ops.TOKEN_API, name="live")[0]) for name, uid in ids.items()}


def client_for(server, people, name):
    from chesssnake.remote.client import ApiClient

    return ApiClient(server.url, token=people[name][1])


class PlaySession:
    """A ``play`` session in a thread, with a pipe for stdin and a buffer for output."""

    def __init__(self, game, player_id, events):
        from chesssnake.play import Session

        read_fd, write_fd = os.pipe()
        self.stdin, self.writer = os.fdopen(read_fd, "r"), os.fdopen(write_fd, "w")
        self.out = io.StringIO()
        self.session = Session(game, player_id=player_id, stdin=self.stdin, stdout=self.out, color=False, events=events)
        self.status = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        self.status = self.session.run()

    def wait_for(self, text, timeout=5):
        """Seconds until ``text`` appeared in the output."""
        started = time.monotonic()
        while text not in self.out.getvalue():
            assert self.thread.is_alive() or text in self.out.getvalue(), self.out.getvalue()[-600:]
            assert time.monotonic() - started < timeout, f"{text!r} never appeared:\n{self.out.getvalue()[-600:]}"
            time.sleep(0.002)
        return time.monotonic() - started

    def type(self, line):
        self.writer.write(line + "\n")
        self.writer.flush()

    def finish(self):
        self.type("quit")
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        self.writer.close()
        return self.status


def open_session(server, people, name, game_id):
    from chesssnake.remote.game import Game

    client = client_for(server, people, name)
    game = Game.remote(game_id, client=client)
    return PlaySession(game, people[name][0], client.events([game_id]))


def test_the_opponents_move_appears_live(serve, people):
    server = serve(enabled=True)
    challenge = client_for(server, people, "alice").challenge("bob", color="white")
    game = client_for(server, people, "bob").accept_challenge(challenge.id)
    bob = open_session(server, people, "bob", game.id)
    bob.wait_for("> ")

    sent = time.monotonic()
    client_for(server, people, "alice").move(game.id, "e4")
    bob.wait_for("alice played e4")
    latency_ms = (time.monotonic() - sent) * 1000
    print(f"\nmove request sent -> shown in the other player's session: {latency_ms:.1f} ms")
    assert latency_ms < 2000
    assert bob.session.game.version == game.version + 1
    assert bob.finish() == 0
    bob.session.events.close()


def test_a_rematch_reaches_the_finished_games_session(serve, people):
    server = serve(enabled=True)
    alice_api, bob_api = client_for(server, people, "alice"), client_for(server, people, "bob")
    first = bob_api.accept_challenge(alice_api.challenge("bob", color="white").id)
    bob = open_session(server, people, "bob", first.id)
    bob.wait_for("> ")

    alice_api.resign(first.id)
    bob.wait_for("game over")
    alice_api.challenge("bob", color="white")
    bob.wait_for("alice challenged you to a rematch - `new` accepts")
    bob.type("new")
    bob.wait_for("rematch - game")
    assert bob.session.game.id != first.id
    # The new game is followed live too: the subscription moved with the session.
    alice_api.move(bob.session.game.id, "d4")
    bob.wait_for("alice played d4")
    bob.finish()
    bob.session.events.close()


def test_logging_out_elsewhere_ends_the_session(serve, people):
    server = serve(enabled=True)
    alice_api, bob_api = client_for(server, people, "alice"), client_for(server, people, "bob")
    game = bob_api.accept_challenge(alice_api.challenge("bob").id)
    bob = open_session(server, people, "bob", game.id)
    bob.wait_for("> ")

    bob_api.logout()  # the same token, as `chesssnake logout` in another terminal would
    bob.wait_for("chesssnake login")
    bob.thread.join(timeout=5)
    assert bob.status == 1
    if bob.session.events is not None:
        bob.session.events.close()


def test_without_websockets_the_client_is_told_to_poll(serve, people):
    from chesssnake.remote.realtime import RealtimeUnavailable

    server = serve(enabled=False)
    with pytest.raises(RealtimeUnavailable, match="websockets turned off"):
        client_for(server, people, "alice").events()


def test_the_cli_falls_back_to_polling_with_a_note(serve, people, capsys):
    from chesssnake.cli import _live_updates

    server = serve(enabled=False)
    assert _live_updates(client_for(server, people, "alice"), 1, 10) is None
    assert "note: no live updates: the server has websockets turned off; polling every 10 s" in capsys.readouterr().err


def test_a_bad_token_is_an_auth_error_not_a_fallback(serve, people):
    from chesssnake.db.errors import AuthError
    from chesssnake.remote.client import ApiClient

    server = serve(enabled=True)
    with pytest.raises(AuthError):
        ApiClient(server.url, token="css_not-a-real-token").events()


def test_a_server_restart_is_survived(serve, people):
    """Shutdown closes sockets with 1012; the stream reconnects and re-subscribes."""
    server = serve(enabled=True)
    alice_api, bob_api = client_for(server, people, "alice"), client_for(server, people, "bob")
    game = bob_api.accept_challenge(alice_api.challenge("bob", color="white").id)
    stream = bob_api.events([game.id])
    try:
        seconds = server.stop()
        assert seconds < 3, f"shutdown with a socket open took {seconds:.1f} s"

        events = _collect(stream, lambda e: e["type"] == "disconnected")
        assert events[-1]["code"] in (1001, 1006, 1012), events

        restarted = serve(port=server.port, enabled=True)  # back, on the URL the stream knows
        events = _collect(stream, lambda e: e["type"] == "subscribed", timeout=10)
        assert any(e["type"] == "reconnected" for e in events)
        assert events[-1]["game"] == game.id
        alice_api.move(game.id, "e4")
        events = _collect(stream, lambda e: e["type"] == "game")
        assert events[-1]["move"]["san"] == "e4"
        restarted.stop()
    finally:
        stream.close()


def _collect(stream, until, timeout=5):
    import select

    seen, deadline = [], time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0, f"timed out; saw {seen}"
        select.select([stream.fileno()], [], [], remaining)
        for event in stream.drain():
            seen.append(event)
            if until(event):
                return seen


class _BadGateway:
    """What a reverse proxy answers while its upstream restarts: HTTP 502 to everything."""

    def __init__(self, port):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"  # as Caddy answers; websockets rejects 1.0 outright

            def do_GET(self):
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        ThreadingHTTPServer.allow_reuse_address = True
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def test_a_proxys_502_during_a_restart_is_retried_not_the_end(serve, people, monkeypatch):
    """
    Behind Caddy, a reconnect during a restart is answered 502, not refused.

    0.13.0 treated any HTTP status on a reconnect as "websockets were turned off"
    and gave up, so a restart behind a proxy ended live updates for good. Found on
    the deployment; locally a restart only ever gave "connection refused".
    """
    from chesssnake.remote import realtime

    # Short waits, so several reconnects land while the "proxy" is answering.
    monkeypatch.setattr(realtime, "BACKOFF_START", 0.1)
    monkeypatch.setattr(realtime, "BACKOFF_MAX", 0.2)
    server = serve(enabled=True)
    stream = client_for(server, people, "alice").events()
    try:
        server.stop()
        assert _collect(stream, lambda e: e["type"] == "disconnected")[-1]["type"] == "disconnected"
        proxy = _BadGateway(server.port)
        time.sleep(1.5)  # several reconnects, each answered 502
        proxy.stop()
        assert all(e["type"] != "ended" for e in stream.drain()), "a 502 ended the stream"
        restarted = serve(port=server.port, enabled=True)
        events = _collect(stream, lambda e: e["type"] in ("reconnected", "ended"), timeout=10)
        assert events[-1]["type"] == "reconnected", events
        restarted.stop()
    finally:
        stream.close()


def test_websockets_turned_off_across_a_restart_ends_the_stream(serve, people, monkeypatch):
    """The one answer to a reconnect that means stop: the server is up and refuses (403)."""
    from chesssnake.remote import realtime

    monkeypatch.setattr(realtime, "BACKOFF_START", 0.1)
    monkeypatch.setattr(realtime, "BACKOFF_MAX", 0.2)
    server = serve(enabled=True)
    stream = client_for(server, people, "alice").events()
    try:
        server.stop()
        restarted = serve(port=server.port, enabled=False)  # back, with websockets off
        events = _collect(stream, lambda e: e["type"] in ("reconnected", "ended"), timeout=10)
        assert events[-1]["type"] == "ended" and "turned off" in events[-1]["reason"], events
        restarted.stop()
    finally:
        stream.close()
