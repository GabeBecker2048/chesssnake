"""
Live updates for asyncio programs: :class:`AsyncEventStream`, from
:meth:`AsyncApiClient.events() <chesssnake.remote.async_client.AsyncApiClient.events>`.

The asyncio twin of :class:`~chesssnake.remote.realtime.EventStream`: the same
events (the server's ``game``, ``game_started``, ``challenge``, ... and the
stream's own ``disconnected``, ``reconnected``, ``ended`` and ``auth_error``), the
same reconnect rules, but a task on the caller's loop instead of a thread, and
``async for`` instead of a pipe to ``select`` on:

.. code-block:: python

    async with client.events() as stream:
        await stream.follow(all=True)          # administrators: every game
        async for event in stream:
            if event["type"] == "game":
                ...

Iteration ends after ``ended`` or ``auth_error`` (both mean it gave up), or once
:meth:`AsyncEventStream.close` is called. Subscriptions and follows are kept
across reconnects.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from ..db import errors
from .realtime import (
    _PERMANENT,
    _TURNED_OFF,
    BACKOFF_MAX,
    BACKOFF_START,
    OPEN_TIMEOUT_SECONDS,
    RealtimeUnavailable,
    _close_code,
    _describe,
    _feed_message,
    _http_status,
    websocket_url,
)

_CLOSED = object()


class AsyncEventStream:
    """
    A self-reconnecting subscription to an api-endpoint's live updates, on asyncio.

    :param client: A logged-in client (its ``base_url`` and ``token`` are used).
    :param games: Game ids to follow from the start.
    """

    def __init__(self, client, games=(), *, open_timeout: float = OPEN_TIMEOUT_SECONDS):
        if not client.base_url:
            raise RealtimeUnavailable("live updates need a real api-endpoint URL")
        self.url = websocket_url(client.base_url)
        self._token = client.token
        self._open_timeout = open_timeout
        self._wanted: set[int] = {int(g) for g in games}
        #: Feeds followed: group ids, and ``None`` for every game.
        self._follows: set[int | None] = set()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._ws = None
        self._task: asyncio.Task | None = None
        self._closed = False
        self._finished = False

    # --- connecting and closing ---------------------------------------------------

    async def connect(self) -> AsyncEventStream:
        """
        Open the first connection and start reading.

        :raises RealtimeUnavailable: if the server does not offer live updates.
        :raises chesssnake.db.errors.AuthError: if the token is refused.
        """
        if self._task is not None:
            return self
        try:
            self._ws = await self._open()
        except (errors.AuthError, RealtimeUnavailable):
            raise
        except Exception as e:
            raise RealtimeUnavailable(_describe(e)) from e
        self._task = asyncio.create_task(self._run(), name="chesssnake-events")
        return self

    async def close(self) -> None:
        """Stop for good. Safe to call more than once; ends iteration."""
        if self._closed:
            return
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        self._queue.put_nowait(_CLOSED)

    async def __aenter__(self):
        return await self.connect()

    async def __aexit__(self, *_exc):
        await self.close()

    # --- reading ----------------------------------------------------------------------

    def __aiter__(self):
        return self

    async def __anext__(self) -> dict:
        if self._finished:
            raise StopAsyncIteration
        event = await self._queue.get()
        if event is _CLOSED:
            self._finished = True
            raise StopAsyncIteration
        if event.get("type") in ("ended", "auth_error"):
            self._finished = True  # this one is delivered; the next call stops
        return event

    def drain(self) -> list[dict]:
        """Everything queued so far, without waiting."""
        events: list[dict] = []
        while True:
            try:
                event = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return events
            if event is _CLOSED:
                self._queue.put_nowait(_CLOSED)
                return events
            events.append(event)

    # --- what to follow ----------------------------------------------------------------

    async def subscribe(self, game_id: int) -> None:
        """Follow a game. A snapshot arrives as ``subscribed``."""
        self._wanted.add(int(game_id))
        await self._send({"type": "subscribe", "game": int(game_id)})

    async def unsubscribe(self, game_id: int) -> None:
        self._wanted.discard(int(game_id))
        await self._send({"type": "unsubscribe", "game": int(game_id)})

    async def follow(self, group: int | None = None, *, all: bool = False) -> None:
        """
        Follow a feed: every game event in ``group`` (its admins, and administrators),
        or with ``all=True`` in every group (administrators). Answered with
        ``following``, or an ``error`` with code ``forbidden``.
        """
        target = _feed_target(group, all)
        self._follows.add(target)
        await self._send(_feed_message("follow", target))

    async def unfollow(self, group: int | None = None, *, all: bool = False) -> None:
        target = _feed_target(group, all)
        self._follows.discard(target)
        await self._send(_feed_message("unfollow", target))

    # --- internals ----------------------------------------------------------------------

    async def _open(self):
        from websockets.asyncio.client import connect

        ws = await connect(self.url, open_timeout=self._open_timeout, close_timeout=2, max_size=2**20)
        try:
            await ws.send(json.dumps({"type": "auth", "token": self._token}))
            first = json.loads(await asyncio.wait_for(ws.recv(), self._open_timeout))
            if first.get("type") != "ready":
                raise RealtimeUnavailable(f"unexpected first message from the server: {first.get('type')!r}")
            for game_id in sorted(self._wanted):
                await ws.send(json.dumps({"type": "subscribe", "game": game_id}))
            for target in list(self._follows):
                await ws.send(json.dumps(_feed_message("follow", target)))
            return ws
        except BaseException as e:
            code = _close_code(e)
            with contextlib.suppress(Exception):
                await ws.close()
            if code == 4401:
                raise errors.AuthError("the server refused the token for live updates; log in again") from e
            raise

    async def _run(self) -> None:
        while not self._closed:
            code = await self._read(self._ws)
            if self._closed:
                return
            if code == 4401:
                self._emit({"type": "auth_error", "detail": "the token is no longer valid; log in again"})
                return
            if code in _PERMANENT:
                self._emit({"type": "ended", "reason": _PERMANENT[code]})
                return
            self._emit({"type": "disconnected", "code": code})
            self._ws = await self._reconnect()
            if self._ws is None:
                return
            self._emit({"type": "reconnected"})

    async def _read(self, ws) -> int | None:
        try:
            async for raw in ws:
                try:
                    self._emit(json.loads(raw))
                except ValueError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return _close_code(e)
        return getattr(ws, "close_code", None)

    async def _reconnect(self):
        delay = BACKOFF_START
        while not self._closed:
            await asyncio.sleep(delay)
            try:
                return await self._open()
            except errors.AuthError:
                self._emit({"type": "auth_error", "detail": "the token is no longer valid; log in again"})
                return None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if _http_status(e) == _TURNED_OFF:
                    self._emit({"type": "ended", "reason": f"live updates are no longer available ({_describe(e)})"})
                    return None
                delay = min(delay * 2, BACKOFF_MAX)
        return None

    def _emit(self, event: dict) -> None:
        self._queue.put_nowait(event)

    async def _send(self, message: dict) -> None:
        # Best effort: mid-reconnect, the wanted sets are re-sent once it is back.
        ws = self._ws
        if ws is None:
            return
        with contextlib.suppress(Exception):
            await ws.send(json.dumps(message))


def _feed_target(group, all_):
    if all_ == (group is not None):
        raise ValueError("Pass a group id, or all=True")
    return None if all_ else int(group)
