"""
Real-time updates over a websocket at ``/v1/ws``. On unless ``websocket.enabled`` is false.

The protocol is specified in ``docs/websocket-api.md``. In short: a client
connects, sends ``{"type": "auth", "token": ...}`` first, then subscribes to games;
the server pushes each game's new state as it changes, plus the user's own events
(challenges to them, games they start) without being asked. An administrator can
also *follow* every game (``{"type": "follow", "all": true}``), and a group's
admins that group's games (``{"type": "follow", "group": G}``): that feed carries
every game event, new games included, without subscribing to each.

How events get here. The REST routes are plain ``def`` functions running in the
threadpool; this module's sockets live on the event loop. After a route commits a
change it calls the app's :class:`Broker` (``app.state.broker``), which serializes
the message once in that worker thread and hands it to the loop with
``loop.call_soon_threadsafe``, the one thread-safe way in. Everything that touches
a socket, a queue or the subscription tables then runs on the loop thread alone.

Each app has its own broker. The ``v1`` router object is shared by every app built
in a process (the test-suite builds several), so a module-level broker would send
one app's events to another app's sockets.

Fan-out is in-process: a change made through another server process (several
uvicorn workers, several replicas on PostgreSQL) is not seen here. :class:`Broker`
is the seam where a PostgreSQL LISTEN/NOTIFY implementation would go.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import TYPE_CHECKING, Any, TypeGuard

import anyio
from fastapi import WebSocket

from ..db import errors
from ..db import operations as ops
from ..dto import GameState, User
from .auth import Principal, authenticate

if TYPE_CHECKING:
    from ..config import WebsocketSettings

logger = logging.getLogger(__name__)

#: Close codes, all sent after the upgrade is accepted (a close *before* accepting
#: reaches a real client as a bare HTTP 403 and loses the code).
CLOSE_MALFORMED = 4400
CLOSE_UNAUTHORIZED = 4401
CLOSE_ORIGIN = 4403
CLOSE_AUTH_TIMEOUT = 4408
CLOSE_LIMIT = 4429
CLOSE_TOO_BIG = 1009
CLOSE_TRY_LATER = 1013


class Broker:
    """
    Where routes report changes. This base class drops everything: it is what an
    app gets when websockets are off, so publishing costs a REST request nothing.
    """

    enabled = False

    def game_changed(
        self, state: dict, move: dict | None = None, legal_moves: list | None = None, who: dict | None = None
    ) -> None:
        """A game's state changed (a move, a draw offer, the end). ``legal_moves``,
        given for a move, are the next player's options and ride on the event;
        ``who`` (``actor_id``, ``requested_by``) says who made the change."""

    def game_started(self, state: dict, who: dict | None = None) -> None:
        """A game began; both players hear of it. ``who`` as for :meth:`game_changed`."""

    def game_removed(self, game_id: int, group_id: int | None = None) -> None:
        """An administrator deleted a game (of ``group_id``, for that group's feed)."""

    def challenge(self, event: str, challenge: dict) -> None:
        """A challenge was ``created`` or ``removed`` (declined, withdrawn or accepted)."""

    def identity_linked(self, user_id: int, provider: str, external_id: str, previous_user_id: int | None) -> None:
        """An outside id was linked to a user (and moved off ``previous_user_id``)."""

    def recheck_token(self, token_id: int) -> None:
        """A token may have been revoked: sockets using it check it again now."""

    def recheck_user(self, user_id: int) -> None:
        """A user's tokens may have been revoked (password change, disable): their sockets check again now."""


#: The topic of the feed of every game, which global administrators may follow.
_ALL = ("all", 0)


def _feed(group_id, *topics):
    """``topics`` plus the feeds that also carry an event in ``group_id``."""
    return (*topics, ("group", group_id), _ALL)


class InProcessBroker(Broker):
    """Delivers changes to the websockets of this process."""

    enabled = True

    def __init__(self, settings: WebsocketSettings) -> None:
        self.settings = settings
        self._loop: asyncio.AbstractEventLoop | None = None
        self._limiter: anyio.CapacityLimiter | None = None
        self._topics: dict[tuple[str, int], set[Connection]] = {}
        self._connections: set[Connection] = set()
        self._per_user: dict[int, int] = {}

    # --- called from the REST routes' worker threads ---------------------------

    def game_changed(self, state, move=None, legal_moves=None, who=None):
        message = {"type": "game", "state": state, "move": move}
        if legal_moves is not None:
            message["legal_moves"] = legal_moves
        if who:
            message.update(who)
        self._publish(_feed(state["group_id"], ("game", state["id"])), "game", message, state=state)

    def game_started(self, state, who=None):
        message = {"type": "game_started", "state": state}
        if who:
            message.update(who)
        players = [("user", player) for player in {state["white_id"], state["black_id"]}]
        self._publish(_feed(state["group_id"], *players), "event", message)

    def game_removed(self, game_id, group_id=None):
        topics = _feed(group_id, ("game", game_id)) if group_id is not None else (("game", game_id), _ALL)
        self._publish(topics, "removed", {"type": "game_removed", "game": game_id}, game_id=game_id)

    def challenge(self, event, challenge):
        message = {"type": "challenge", "event": event, "challenge": challenge}
        parties = [("user", party) for party in {challenge["challenger_id"], challenge["challenged_id"]}]
        self._publish(_feed(challenge["group_id"], *parties), "event", message)

    def identity_linked(self, user_id, provider, external_id, previous_user_id):
        message = {
            "type": "identity_linked",
            "user_id": user_id,
            "provider": provider,
            "external_id": external_id,
            "previous_user_id": previous_user_id,
        }
        self._publish((_ALL,), "event", message)

    def recheck_token(self, token_id):
        self._publish((("token", token_id),), "recheck", None)

    def recheck_user(self, user_id):
        self._publish((("user", user_id),), "recheck", None)

    def _publish(self, topics, kind, message, *, state=None, game_id=None):
        """
        Hand a message to the event loop. Never raises.

        The change is already committed when a route calls this; an exception
        here would turn a saved move into a 500 and invite a retry that fails.
        """
        loop = self._loop
        if loop is None or not self._connections:
            return  # nobody has ever connected, or nobody is connected now
        try:
            text = json.dumps(message, separators=(",", ":")) if message is not None else None
            loop.call_soon_threadsafe(self._dispatch, topics, kind, text, state, game_id)
        except RuntimeError:
            pass  # the loop has closed: the server is shutting down
        except Exception:  # pragma: no cover - defensive; must never fail the request
            logger.exception("could not publish a websocket event for %s", topics)

    # --- everything below runs on the event loop thread ------------------------

    def _dispatch(self, topics, kind, text, state, game_id):
        # A connection on several of the topics (a player who also follows the
        # feed) gets the message once.
        receivers = set()
        for topic in topics:
            receivers.update(self._topics.get(topic, ()))
        for conn in receivers:
            conn.deliver(kind, text, state, game_id)

    @property
    def limiter(self) -> anyio.CapacityLimiter:
        assert self._limiter is not None
        return self._limiter

    def admit(self, conn: Connection) -> str | None:
        """Register a just-accepted socket, or say why not (the reason closes it)."""
        if self._loop is None:
            # Captured lazily: this is the first code that is sure to run on the
            # loop, and a broker whose app never started has no loop to capture.
            self._loop = asyncio.get_running_loop()
            self._limiter = anyio.CapacityLimiter(self.settings.worker_threads)
        pending = sum(1 for c in self._connections if c.principal is None)
        if len(self._connections) >= self.settings.max_connections:
            return "too many connections"
        if pending >= self.settings.max_pending_auth:
            return "too many connections waiting to authenticate"
        self._connections.add(conn)
        return None

    def authenticated(self, conn: Connection, principal: Principal) -> str | None:
        """Count a socket against its user, or say why not. No await before this returns."""
        if self._per_user.get(principal.user_id, 0) >= self.settings.max_connections_per_user:
            return "too many connections for this user"
        self._per_user[principal.user_id] = self._per_user.get(principal.user_id, 0) + 1
        conn.principal = principal
        self.subscribe(conn, ("user", principal.user_id))
        self.subscribe(conn, ("token", principal.token_id))
        return None

    def subscribe(self, conn: Connection, topic: tuple[str, int]) -> None:
        self._topics.setdefault(topic, set()).add(conn)
        conn.topics.add(topic)

    def unsubscribe(self, conn: Connection, topic: tuple[str, int]) -> None:
        subscribers = self._topics.get(topic)
        if subscribers is not None:
            subscribers.discard(conn)
            if not subscribers:
                del self._topics[topic]
        conn.topics.discard(topic)

    def unregister(self, conn: Connection) -> None:
        for topic in list(conn.topics):
            self.unsubscribe(conn, topic)
        if conn in self._connections:
            self._connections.discard(conn)
            if conn.principal is not None:
                uid = conn.principal.user_id
                self._per_user[uid] -= 1
                if not self._per_user[uid]:
                    del self._per_user[uid]

    def stats(self) -> dict[str, int]:
        """Connection counts, for tests and diagnostics."""
        return {
            "connections": len(self._connections),
            "pending_auth": sum(1 for c in self._connections if c.principal is None),
            "topics": len(self._topics),
        }


class Connection:
    """One websocket: its user, its subscriptions, and its outgoing queue."""

    def __init__(self, websocket: WebSocket, broker: InProcessBroker):
        self.websocket = websocket
        self.broker = broker
        self.settings = broker.settings
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.settings.send_queue_size)
        self.principal: Principal | None = None
        self.token: str | None = None
        self.topics: set[tuple[str, int]] = set()
        #: Games subscribed to, and the newest version sent (or snapshotted) of each.
        self.seen: dict[int, int] = {}
        #: Games whose snapshot is still being read, with the newest state that
        #: arrived meanwhile (it replaces an older snapshot when that lands).
        self.pending: dict[int, dict | None] = {}
        #: Games in progress heard of only through a followed feed, and the newest
        #: version sent of each; kept apart from ``seen`` so they neither count as
        #: subscriptions nor stop a later ``subscribe`` from sending its snapshot.
        self.fed: dict[int, int] = {}
        #: The feeds followed: group ids, and ``None`` for every game.
        self.follows: set[int | None] = set()
        self.close_code: int | None = None
        self.close_reason = ""
        self._scope: anyio.CancelScope | None = None
        self._task_group: Any = None
        self.recheck_now = asyncio.Event()

    # --- the one way to close ----------------------------------------------------

    def request_close(self, code: int | None, reason: str = "") -> None:
        """Ask for the socket to close. Idempotent; the handler does the closing, once."""
        if self.close_code is None and code is not None:
            self.close_code, self.close_reason = code, reason
        if self._scope is not None:
            self._scope.cancel()

    # --- events from the broker (loop thread) ---------------------------------------

    def deliver(self, kind: str, text: str | None, state: dict | None, game_id: int | None) -> None:
        if kind == "recheck":
            self.recheck_now.set()
            return
        if kind == "game" and state is not None:
            gid, version = state["id"], state["version"]
            if gid in self.pending:
                newest = self.pending[gid]
                if newest is None or version > newest["version"]:
                    self.pending[gid] = state
                return  # the snapshot, when it lands, carries this or something newer
            if version <= max(self.seen.get(gid, -1), self.fed.get(gid, -1)):
                return  # an older state overtaken on the way here: never go backwards
            if gid in self.seen:
                self.seen[gid] = version
            elif state.get("status", 0) == 0:
                self.fed[gid] = version
            else:
                self.fed.pop(gid, None)  # over: it will not change again
        elif kind == "removed" and game_id is not None:
            self.broker.unsubscribe(self, ("game", game_id))
            self.seen.pop(game_id, None)
            self.pending.pop(game_id, None)
            self.fed.pop(game_id, None)
        if text is not None:
            self.enqueue(text)

    def enqueue(self, text: str) -> None:
        try:
            self.queue.put_nowait(text)
        except asyncio.QueueFull:
            self.request_close(CLOSE_TRY_LATER, "too many messages waiting; reconnect and subscribe again")

    def send(self, message: dict) -> None:
        self.enqueue(json.dumps(message, separators=(",", ":")))

    # --- the tasks ----------------------------------------------------------------

    async def _sender(self) -> None:
        # The only task that writes to the socket.
        try:
            while True:
                await self.websocket.send_text(await self.queue.get())
        except Exception:  # the peer went away mid-send
            self.request_close(None)

    async def _auth_deadline(self) -> None:
        await anyio.sleep(self.settings.auth_timeout_seconds)
        if self.principal is None:
            self.request_close(CLOSE_AUTH_TIMEOUT, "no auth message in time")

    async def _reauth(self) -> None:
        """Check the token again every interval, or at once when told it may be revoked."""
        interval = self.settings.reauth_interval_seconds
        while True:
            with anyio.move_on_after(interval * random.uniform(0.9, 1.1)):
                await self.recheck_now.wait()
            self.recheck_now.clear()
            try:
                self.principal = await self._in_thread(authenticate, self.token)
                for group in [g for g in self.follows if g is not None]:
                    # A group admin who was removed stops hearing that group's games.
                    if not await self._in_thread(self.principal.administers, group):
                        self._unfollow(group)
                        self.send({"type": "unfollowed", "group": group, "reason": "no longer a group admin"})
                if None in self.follows and not self.principal.is_admin:
                    self._unfollow(None)
                    self.send({"type": "unfollowed", "all": True, "reason": "no longer an administrator"})
            except errors.AuthError:
                self.request_close(CLOSE_UNAUTHORIZED, "the token is no longer valid; log in again")
                return
            except errors.GameError:
                logger.warning("could not re-check a websocket's token; trying again later", exc_info=True)

    async def _in_thread(self, fn, *args):
        return await anyio.to_thread.run_sync(fn, *args, limiter=self.broker.limiter)

    async def _receive_loop(self) -> None:
        """Handle one message at a time; returns when the client disconnects."""
        while True:
            message = await self.websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            text = message.get("text")
            if text is None:
                self.request_close(CLOSE_MALFORMED, "send JSON text frames")
                return
            if len(text) > self.settings.max_message_bytes or len(text.encode()) > self.settings.max_message_bytes:
                self.request_close(CLOSE_TOO_BIG, "message too large")
                return
            try:
                data = json.loads(text)
            except (ValueError, RecursionError):
                self.request_close(CLOSE_MALFORMED, "not JSON")
                return
            if not isinstance(data, dict) or not isinstance(data.get("type"), str):
                self.request_close(CLOSE_MALFORMED, 'every message is an object with a "type"')
                return
            if not await self._handle(data):
                return

    async def _handle(self, data: dict) -> bool:
        kind = data["type"]
        if self.principal is None:
            if kind != "auth":
                self.request_close(CLOSE_UNAUTHORIZED, "authenticate first")
                return False
            return await self._authenticate(data.get("token"))
        if kind == "subscribe":
            await self._subscribe(data.get("game"))
        elif kind == "unsubscribe":
            game = data.get("game")
            if _is_id(game):
                self.broker.unsubscribe(self, ("game", game))
                self.seen.pop(game, None)
                self.pending.pop(game, None)
        elif kind == "follow":
            await self._follow(data)
        elif kind == "unfollow":
            target = self._feed_target(data)
            if target is not False:
                self._unfollow(target)
                self.send({"type": "unfollowed", **self._feed_label(target)})
        elif kind == "ping":
            self.send({"type": "pong"})
        else:
            self.request_close(CLOSE_MALFORMED, f"unknown message type {kind!r}")
            return False
        return True

    async def _authenticate(self, token) -> bool:
        if not isinstance(token, str):
            self.request_close(CLOSE_UNAUTHORIZED, "the auth message needs a token")
            return False
        try:
            principal = await self._in_thread(authenticate, token)
            user = await self._in_thread(ops.user_get, principal.user_id)
        except errors.AuthError:
            self.request_close(CLOSE_UNAUTHORIZED, "invalid, expired or revoked token")
            return False
        except errors.GameError:
            self.request_close(CLOSE_TRY_LATER, "the server is busy; try again shortly")
            return False
        refusal = self.broker.authenticated(self, principal)
        if refusal is not None:
            self.request_close(CLOSE_LIMIT, refusal)
            return False
        self.token = token
        self._scope_start(self._reauth)
        self.send(
            {
                "type": "ready",
                "user": User.from_row(user).to_dict() if user else None,
                "limits": {
                    "max_subscriptions": self.settings.max_subscriptions,
                    "max_message_bytes": self.settings.max_message_bytes,
                },
            }
        )
        return True

    def _scope_start(self, fn) -> None:
        # Started from inside the task group's own task, so it is cancelled with it.
        assert self._task_group is not None
        self._task_group.start_soon(fn)

    async def _subscribe(self, game) -> None:
        if not _is_id(game):
            self.send({"type": "error", "code": "bad_game", "detail": "game must be an integer id"})
            return
        if game in self.seen or game in self.pending:
            return  # already following it
        if len(self.seen) + len(self.pending) >= self.settings.max_subscriptions:
            self.send(
                {
                    "type": "error",
                    "code": "too_many_subscriptions",
                    "detail": f"at most {self.settings.max_subscriptions} games per connection",
                }
            )
            return
        # Subscribe before reading, so nothing that commits in between is missed;
        # hold its events until the snapshot is sent (see deliver).
        self.pending[game] = None
        self.broker.subscribe(self, ("game", game))
        try:
            row = await self._in_thread(ops.game_get_by_id, game)
        except errors.GameError as e:
            self._drop(game)
            code = "busy" if isinstance(e, errors.DatabaseBusyError) else "bad_game"
            self.send({"type": "error", "code": code, "detail": str(e).splitlines()[0]})
            return
        if game not in self.pending:
            return  # unsubscribed, or removed, while the snapshot was being read
        newest = self.pending.pop(game)
        if row is None:
            self._drop(game)
            self.send({"type": "error", "code": "not_found", "detail": f"no game with id {game}"})
            return
        state = GameState.from_row(row).to_dict()
        if newest is not None and newest["version"] > state["version"]:
            state = newest
        self.seen[game] = state["version"]
        self.send({"type": "subscribed", "game": game, "state": state})

    def _feed_target(self, data: dict):
        """``None`` for ``{"all": true}``, a group id for ``{"group": G}``, or
        ``False`` (after sending an error) for anything else."""
        if data.get("all") is True and "group" not in data:
            return None
        group = data.get("group")
        if _is_id(group) and "all" not in data:
            return group
        self.send({"type": "error", "code": "bad_feed", "detail": 'follow needs "group": an id, or "all": true'})
        return False

    @staticmethod
    def _feed_label(target) -> dict:
        return {"all": True} if target is None else {"group": target}

    async def _follow(self, data: dict) -> None:
        target = self._feed_target(data)
        if target is False:
            return
        assert self.principal is not None
        if target is None:
            allowed = self.principal.is_admin
        else:
            try:
                allowed = await self._in_thread(self.principal.administers, target)
            except errors.GameError:
                self.send({"type": "error", "code": "busy", "detail": "the server is busy; try again shortly"})
                return
        if not allowed:
            who = "an administrator" if target is None else "an administrator of that group"
            self.send({"type": "error", "code": "forbidden", "detail": f"only {who} can follow it"})
            return
        if target not in self.follows:
            self.follows.add(target)
            self.broker.subscribe(self, _ALL if target is None else ("group", target))
        self.send({"type": "following", **self._feed_label(target)})

    def _unfollow(self, target) -> None:
        self.follows.discard(target)
        self.broker.unsubscribe(self, _ALL if target is None else ("group", target))
        if not self.follows:
            self.fed.clear()

    def _drop(self, game: int) -> None:
        self.pending.pop(game, None)
        self.seen.pop(game, None)
        self.broker.unsubscribe(self, ("game", game))


def _is_id(value) -> TypeGuard[int]:
    """A game id: an int (not a bool, which is one) inside the 64-bit range."""
    return type(value) is int and ops._BIGINT_MIN <= value <= ops._BIGINT_MAX


async def websocket_endpoint(websocket: WebSocket) -> None:
    """
    ``/v1/ws``. Deliberately ``async``: it is I/O-bound, and every blocking call it
    makes (token checks, snapshot reads) goes through ``anyio.to_thread`` on the
    broker's own limiter, so a reconnect storm cannot take the REST routes' threads.
    """
    broker: InProcessBroker = websocket.app.state.broker
    settings = broker.settings
    await websocket.accept()

    # Refusals are sent after accepting, so the client sees the close code.
    if not settings.origin_allowed(websocket.headers.get("origin")):
        await _close(websocket, CLOSE_ORIGIN, "origin not allowed")
        return
    conn = Connection(websocket, broker)
    refusal = broker.admit(conn)
    if refusal is not None:
        await _close(websocket, CLOSE_LIMIT, refusal)
        return
    try:
        async with anyio.create_task_group() as tg:
            conn._task_group = tg
            conn._scope = tg.cancel_scope
            tg.start_soon(conn._sender)
            tg.start_soon(conn._auth_deadline)
            await conn._receive_loop()
            tg.cancel_scope.cancel()
    finally:
        broker.unregister(conn)
        if conn.close_code is not None:
            await _close(websocket, conn.close_code, conn.close_reason)


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason[:120])
    except Exception:
        pass  # already closed by the other side
