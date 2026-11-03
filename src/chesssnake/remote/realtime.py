"""
Live updates from an api-endpoint's websocket (``/v1/ws``), for Python clients.

:class:`EventStream` connects, authenticates with the client's token, follows the
games it is asked to, and keeps going across dropped connections. It is built for
programs that already have a loop of their own, such as ``chesssnake play``:

- a background thread reads the socket and only *queues* what arrives, so the
  caller's thread stays the one that touches its game and its output;
- :meth:`EventStream.fileno` is a pipe that becomes readable whenever something
  is queued, so the caller can ``select`` on it alongside stdin, and
  :meth:`EventStream.drain` returns everything queued so far.

Besides the server's messages (``game``, ``game_started``, ``challenge``, ...,
see ``docs/realtime-websockets.md``), the stream adds its own:

- ``{"type": "disconnected", "code": ...}``: the connection dropped; it is
  reconnecting (doubling the wait from 1 s to 30 s);
- ``{"type": "reconnected"}``: back, every game re-subscribed (fresh snapshots
  follow as ``subscribed`` messages, so the caller can re-sync);
- ``{"type": "ended", "reason": ...}``: it gave up for good (websockets were turned
  off, the server refused the origin, or :meth:`close`);
- ``{"type": "auth_error", "detail": ...}``: the token was revoked or expired.

Needs the ``websockets`` package (in the ``client`` extra), imported only when a
stream is made, so local games and polling clients never need it.
"""

from __future__ import annotations

import json
import os
import queue
import threading
from urllib.parse import urlsplit, urlunsplit

from ..db import errors

#: How long the first connection attempt may take before live updates are
#: declared unavailable and the caller falls back to polling.
OPEN_TIMEOUT_SECONDS = 5.0
BACKOFF_START, BACKOFF_MAX = 1.0, 30.0

#: Close codes after which reconnecting would only be refused again.
_PERMANENT = {4400: "the server rejected a message", 4403: "this origin is not allowed"}


class RealtimeUnavailable(Exception):
    """The server does not offer live updates (or they could not be reached); poll instead."""


def websocket_url(api_url: str) -> str:
    """``https://chess.example`` -> ``wss://chess.example/v1/ws`` (a path prefix is kept)."""
    parts = urlsplit(api_url)
    scheme = {"https": "wss", "http": "ws"}.get(parts.scheme.lower(), parts.scheme)
    return urlunsplit((scheme, parts.netloc, parts.path.rstrip("/") + "/v1/ws", "", ""))


class EventStream:
    """
    A self-reconnecting subscription to an api-endpoint's live updates.

    :param client: a logged-in :class:`~chesssnake.remote.client.ApiClient` (its
        ``base_url`` and ``token`` are used; its session is not).
    :param games: game ids to follow from the start.
    :raises RealtimeUnavailable: if the first connection fails for any reason but
        a bad token: websockets switched off (the upgrade answers 403), a proxy that
        does not pass them on, TLS, a timeout, or the ``websockets`` package missing.
    :raises chesssnake.db.errors.AuthError: if the token is refused.
    """

    def __init__(self, client, games=(), *, open_timeout: float = OPEN_TIMEOUT_SECONDS):
        try:
            from websockets.sync.client import connect  # noqa: F401
        except ImportError as e:
            raise RealtimeUnavailable(
                "live updates need the websockets package: pip install 'chesssnake[client]'"
            ) from e
        if not client.base_url:
            raise RealtimeUnavailable("live updates need a real api-endpoint URL")
        self.url = websocket_url(client.base_url)
        self._token = client.token
        self._open_timeout = open_timeout
        self._wanted: set[int] = {int(g) for g in games}
        self._lock = threading.Lock()
        self._queue: queue.Queue[dict] = queue.Queue()
        self._read_fd, self._write_fd = os.pipe()
        os.set_blocking(self._read_fd, False)
        os.set_blocking(self._write_fd, False)
        self._closed = threading.Event()
        self._ws = self._first_connection()
        self._thread = threading.Thread(target=self._run, name="chesssnake-events", daemon=True)
        self._thread.start()

    # --- for the caller ----------------------------------------------------------

    def fileno(self) -> int:
        """Readable whenever events are waiting; ``select`` on it."""
        return self._read_fd

    def drain(self) -> list[dict]:
        """Everything queued so far, oldest first. Never blocks."""
        # Empty the pipe *before* the queue: an event queued after this read
        # writes a fresh byte, so the next select wakes for it.
        try:
            while os.read(self._read_fd, 4096):
                pass
        except (BlockingIOError, OSError):
            pass
        events = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                return events

    def subscribe(self, game_id: int) -> None:
        """Follow a game. Kept across reconnects; a snapshot arrives as ``subscribed``."""
        with self._lock:
            self._wanted.add(int(game_id))
        self._send({"type": "subscribe", "game": int(game_id)})

    def unsubscribe(self, game_id: int) -> None:
        with self._lock:
            self._wanted.discard(int(game_id))
        self._send({"type": "unsubscribe", "game": int(game_id)})

    def close(self) -> None:
        """Stop for good. Safe to call more than once."""
        if self._closed.is_set():
            return
        self._closed.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._thread.join(timeout=2)
        for fd in (self._read_fd, self._write_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    # --- connecting ------------------------------------------------------------------

    def _open(self):
        """Connect, authenticate and subscribe. Raises on any failure."""
        from websockets.sync.client import connect

        ws = connect(self.url, open_timeout=self._open_timeout, close_timeout=2, max_size=2**20)
        try:
            ws.send(json.dumps({"type": "auth", "token": self._token}))
            first = json.loads(ws.recv(timeout=self._open_timeout))
            if first.get("type") != "ready":
                raise RealtimeUnavailable(f"unexpected first message from the server: {first.get('type')!r}")
            with self._lock:
                wanted = sorted(self._wanted)
            for game_id in wanted:
                ws.send(json.dumps({"type": "subscribe", "game": game_id}))
            return ws
        except BaseException as e:
            code = _close_code(e)
            try:
                ws.close()
            except Exception:
                pass
            if code == 4401:
                raise errors.AuthError("the server refused the token for live updates; log in again") from e
            raise

    def _first_connection(self):
        try:
            return self._open()
        except errors.AuthError:
            self._close_fds()
            raise
        except RealtimeUnavailable:
            self._close_fds()
            raise
        except Exception as e:
            self._close_fds()
            raise RealtimeUnavailable(_describe(e)) from e

    def _close_fds(self):
        for fd in (self._read_fd, self._write_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    # --- the reader thread ---------------------------------------------------------------

    def _run(self) -> None:
        while not self._closed.is_set():
            code = self._read(self._ws)
            if self._closed.is_set():
                break
            if code == 4401:
                self._emit({"type": "auth_error", "detail": "the token is no longer valid; log in again"})
                return
            if code in _PERMANENT:
                self._emit({"type": "ended", "reason": _PERMANENT[code]})
                return
            self._emit({"type": "disconnected", "code": code})
            self._ws = self._reconnect()
            if self._ws is None:
                return
            self._emit({"type": "reconnected"})

    def _read(self, ws) -> int | None:
        """Queue messages until the connection ends; return its close code."""
        try:
            for raw in ws:
                try:
                    self._emit(json.loads(raw))
                except ValueError:
                    continue
        except Exception as e:
            return _close_code(e)
        return _close_code_of(ws)

    def _reconnect(self):
        delay = BACKOFF_START
        while not self._closed.wait(delay):
            try:
                return self._open()
            except errors.AuthError:
                self._emit({"type": "auth_error", "detail": "the token is no longer valid; log in again"})
                return None
            except Exception as e:
                if _http_status(e) is not None:
                    # The server answers but will not upgrade: websockets were
                    # switched off, or a proxy no longer passes them on.
                    self._emit({"type": "ended", "reason": f"live updates are no longer available ({_describe(e)})"})
                    return None
                delay = min(delay * 2, BACKOFF_MAX)
        return None

    def _emit(self, event: dict) -> None:
        self._queue.put(event)
        try:
            os.write(self._write_fd, b"!")
        except (BlockingIOError, OSError):
            pass  # the pipe is full of wakeups already, or closed

    def _send(self, message: dict) -> None:
        # Best effort: if the connection is mid-reconnect, the wanted set is
        # re-sent once it is back.
        ws = self._ws
        if ws is None:
            return
        try:
            ws.send(json.dumps(message))
        except Exception:
            pass


def _close_code(exc) -> int | None:
    received = getattr(exc, "rcvd", None)
    return getattr(received, "code", None)


def _close_code_of(ws) -> int | None:
    return getattr(ws, "close_code", None)


def _http_status(exc) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _describe(exc) -> str:
    status = _http_status(exc)
    if status == 403:
        return "the server has websockets turned off"
    if status is not None:
        return f"the server answered HTTP {status} instead of upgrading (a proxy may not pass websockets on)"
    if isinstance(exc, TimeoutError):
        return "connecting timed out"
    return f"{type(exc).__name__}: {exc}"
