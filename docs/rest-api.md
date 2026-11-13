# chesssnake REST API reference

The `chesssnake api-endpoint` is a **server-authoritative** chess service. Clients
do **not** implement chess: they send a move (or a draw action), and the server
runs the engine, validates the action against the stored game, applies it,
persists the result, and returns the new state, or a structured error describing
exactly what went wrong. Any HTTP client, in any language, can play a full game
without a chess engine of its own.

This document describes every route, who may call it, the JSON that goes in and
out, every response you can get, and how a client is expected to interpret them.

- [Overview](#overview)
- [Authentication](#authentication)
- [Who may do what](#who-may-do-what)
- [Data models](#data-models)
- [Error handling](#error-handling)
- [Acting in a game](#acting-in-a-game)
- [Endpoints](#endpoints)
  - [Health](#get-health)
  - [Server information](#get-v1info)
  - [Accounts and tokens](#accounts-and-tokens)
  - [Users](#users)
  - [Challenges](#challenges)
  - [Games](#games)
- [Real-time updates (websockets)](#real-time-updates-websockets)
- [The Python client](#the-python-client)
- [Building your own client](#building-your-own-client)

---

## Overview

- **Base URL**: whatever host and port the server is bound to, e.g. `http://localhost:8000`.
- **Versioning**: every route except `/health` is under `/v1`. Incompatible
  changes would go under a new prefix (`/v2`) after 1.0; before 1.0 a minor
  version may change `/v1` (see the changelog).
- **Content type**: request and response bodies are JSON, except the PGN and FEN
  exports (`text/plain`) and the board image (`image/png`).
- **Everything needs a login** except `/health`, `POST /v1/auth/login` and
  `POST /v1/auth/register`. See [Authentication](#authentication).
- **Users**: every player is an account with a server-assigned id and a username.
  Boards and PGN show the username. An integration with ids of its own (a Discord
  bot, say) maps them onto users through [external ids](#users) rather than
  choosing user ids.
- **Games** are addressed by their **id**, which never changes and is kept when
  the game finishes. A game is normally created by one user
  [challenging](#challenges) another and the challenge being accepted;
  administrators can also create games directly. `group_id` is a namespace of your
  choosing (a Discord server, a tournament, `0` for none): the same two players
  can have one game in progress per group.
- **The server is the authority on the rules.** It decides whether a move is
  legal, whose turn it is, and when the game is over. Clients render and collect
  input; they never decide legality.

### The game lifecycle at a glance

1. `POST /v1/auth/login` with a username and password → a token. Send it as
   `Authorization: Bearer <token>` from then on.
2. `POST /v1/challenges {"opponent_id": …}`; the opponent sees it in
   `GET /v1/challenges?direction=incoming` and accepts with
   `POST /v1/challenges/{id}/accept`, which creates the game and returns it.
3. `POST /v1/games/{id}/moves {"move": "e4"}` on your turn → a `MoveResult`.
4. `GET /v1/games/{id}` to see the opponent's moves (compare `version`).
5. When it is over, challenge again for a rematch; the finished game stays
   readable at the same id.

---

## Authentication

Tokens are opaque bearer tokens: `css_` followed by 43 random characters. Send
one on every request:

```
Authorization: Bearer css_9fJ…
```

There are two kinds, held in the same way:

- **Session tokens** come from logging in (`POST /v1/auth/login`) or registering.
  They expire after `api.session_lifetime_days` (30 by default); log in again then.
  A user keeps at most 20; older ones are revoked as new ones are made.
- **Api tokens** are named and made by a user for a script or a bot
  (`POST /v1/auth/tokens`, which asks for the password again). Their expiry is
  chosen when they are made, or never.

The server stores only a SHA-256 of each token, so a token is shown exactly once:
in the response that created it. Revoking one (logging out, an administrator
resetting a password or disabling the account) takes effect on the very next
request.

What revokes what:

| Event | Session tokens | Api tokens |
|---|---|---|
| `POST /v1/auth/logout` | the one presented | the one presented |
| The user changes their own password | all **but** the one presented | kept |
| An administrator resets the password | all | all |
| An administrator disables the account | all | all |

Changing your own password keeps your api tokens on purpose: they are separate
credentials, and a bot should not stop because its owner changed a password.

**Accounts.** `api.registration` decides who can make one: `"closed"` (the
default) means only administrators, through `POST /v1/users` or
`chesssnake user create` on the server's machine; `"open"` lets anyone call
`POST /v1/auth/register`. The first administrator is always made on the server:
`chesssnake user create NAME --admin`.

**Passwords** are 8 to 256 characters, sent in plain text over TLS and stored as
Argon2id hashes. A failed login always answers `401 invalid username or password`,
whether the username exists, the password is wrong, or the account has no
password, and takes the same time in each case. A disabled account is only
reported (`403`) once the password was right.

A request without a valid token gets `401` with `{"error_type": "AuthError", ...}`
and `WWW-Authenticate: Bearer`. A response that says the token is invalid means
log in again; a `503` means the server was busy and the token is fine.

---

## Who may do what

Two roles: **user** and **admin**.

| | anonymous | user | admin |
|---|---|---|---|
| `GET /health`, `GET /v1/info`, log in | yes | yes | yes |
| register | only if `registration = "open"` | n/a | n/a |
| read users, games, records, PGN, images | no | yes, any | yes |
| move, offer or answer a draw, resign | no | as themselves, in their own games | as any player |
| challenge, accept, decline, withdraw | no | as themselves | on anyone's behalf |
| create or delete games directly | no | no | yes |
| create users, change roles, disable, reset passwords | no | no | yes |
| link external ids | no | no | yes |
| rename themselves, change their own password, manage their own tokens | no | yes | any account |

Linked external ids appear in a `User` only for that user and for administrators.
Someone else's challenge or token answers `404`, not `403`, so ids of other
people's things are not confirmed.

The last enabled administrator cannot be demoted or disabled.

---

## Data models

### `GameState`

The state of a game, in progress or finished. Returned by game creation, reads,
and every action, and nested inside a `MoveResult`.

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | The game's id. Never reused, and kept when the game finishes. |
| `fen` | string | The full position as standard [FEN](#fen). |
| `status` | integer | `0` in play, `1` white won, `2` black won, `3` draw. |
| `version` | integer | Bumped on every change, for [optimistic concurrency](#optimistic-concurrency-expected_version). |
| `generation` | integer | Which game this is between these two colours in this group: `1`, then `2` for a rematch with the same colours, and so on. |
| `draw` | integer \| null | Who has an open draw offer: `0` white, `1` black, `null` none. |
| `termination` | string \| null | Why a finished game ended ([result model](#result-model)); `null` in play. |
| `group_id`, `white_id`, `black_id` | integer | The group and the two players. |
| `white_name`, `black_name` | string | The players' current usernames. |
| `started_at` | string | When the game began (ISO 8601, UTC). |
| `updated_at` | string | When it last changed; for a finished game, when it ended. |

```json
{
  "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
  "status": 0,
  "version": 2,
  "generation": 1,
  "draw": null,
  "termination": null,
  "id": 41,
  "group_id": 0,
  "white_id": 1,
  "black_id": 2,
  "white_name": "alice",
  "black_name": "bob",
  "started_at": "2026-11-03T16:00:49.852248+00:00",
  "updated_at": "2026-11-03T16:01:02.117730+00:00"
}
```

Whose turn it is comes from the FEN (the field after the placement: `w` or `b`).
New fields may be added to any response, so a client should ignore keys it does
not recognize.

### `MoveResult`

What playing a move returns: the move plus the resulting `GameState`.

| Field | Type | Meaning |
|---|---|---|
| `state` | `GameState` | The full state **after** the move. |
| `from`, `to` | string | Origin and destination squares, e.g. `"e2"`, `"e4"`. |
| `san` | string | The move as a postable string (`"e4"`, `"Nf3"`, `"exd5"`, `"e8Q"`, `"0-0"`, with `+`/`#` on check/mate). |
| `check` | boolean | Whether the move gives check (non-terminal; a mate is `status` 1/2). |
| `castle` | string \| null | `"K"` or `"Q"` for a castle, else `null`. |
| `promotion` | string \| null | The promoted-to piece letter, else `null`. |
| `en` | boolean | Whether the move was an en-passant capture. |

### `User`

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | Assigned by the server. |
| `username` | string | 2 to 32 letters, digits, `_`, `.` or `-`, not all digits. Unique ignoring case; shown as typed. |
| `role` | string | `"user"` or `"admin"`. |
| `has_password` | boolean | Whether the account can log in with a password (a bot account may only use api tokens). |
| `created_at` | string | ISO 8601, UTC. |
| `disabled_at` | string \| null | When it was disabled, or `null`. |
| `identities` | array | Linked external ids, `{"provider", "external_id"}`; empty unless you are this user or an admin. |

Usernames cannot be all digits, so a client can accept "a user id or a username"
in one field without ambiguity.

### `Challenge`

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | The challenge's id. |
| `group_id` | integer | The group the game will be in. |
| `challenger_id`, `challenger_name` | integer, string | Who sent it. |
| `challenged_id`, `challenged_name` | integer, string | Who it is for. |
| `color` | string | The colour the **challenger** plays: `"white"`, `"black"` or `"random"` (decided on acceptance). |
| `created_at` | string | ISO 8601, UTC. |

### `LoginResult` and `TokenInfo`

Logging in, registering and creating an api token return a `LoginResult`:

```json
{
  "token": "css_9fJ…",
  "token_info": {"id": 12, "kind": "session", "name": "login",
                 "created_at": "2026-11-03T16:00:49+00:00", "expires_at": "2026-12-03T16:00:49+00:00"},
  "user": { "...": "a User (absent when creating an api token)" }
}
```

`token` appears only here. `GET /v1/auth/tokens` lists `TokenInfo`s, which never
include it. `kind` is `"session"` or `"api"`; `expires_at` is `null` for an api
token that does not expire.

### Result model

The game outcome is `state.status` plus `state.termination`:

- **`status`**: `0` in play, `1` white won, `2` black won, `3` draw. The game is
  over when `status != 0`; the winner (if any) is directly encoded (no need to infer
  it from whose turn it is).
- **`termination`**: *why* it ended: `"checkmate"`, `"resignation"`, `"stalemate"`,
  `"threefold_repetition"`, `"fifty_move_rule"`, `"insufficient_material"`, or
  `"agreement"`. It is `null` while the game is in play.

Draw-by-rule endings (stalemate, threefold, fifty-move, insufficient material) are
detected **automatically** by the server and end the game.

`check` in a `MoveResult` is true only for a *non-terminal* check (a checkmate is
`status` 1/2 with `termination` `"checkmate"`).

### Move notation

Moves are standard algebraic notation (SAN) or UCI strings:

- Pawn moves: `e4`, `d5`. Captures: `exd5`. Promotion: `e8=Q` or `e8Q`, `exd8=Q` or
  `exd8Q`.
- Piece moves: `Nf3`, `Bb5`, `Qh4`, `Ke2`, `Ra1`. Captures: `Nxe5`.
- Disambiguation: `Rad1` (file), `R1a3` (rank), `Nbd2`, also with a capture: `Nexg4`.
- Castling: `O-O` / `O-O-O`, or `0-0` / `0-0-0`.
- UCI, as engines and bots send moves: `e2e4`, `e7e8q`, castling as the king's move
  (`e1g1`).
- A trailing `+` (check) or `#` (checkmate) is accepted but never required.

Whatever form a move is sent in, `san` in the response, the move history and
`legal-moves` use chesssnake notation: SAN with the promotion letter appended
without `=` (`e8Q`) and castling in zeros (`0-0`). Every listed `san` can be posted
back as is. PGN export uses standard `e8=Q` and `O-O`.

### FEN

The board is stored and transmitted as standard **Forsyth-Edwards Notation**, the
universal one-line encoding used across the chess ecosystem (Stockfish, python-chess,
board editors, opening databases, …). A FEN has six space-separated fields:

```
rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1
```

1. **Placement**: ranks 8→1 separated by `/`; each rank lists files a→h with piece
   letters (uppercase = white, lowercase = black) and digits for runs of empty squares.
2. **Active color**: `w` or `b` (whose turn it is).
3. **Castling availability**: any of `KQkq`, or `-`.
4. **En-passant target**: the square a pawn skipped (e.g. `e3`), or `-`.
5. **Halfmove clock**: plies since the last pawn move or capture (for the fifty-move rule).
6. **Fullmove number**: starts at 1, increments after Black moves.

Because it's standard FEN, any chess library or tool can render or analyze a
chesssnake position directly. You can also fetch it as plain text from
[`GET …/fen`](#game-reads).

---

---

## Error handling

Every handled error returns a JSON envelope with a machine-readable type and a
human-readable detail:

```json
{ "error_type": "MoveIntoCheckError", "detail": "Making that move would put you in check" }
```

| Status | When | `error_type` values |
|---|---|---|
| `400 Bad Request` | The move or draw action breaks the rules | any engine error: `InvalidNotationError`, `GameOverError`, `MoveIntoCheckError`, `PromotionError`, `InvalidCastleError`, `PieceNotFoundError`, `MultiplePiecesFoundError`, `NothingToCaptureError`, `CaptureOwnPieceError`, `PieceOnSquareError`, `IllegalMoveError`, `DrawWrongTurnError`, `DrawAlreadyOfferedError`, `DrawNotOfferedError` |
| `401 Unauthorized` | No token, or an invalid, expired or revoked one; a failed login; a wrong current password | `AuthError` |
| `403 Forbidden` | Logged in but not allowed: not an admin, acting as someone else, not your turn or not your game, a disabled account, registration closed | `ForbiddenError`, `NotYourTurnError` |
| `404 Not Found` | No such game, user, challenge or token (or not one you may see) | `GameNotFoundError`, `UserNotFoundError`, `ChallengeNotFoundError`, `TokenNotFoundError` |
| `409 Conflict` | Stale `expected_version`; a username or external id taken; a challenge that cannot be made or accepted | `VersionConflictError`, `UserExistsError`, `ChallengeError` |
| `422 Unprocessable Entity` | A malformed value: an id out of range, a bad username, password, provider or token name; an admin not saying which player acts | `SQLIdError`, `UserValidationError` |
| `503 Service Unavailable` | The server is busy (no free database connection, or too many logins being checked at once). Retry shortly. | `SQLBusyError` |
| `500 Internal Server Error` | A database failure | `SQLError` |

FastAPI's own request-validation failures (malformed JSON, a missing body field, a
string where an integer belongs) are `422` with a list-shaped `detail` and no
`error_type`.

**On an error the server changed nothing.** Show `detail`, keep your current
state, and on a `409` re-read before retrying.

---

## Acting in a game

### Who acts

Moves, draws and resignations are made **as the logged-in user**. A user who is
not one of the two players gets `403 NotYourTurnError`; a player moving out of
turn gets the same.

Administrators can act for a player by sending `player_id` (how a bot plays for
the people it represents). An administrator who is one of the players and sends
no `player_id` acts as themselves. An administrator who is not playing and sends
no `player_id` moves for whichever side is to move, but must name the player for
a resignation or a draw (`422` otherwise). A non-admin sending someone else's
`player_id` gets `403 ForbiddenError`. Nobody can act as a disabled user.

### Optimistic concurrency (`expected_version`)

Every `GameState` carries a `version` that increases on each change. Send the
`version` you last saw as `expected_version`; if the game has moved on, the
server refuses with `409 VersionConflictError` instead of applying your action to
a position you have not seen. That makes retrying after a dropped response
**safe**. Even without it, actions on one game are serialized and never corrupt
each other.

### Finished games and rematches

A finished game keeps its id and stays readable through every read route. Acting
on it answers `400 GameOverError`. A rematch is a new challenge (and so a new game
with a new id); `GET /v1/games/between` lists every game two players have played.

---

## Endpoints

All examples omit the base URL and the `Authorization` header.

### `GET /health`

Liveness probe. Unversioned and never authenticated.

- **Response** `200 OK`: `{ "status": "ok" }`.
- A `200` means the process is up and its event loop responsive. It does **not**
  mean the database is reachable or that a worker is free: this route runs on the
  event loop on purpose, so it answers in milliseconds even when every worker is
  busy. It is a liveness probe, not a readiness probe.

---

### `GET /v1/info`

What a client needs to know before it has an account. No token needed.

- **Response** `200 OK`:

  ```json
  { "version": "0.14.0", "registration": "closed", "websocket": true }
  ```

- `registration` is `"open"` when anyone may `POST /v1/auth/register`.
- `websocket` says whether [`/v1/ws`](realtime-websockets.md) is served. When it
  is `false`, poll instead.

---

### Accounts and tokens

| Route | Body | Response | Notes |
|---|---|---|---|
| `POST /v1/auth/login` | `{username, password}` | `200 LoginResult` | No token needed. `401` on any wrong username or password; `403` if disabled. |
| `POST /v1/auth/register` | `{username, password}` | `201 LoginResult` | No token needed. `403` unless `api.registration = "open"`; `409` if the name is taken. |
| `POST /v1/auth/logout` | | `204` | Revokes the token presented. |
| `GET /v1/auth/me` | | `200 User` | Who the token belongs to. |
| `POST /v1/auth/password` | `{current_password, new_password}` | `204` | Ends your other sessions; keeps this one and your api tokens. `401` if `current_password` is wrong. |
| `POST /v1/auth/tokens` | `{name, current_password, expires_in_days?}` | `201 LoginResult` | An api token. `name` 1 to 64 characters; `expires_in_days` 1 to 3650, or omit for none. |
| `GET /v1/auth/tokens` | | `200 {"tokens": [TokenInfo]}` | Your tokens. Admins may add `?user_id=`. |
| `DELETE /v1/auth/tokens/{id}` | | `204` | Your own token (admins: any). `404` otherwise. |
| `GET /v1/auth/settings` | | `200 {name: value}` | Your settings, every one with its default filled in: `{"auto_queen": false}`. |
| `PATCH /v1/auth/settings` | `{name: value, ...}` | `200 {name: value}` | Change some; the rest keep their values. `422` for an unknown name or a value of the wrong type (`1` is not `true`). |

Settings are personal and kept on the server so they follow you to every client.
The server only stores them; what they do is up to the client. Today there is one:

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `auto_queen` | boolean | `false` | The web UI promotes a pawn to a queen without asking which piece. |
| `mark_highlight_color` | `"#rrggbb"` | `"#1b7a3a"` | The web UI's square highlights (right-click). |
| `mark_arrow_color` | `"#rrggbb"` | `"#1b7a3a"` | Its arrows (right-drag) and rings (middle-click). |
| `mark_ctrl_color` | `"#rrggbb"` | `"#c42b2b"` | Any mark made with Ctrl held. |
| `mark_alt_color` | `"#rrggbb"` | `"#7b3fc4"` | Any mark made with Alt held. |
| `mark_ctrl_alt_color` | `"#rrggbb"` | `"#0b7e86"` | Any mark made with Ctrl and Alt held. |

A colour must be exactly `#` and six hex digits (either case); it is stored and
returned lowercase. Anything else is a `422`.

---

### Users

| Route | Who | Body | Response |
|---|---|---|---|
| `POST /v1/users` | admin | `{username, password?, role?}` | `201 User`. Without a password the account can only use api tokens. |
| `GET /v1/users?username=` | any | | `200 User` (case does not matter), `404` if none |
| `GET /v1/users/search?q=&limit=20&offset=0` | any | | `200 {"users": [User]}`: names starting with `q`, ignoring case, ordered by name. An empty `q` lists everyone. `limit` is 1 to 200. |
| `GET /v1/users/{id}` | any | | `200 User` |
| `PATCH /v1/users/{id}` | self: `username`; admin: also `role`, `disabled`, `password` | any subset | `200 User`. A non-admin changing anything else, or another account, gets `403`. |
| `GET /v1/users/{provider}/{external_id}` | admin | | `200 User` linked to that external id, `404` if none |
| `POST /v1/users/{provider}/{external_id}` | admin | `{username}` | `200 User`: the linked user, **created** (with that username, no password) on first use. Idempotent: the one call a bot needs per interaction. |
| `PUT /v1/users/{id}/identities/{provider}/{external_id}` | admin | | `200 User`. `409` if that external id belongs to someone else. Linking again is a no-op. |
| `DELETE /v1/users/{id}/identities/{provider}/{external_id}` | admin, or the user themselves | | `200 User`. A user may unlink their own ids but never link one: linking asserts the external account is theirs, which only a trusted bot or an admin can vouch for. |

`provider` is a short lowercase name of your choosing (`[a-z0-9_-]`, up to 32
characters); `external_id` is any token up to 128 characters, stored as text, so
a Discord snowflake is its decimal digits. A user can be linked from any number
of providers.

A bot's usual setup: a dedicated admin account with no password
(`chesssnake user create discord-bot --admin --no-password` on the server) and an
api token for it (`chesssnake user token discord-bot --name bot`). It maps each
Discord member with `POST /v1/users/discord/{member_id}` and acts for them with
`player_id`.

---

### Challenges

A challenge is how a game normally starts. Accepting it creates the game, in the
same transaction that consumes the challenge, so a challenge can never be
accepted twice or accepted after being withdrawn.

#### `POST /v1/challenges`

- **Body**: `{ "opponent_id": 2, "group_id": 0, "color": "random" }`. `color` is
  the colour you want: `"white"`, `"black"` or `"random"` (the default, decided on
  acceptance). Admins may add `player_id` to challenge on someone's behalf.
- **Response** `201 Challenge`.
- **Errors**: `409 ChallengeError` when you challenge yourself, the opponent is
  disabled, a game between you is already in progress in that group, or a
  challenge between you is already pending (if *they* challenged *you*, the
  detail names the challenge to accept instead); `404` if the opponent does not
  exist.

#### `GET /v1/challenges?direction=incoming|outgoing|all`

Your pending challenges, oldest first: `{ "challenges": [Challenge] }`. The
default is `all`. Admins may add `user_id=` to see someone else's.

#### `GET /v1/challenges/{id}`

One challenge, if you are in it (admins: any). `404` otherwise.

#### `POST /v1/challenges/{id}/accept`

Only the challenged user can accept (an admin acts as them). Creates the game
and returns it: **`201 GameState`**. `403` for the challenger; `404` if it is no
longer pending; `409` if a game between the two started in the meantime (the
challenge is then kept).

#### `DELETE /v1/challenges/{id}`

Decline (as the challenged user) or withdraw (as the challenger): `204`. Admins
may delete any. `404` if it is not pending or not yours.

---

### Games

#### `POST /v1/games` (admin)

Create a game directly, without a challenge: `{ "group_id": 0, "white_id": 1,
"black_id": 2 }`. Returns the game in progress between those colours in that
group if there is one, otherwise a new one: `200 GameState`. `404` for an unknown
player, `422` if both players are the same user.

#### `GET /v1/games?player_id=&group_id=`

Games in progress, most recently changed first: `{ "games": [GameState] }`.
Without `player_id`, your own; without `group_id`, in every group.

#### `GET /v1/games/live?limit=50`

Every game in progress, in **any** group and between any players, most recently
changed first: `{ "games": [GameState] }`. This is what spectators browse. `limit`
is 1 to 200.

#### `GET /v1/games/finished?player_id=&limit=50&before=`

Finished games, newest first: `{ "games": [GameState] }`. With `player_id`, only
that player's games (either colour). To page back, pass the last id you got as
`before`. `limit` is 1 to 200.

#### `GET /v1/games/between?player1=&player2=&group_id=0&status=all`

Every game between two players in a group, **either colour**, oldest first:
`{ "games": [GameState] }`. `status` is `active` (the game in progress, if any),
`finished`, or `all`. This is a head-to-head history, and how to find the game
two players currently have.

#### `GET /v1/games/record?player1=&player2=&group_id=0`

Win/draw/loss record over their **finished** games in a group, both colour
arrangements:

```json
{ "player1": 1, "player2": 2, "player1_wins": 3, "player2_wins": 1, "draws": 2 }
```

A win by checkmate or resignation counts for that side; every kind of draw counts
as a draw; games in progress are not counted.

#### `GET /v1/games/{id}`

The game, in progress or finished: `200 GameState`, or `404 GameNotFoundError`.
Poll it (compare `version`) to see the opponent's moves, or follow it over a
[websocket](realtime-websockets.md) when the server offers one.

#### `DELETE /v1/games/{id}` (admin)

Delete a game, in progress or finished, and its moves: `204`, or `404`.

#### `POST /v1/games/{id}/moves`

| Field | Type | Required | Notes |
|---|---|---|---|
| `move` | string | yes | SAN or UCI ([move notation](#move-notation)) |
| `expected_version` | integer | no | `409` if stale |
| `player_id` | integer | no | admins only: act as this player |

```json
{ "move": "e4", "expected_version": 1 }
```

- **Response** `200 MoveResult`. The move is already stored when you receive it.
- **Errors**: `400` with the engine's `error_type` for an illegal or malformed
  move, or `GameOverError` on a finished game; `403 NotYourTurnError` out of turn
  or outside the game; `409 VersionConflictError`; `404`. Nothing is stored when a
  move is refused.

#### `POST /v1/games/{id}/resign`, `/draw/offer`, `/draw/accept`, `/draw/decline`

Body optional: `{ "expected_version": 5 }` (and `player_id` for admins).
Response `200 GameState`. Draw rules, enforced by the engine:

- `offer`: only on your own turn. Offering when the opponent already has an
  offer open **accepts** it.
- `accept` ends the game in a draw (`status` 3, `termination` `"agreement"`).
- `decline` clears the opponent's offer; play continues.

Errors: `400 DrawWrongTurnError`, `DrawAlreadyOfferedError`, `DrawNotOfferedError`,
`GameOverError`; `403`; `409`; `404`.

#### Game reads

| Route | Response |
|---|---|
| `GET /v1/games/{id}/legal-moves` | `{ "moves": [ { "from": "e2", "to": "e4", "san": "e4", "promotion": null } ] }`; each `san` is postable as is. Castling has `to: null`. A finished game has none. |
| `GET /v1/games/{id}/history` | `{ "moves": [ { "ply": 1, "san": "e4" }, { "ply": 2, "san": "e5" } ] }` |
| `GET /v1/games/{id}/pgn` | `text/plain` PGN: tag pairs, movetext and result, ready for any chess tool |
| `GET /v1/games/{id}/fen` | `text/plain` FEN (also in every `GameState`) |
| `GET /v1/games/{id}/image?perspective=white\|black` | `image/png`. Without `perspective`, both orientations side by side with the players' names; with it, one board from that side. |

---

## Real-time updates (websockets)

When the server has `websocket.enabled` on (it is off by default), a client can
open a websocket at `/v1/ws` and be told about every change to the games it
follows, and about challenges and new games of its own, instead of polling. It
logs in by sending its token as the first message (browsers cannot set an
`Authorization` header on a websocket, and a token in the URL would end up in
access logs); logging out or revoking the token closes the socket at once. The
REST contract is the same either way: the socket only reports changes, and every
action is still a request here.

The protocol is specified in [Real-time updates](realtime-websockets.md).

---

## The Python client

The bundled client turns all of this into objects and exceptions:

```python
from chesssnake import Game, connect
from chesssnake.engine.errors import MoveIntoCheckError

client = connect("http://localhost:8000", username="alice", password="...")
challenge = client.challenge("bob", color="white")      # bob then: client.accept_challenge(id)

state = client.current_games()[0]                        # once bob has accepted
game = Game.remote(state, client=client)
result = game.move("e4")                                 # MoveResult, already stored
try:
    game.move("Ke2")
except MoveIntoCheckError as e:
    print("rejected:", e)
game.refresh()                                           # pick up bob's reply
```

- `connect(api_url, ...)` returns an `ApiClient`. It logs in with
  `username`/`password`, or uses a `token`, `$CHESSSNAKE__CLIENT__TOKEN`, or the
  token `chesssnake login` stored for that endpoint.
- `ApiClient` has one method per route: `login`, `me`, `create_token`, `challenge`,
  `challenges`, `accept_challenge`, `decline_challenge`, `get_game`,
  `current_games`, `games_between`, `record`, `move`, and the admin methods
  (`create_user`, `update_user`, `create_game`, the identity methods). Players may
  be given as ids or usernames.
- `Game.remote(game_id, client=...)` mirrors one game locally (board, accessors,
  `render()`), sends `expected_version` with every action, and maps every error
  response back to the same exception class the engine or database raised, so
  `except GameOverError` works the same against a server as against a local game.

---

## Building your own client

You need HTTP and nothing else. A typical frontend:

1. **Log in**: `POST /v1/auth/login`; keep the token and the `user`. On any `401`
   later, log in again.
2. **Home screen**: `GET /v1/auth/me`, `GET /v1/games` (your games in progress)
   and `GET /v1/challenges?direction=incoming`.
3. **Start a game**: `POST /v1/challenges`, or accept an incoming one, which
   returns the new game.
4. **Render**: parse the [FEN](#fen) with any chess library, or show
   `GET /v1/games/{id}/image`.
5. **Show options** (optional): `GET /v1/games/{id}/legal-moves`.
6. **Move**: `POST /v1/games/{id}/moves {"move": …, "expected_version": …}`. On
   `200` replace your state with `result.state`. On a `4xx` show `detail` and keep
   your state.
7. **See the opponent move**: [subscribe to the game over a websocket](realtime-websockets.md)
   and render each `game` event's `state`. If the server answers the upgrade with
   `403` (websockets off), poll `GET /v1/games/{id}` and watch `version` instead.
8. **End states**: `status` `1`/`2` is a win for white/black, `3` a draw;
   `termination` says why.

The golden rule: **the server's response is the truth.** Never advance your view
on a refused request, and re-read whenever in doubt.
