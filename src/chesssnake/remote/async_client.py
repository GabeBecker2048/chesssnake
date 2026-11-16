"""
:class:`AsyncApiClient`: the same routes as :class:`~chesssnake.remote.client.ApiClient`,
awaitable, on ``httpx``. For asyncio programs (Discord, Slack and Telegram bots,
web servers), which must not block their event loop on HTTP.

.. code-block:: python

    client = chesssnake.connect("https://chess.example", token="css_...", asynchronous=True)
    async with client:
        game = await client.get_game(41)
        result = await client.move(game, "e4", player_id=7)

Every route method of ``ApiClient`` is here with the same name and arguments,
because both inherit them from one definition (see
:mod:`chesssnake.remote.client`); here each returns a coroutine. Live updates are
:meth:`AsyncApiClient.events`, an :class:`~chesssnake.remote.async_realtime.AsyncEventStream`
to ``async for`` over.

Needs ``httpx`` (in the ``client`` extra), imported when a client is made.
"""

from __future__ import annotations

import inspect

from .client import API_PREFIX, _Call, _id, _Routes, raise_for_response


class AsyncApiClient(_Routes):
    """
    Talks to a chesssnake api-endpoint over REST, as one user, without blocking.

    :param base_url: The endpoint, e.g. ``https://chess.example``.
    :param token: A bearer token; set later by :meth:`login`.
    :param http: An ``httpx.AsyncClient`` to send with (default: a new one, closed
        by :meth:`aclose`). Tests pass one over ``httpx.ASGITransport(app)``.
    :param timeout: Seconds per request, for the default ``http`` client.
    """

    def __init__(self, base_url, token=None, *, http=None, timeout=30.0):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.token = token
        if http is None:
            try:
                import httpx
            except ImportError as e:  # pragma: no cover - exercised via install extras
                raise ImportError(
                    "The 'httpx' package is required for the async client. "
                    "Install it with: pip install chesssnake[client]"
                ) from e
            http = httpx.AsyncClient(timeout=timeout)
            self._owns_http = True
        else:
            self._owns_http = False
        self._http = http

    async def aclose(self) -> None:
        """Close the HTTP connections (only those this client opened itself)."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        await self.aclose()

    # --- transport ---------------------------------------------------------

    def _headers(self, anonymous=False):
        return {"Authorization": f"Bearer {self.token}"} if self.token and not anonymous else None

    async def _run(self, call: _Call):
        resp = await self._http.request(
            call.method,
            f"{self.base_url}{API_PREFIX}{call.path}",
            params=call.params,
            json=call.json,
            headers=self._headers(call.anonymous),
        )
        if resp.status_code >= 400:
            raise_for_response(resp)
        return call.result(resp)

    async def _then(self, value, fn):
        result = fn(await value)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _done(self, value):
        return value

    # --- live updates --------------------------------------------------------

    def events(self, games=()):
        """
        Live updates over the server's websocket, as an
        :class:`~chesssnake.remote.async_realtime.AsyncEventStream`. Connect it with
        ``async with`` (or ``await stream.connect()``), then ``async for event in stream``.

        :raises chesssnake.remote.realtime.RealtimeUnavailable: when connecting, if
            the server does not offer them; poll instead.
        """
        from .async_realtime import AsyncEventStream

        return AsyncEventStream(self, games=[_id(g) for g in games])
