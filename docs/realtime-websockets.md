# Real-time updates (websockets)

Since 0.13.0 an api-endpoint can push changes to clients instead of making them
poll. A client opens one websocket at `/v1/ws`, logs in on it, says which games it
wants to follow, and from then on is told about every move, draw offer and result
in those games the moment it is saved, plus the events that concern its user
(challenges, new games) without asking.

It is **off by default**. With it off nothing changes: the route does not exist,
REST clients (a Discord bot, a script) work exactly as before, and clients that
want live updates fall back to polling. Everything a websocket tells you can also
be read over REST; the socket only saves you from asking.

- [Turning it on](#turning-it-on)
- [The connection](#the-connection)
- [Messages you send](#messages-you-send)
- [Messages you receive](#messages-you-receive)
- [Ordering and consistency](#ordering-and-consistency)
- [Close codes and reconnecting](#close-codes-and-reconnecting)
- [Limits](#limits)
- [Examples](#examples)
- [Running it](#running-it)

---

## Turning it on

```toml
[websocket]
enabled = true
```

or `CHESSSNAKE__WEBSOCKET__ENABLED=1`. Every other key in `[websocket]` has a
working default; see [configuration](configuration.md#websocket). The socket is
served on the same host and port as the REST API, so there is nothing new to
publish.

With it off, a websocket upgrade to `/v1/ws` is answered with **HTTP 403**. That
is the one answer that means "not available here; poll instead". A browser cannot
see that status (it only reports a failed connection), so `GET /v1/info`, which
needs no token, also says whether the socket is served: `"websocket": true`.

The [web UI](web-ui.md) is a complete browser client of this protocol, in
`src/chesssnake/data/web/js/live.js`.

---

## The connection

```
ws://host:8000/v1/ws        (wss:// behind TLS)
```

One connection per client is enough: it carries any number of games. Every
message, in both directions, is a **JSON text frame** holding an object with a
`"type"`.

1. Open the socket. No header, cookie or query parameter is needed.
2. Send `{"type": "auth", "token": "css_..."}` as the **first message**, within
   `auth_timeout_seconds` (10 s). The token is any login or api token, the same
   one you send as `Authorization: Bearer` over REST.
3. Receive `ready`. You are now following your own user's events.
4. Send `subscribe` for each game you want to follow. Each answers with a
   snapshot of the game.

The token goes in a message rather than the URL because browsers cannot set an
`Authorization` header on a websocket, and a token in a URL ends up in proxy
access logs.

A logged-in user may follow **any** game, as any user may read any game over
REST. Spectating is the same as playing, minus the moves.

The server checks the token again every `reauth_interval_seconds` (60 s).
Logging out, revoking the token, a password reset and disabling the user close
the affected sockets **at once** (`4401`).

---

## Messages you send

| Message | Meaning |
|---|---|
| `{"type": "auth", "token": "css_..."}` | Log in. First message, and only then. |
| `{"type": "subscribe", "game": 41}` | Follow a game. Answered with `subscribed` (or an `error`). Subscribing twice is one subscription. |
| `{"type": "unsubscribe", "game": 41}` | Stop following it. No answer. |
| `{"type": "ping"}` | Answered with `pong`. For clients that cannot see protocol-level pings (browsers); the server already pings every socket to keep it alive. |

Moves, draws, resignations and everything else stay on REST: the socket only
reports changes. Any other `type` closes the socket with `4400`.

---

## Messages you receive

### `ready`

```json
{
  "type": "ready",
  "user": {"id": 2, "username": "bob", "role": "user", "...": "..."},
  "limits": {"max_subscriptions": 64, "max_message_bytes": 65536}
}
```

`user` is the same [User](rest-api.md#user) as `GET /v1/auth/me`.

### `subscribed`

```json
{"type": "subscribed", "game": 41, "state": GameState}
```

The game's current [GameState](rest-api.md#gamestate), sent once per `subscribe`.
A finished game can be followed too; it just never changes.

### `game`

```json
{
  "type": "game",
  "state": GameState,
  "move": {"san": "Nf6", "from": "g8", "to": "f6", "check": false},
  "legal_moves": [{"from": "e2", "to": "e4", "san": "e4", "promotion": null}, ...]
}
```

A followed game changed. `state` is the **whole** new state, so no follow-up read
is needed. `move` is the move that caused it, or `null` for a draw offer, accept
or decline, or a resignation. The game is over when `state.status` is not `0`,
with `state.termination` saying why.

`legal_moves` (since 0.15.1) comes with a move: the legal moves of the side now to
move, in the shape of `GET /v1/games/{id}/legal-moves`, or `[]` once the game has
ended. A player whose turn it now is can offer them straight away instead of asking.
It is absent when `move` is `null` (the position did not change) and from older
servers, so treat it as optional and fall back to the `legal-moves` route.

### `game_removed`

```json
{"type": "game_removed", "game": 41}
```

An administrator deleted a followed game. You are unsubscribed from it.

### `game_started`

```json
{"type": "game_started", "state": GameState}
```

A game **you play in** began: a challenge was accepted (by either side), or an
administrator created it. Sent to both players without subscribing, which is how a
client learns the id of a rematch it did not start. Subscribe to it to follow it.

### `challenge`

```json
{"type": "challenge", "event": "created", "challenge": Challenge}
```

A [Challenge](rest-api.md#challenge) to or from you was `created`, or `removed`
(accepted, declined or withdrawn). Sent to both parties. An accepted challenge
is followed by `game_started`.

### `error`

```json
{"type": "error", "code": "not_found", "detail": "no game with id 999"}
```

Something you asked for could not be done; the socket stays open.

| `code` | Meaning |
|---|---|
| `bad_game` | `game` is not an integer id (a string, a boolean, out of range). |
| `not_found` | There is no game with that id. |
| `too_many_subscriptions` | This socket already follows `max_subscriptions` games. |
| `busy` | The database was busy; try the `subscribe` again shortly. |

### `pong`

`{"type": "pong"}`, the answer to `ping`.

---

## Ordering and consistency

- **Versions only go up.** For each game, the server never sends a `game` or
  `subscribed` state older than one it has already sent on that connection. A
  move saved while your `subscribe` was being answered is not lost and not sent
  out of order: the snapshot you get is the newer of the two.
- **Events are sent after the change is saved.** A `game` event never describes a
  move that could still fail.
- **There is no replay.** Messages sent while you were disconnected are gone.
  After reconnecting, subscribe again: the `subscribed` snapshots are the current
  truth. Re-read `GET /v1/challenges` if you show challenges.
- Treat a `state` whose `version` is not newer than the one you show as a no-op.
  The server already guarantees it, but it costs one comparison and makes a
  client robust to its own bugs.
- Your own actions come back as events too (you are subscribed to the game). The
  REST response and the event carry the same state; whichever arrives second is
  the no-op above.

---

## Close codes and reconnecting

Every refusal is sent **after** the upgrade is accepted, so a client always sees
the code. (Websockets turned off is the exception: there is no socket to close, so
it is an HTTP 403.)

| Code | Meaning | Reconnect? |
|---|---|---|
| `1000` | Normal close (you closed it). | No. |
| `1001`, `1006`, `1011` | Going away, connection lost, server error. | Yes, with backoff. |
| `1012` | The server is restarting (sent to every socket on shutdown). | Yes, with backoff. |
| `1009` | A message over `max_message_bytes`. | Fix the client. |
| `1013` | The server could not send to you fast enough (your queue filled). | Yes. |
| `4400` | A malformed message: not JSON, not an object, no `type`, an unknown `type`, a binary frame. | Fix the client. |
| `4401` | No valid token: a bad `auth`, a message before `auth`, or the token was revoked, expired, or its user disabled. | Log in again, then reconnect. |
| `4403` | The browser's `Origin` is not in `allowed_origins`. | No. |
| `4408` | No `auth` message within `auth_timeout_seconds`. | Yes, and send `auth` first. |
| `4429` | A connection limit: too many sockets in total, waiting to log in, or for this user. | Later, with backoff. |

A reasonable client reconnects after anything but `1000`, `1009`, `4400`, `4401`
and `4403`, waiting 1 s and doubling to a cap of 30 s, and re-subscribes to its
games once `ready` arrives. If the reconnect is refused with HTTP 403, websockets
have been turned off since: poll instead.

---

## Limits

All in `[websocket]`; see [configuration](configuration.md#websocket).

| Key | Default | What it bounds |
|---|---|---|
| `max_connections` | 1000 | Open sockets in total, counted from accept (before `auth`). |
| `max_pending_auth` | 100 | Of those, sockets that have not logged in yet. |
| `max_connections_per_user` | 10 | Sockets per user. |
| `max_subscriptions` | 64 | Games one socket follows. |
| `max_message_bytes` | 65536 | Largest message a client may send. |
| `send_queue_size` | 256 | Messages waiting to go out on one socket; overflow closes it with `1013`. |
| `ping_interval_seconds` / `ping_timeout_seconds` | 20 / 20 | Protocol pings. A peer that stops answering is closed after about 40 s. |

A client that stops reading is detected by the ping timeout, not by the send
queue: the server's websocket layer does not push back on writes, so the queue
only fills if the server itself falls behind.

Memory, measured on 0.13.0 with 500 authenticated idle sockets: about 56 KiB
each, so 1000 sockets cost roughly 55 MiB. Compression (`compression = true`) adds
tens of kilobytes per socket and saves little on messages this small, which is
why it is off.

---

## Examples

### Browser

```js
const ws = new WebSocket("wss://chess.example/v1/ws");
const shown = new Map(); // game id -> version on screen

ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data);
  switch (msg.type) {
    case "ready":
      ws.send(JSON.stringify({ type: "subscribe", game: 41 }));
      break;
    case "subscribed":
    case "game": {
      const { id, version } = msg.state;
      if (version <= (shown.get(id) ?? -1)) break;
      shown.set(id, version);
      render(msg.state, msg.move);
      break;
    }
    case "game_started":
      announceNewGame(msg.state);
      break;
    case "challenge":
      refreshChallenges();
      break;
  }
};
ws.onclose = ({ code }) => {
  if (code === 4401) return logIn();
  if (![1000, 1009, 4400, 4403].includes(code)) scheduleReconnect();
};
```

Serve the frontend from a known address and list it in `allowed_origins`, so
another site cannot open sockets with a visitor's token. (The token still has to
be supplied by that site's script, so this is defence in depth, not the gate.)

### Python

The `client` extra includes a stream that does the reconnecting for you. It is
what `chesssnake play` uses:

```python
import select
from chesssnake import connect

client = connect("https://chess.example")       # a stored `chesssnake login`
with client.events(games=[41]) as stream:       # RealtimeUnavailable if it is off
    while True:
        select.select([stream.fileno()], [], [])
        for event in stream.drain():
            if event["type"] == "game":
                print(event["move"] and event["move"]["san"], event["state"]["fen"])
```

`stream.fileno()` becomes readable whenever events are waiting, so it can sit in
a `select` next to anything else; a background thread does the reading. Besides
the server's messages, the stream emits `disconnected` (it is reconnecting),
`reconnected` (back, with fresh `subscribed` snapshots to follow), `ended` (it
gave up: websockets were turned off, or the origin was refused) and `auth_error`.

---

## Running it

- **Reverse proxies** must pass the websocket upgrade through. Caddy's
  `reverse_proxy` does with no extra configuration. nginx needs
  `proxy_http_version 1.1`, `proxy_set_header Upgrade $http_upgrade` and
  `proxy_set_header Connection "upgrade"`, and a `proxy_read_timeout` longer than
  `ping_interval_seconds`.
- **Shutdown**: the server closes every socket with `1012` and exits within
  `shutdown_timeout_seconds` (5 s). Measured with 500 sockets open: 0.14 s.
- **One process.** Updates are delivered within the api-endpoint process that
  saved the change. With several uvicorn workers, or several replicas behind a
  load balancer, a socket only hears about changes made through its own process.
  Run one process (the shipped container does), or put a shared broker behind the
  server's `Broker` interface; a PostgreSQL `LISTEN`/`NOTIFY` broker is the
  intended next step and is not built.
- Blocking work for sockets (checking tokens, reading snapshots) runs on its own
  `worker_threads` (4), apart from the REST routes' threads, so a burst of
  reconnects does not slow ordinary requests.
