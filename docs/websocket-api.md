---
title: Websocket API
---

A client can open one websocket and be told about every move the moment it is
made, instead of asking over and over. The socket only reports changes: moves
and everything else are still sent over the [REST API](rest-api.html).

[Live updates](live-updates.html) are on by default, but a server can turn
them off. `GET /v1/info` says whether they are on (`"websocket": true`); when
they are not, connecting is refused with HTTP 403, and your client should poll
instead.

Using Python? The [Python client](python-client.html#waiting-for-the-opponent)
does all of this for you.

## Connecting

```
wss://chess.example/v1/ws        (ws:// without HTTPS)
```

Every message, both ways, is JSON with a `"type"`.

1. Open the socket.
2. Send `{"type": "auth", "token": "css_..."}` first, within 10 seconds. It is
   the same token you use for REST.
3. Receive `ready`. From now on you are told about your own challenges and new
   games.
4. Send `subscribe` for each game you want to follow. Any logged-in user may
   follow any game.

One socket can follow many games. An administrator can instead `follow` every
game on the server, and a [group admin](accounts.html#group-admins) every game
of their group: see [Following a feed](#following-a-feed).

## Messages you send

| Message | Meaning |
|---|---|
| `{"type": "auth", "token": "css_..."}` | Log in. The first message, and only then. |
| `{"type": "subscribe", "game": 41}` | Follow a game. Answered with `subscribed`. |
| `{"type": "unsubscribe", "game": 41}` | Stop following it. |
| `{"type": "follow", "all": true}` | Administrators: hear about every game. Answered with `following`. |
| `{"type": "follow", "group": 7}` | Administrators and that group's admins: every game of group 7. |
| `{"type": "unfollow", "all": true}` or `{"type": "unfollow", "group": 7}` | Stop. Answered with `unfollowed`. |
| `{"type": "ping"}` | Answered with `{"type": "pong"}`. |

## Messages you receive

`GameState`, `User` and `Challenge` are the same objects as in the
[REST API](rest-api.html#data).

### ready

```json
{
  "type": "ready",
  "user": { },
  "limits": {"max_subscriptions": 64, "max_message_bytes": 65536}
}
```

You are logged in. `user` is your `User`.

### subscribed

```json
{"type": "subscribed", "game": 41, "state": { }}
```

The game as it is now, once per `subscribe`. `state` is a `GameState`.

### game

```json
{
  "type": "game",
  "state": { },
  "move": {"san": "Nf6", "from": "g8", "to": "f6", "check": false},
  "legal_moves": [{"from": "e2", "to": "e4", "san": "e4", "promotion": null}]
}
```

A game you follow changed. `state` is the whole new `GameState`, so there is
nothing more to fetch.

- `move` is the move that was played, or `null` when the change was a draw
  offer, a draw answer or a resignation.
- `legal_moves` comes with a move: what the side now to move can play. Treat
  it as optional.
- `actor_id` is the player the change was made as, and `requested_by` the user
  whose token sent it. They differ when a bot or an administrator acts for a
  player: a bot can skip its own changes by comparing `requested_by` with its
  own id.
- The game is over when `state.status` is not `0`. `state.last_move` is the last
  move played, also on draw and resignation events.

Your own moves come back as events too.

### game_started

```json
{"type": "game_started", "state": { }}
```

A game **you play in** began: a challenge was accepted, or an administrator
made the game. Sent without subscribing. Subscribe to it to follow it.
`actor_id` (the player who accepted, or `null` for a game an administrator
made) and `requested_by` say who started it, as for `game`.

### challenge

```json
{"type": "challenge", "event": "created", "challenge": { }}
```

A challenge to or from you (or in a group you follow) was `created` or
`removed` (accepted, declined or withdrawn).

### game_removed

```json
{"type": "game_removed", "game": 41}
```

An administrator deleted a game you follow.

### error

```json
{"type": "error", "code": "not_found", "detail": "no game with id 999"}
```

A `subscribe` or `follow` could not be done. The socket stays open.

| `code` | Meaning |
|---|---|
| `bad_game` | `game` is not a game id. |
| `not_found` | There is no game with that id. |
| `too_many_subscriptions` | This socket follows as many games as it may. |
| `bad_feed` | `follow` needs `"group": id` or `"all": true`. |
| `forbidden` | Only administrators, or that group's admins, may follow it. |
| `busy` | The server was busy: try again shortly. |

## Following a feed

A bot that plays for many people, or a moderator, wants every game rather than
a list of ids. After `{"type": "follow", "all": true}` (or `"group": 7`) the
socket receives, for every game in scope, the same `game`, `game_started`,
`game_removed` and `challenge` messages a player would, new games included, with
nothing to subscribe to:

```json
{"type": "following", "all": true}
```

Each event arrives once, even when a game is also subscribed to. A feed is not
a subscription: it does not count against `max_subscriptions`, sends no
snapshot, and `subscribe` still works for a game's current state. Administrators
following everything also receive:

```json
{"type": "identity_linked", "user_id": 12, "provider": "discord", "external_id": "1844...", "previous_user_id": 9}
```

when an outside id is linked to a user (by an administrator or a
[link code](accounts.html#link-codes)); `previous_user_id` is who had it before,
or `null`.

A group admin who loses the role is told at the next token check (at once if
the change was made through the API), with
`{"type": "unfollowed", "group": 7, "reason": "..."}`, and hears no more.

## What you can rely on

- An event is sent only after the change is saved.
- For each game, states arrive in order. Ignore any `state` whose `version` is
  not newer than the one you show.
- Nothing is replayed. After reconnecting, subscribe again: the `subscribed`
  answers are the current truth.

## When the socket closes

| Code | Meaning | Reconnect? |
|---|---|---|
| `1000` | You closed it. | no |
| `1001`, `1006`, `1011`, `1012`, `1013` | The connection was lost, or the server is restarting or overloaded. | yes |
| `1009` | You sent a message that was too large. | fix the client |
| `4400` | You sent something malformed, or an unknown `type`. | fix the client |
| `4401` | No valid token: it was wrong, missing, expired or revoked. | log in again first |
| `4403` | This web page's address is not allowed to connect. See [Live updates](live-updates.html#things-to-know). | no |
| `4408` | No `auth` message in time. | yes |
| `4429` | Too many connections, in total or for this user. | later |

When reconnecting, wait 1 second, then double the wait each time up to 30
seconds. If the reconnect is refused with HTTP 403, live updates have been
turned off: poll instead.

## Example

```js
const ws = new WebSocket("wss://chess.example/v1/ws");
const shown = new Map();            // game id -> version on screen

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
