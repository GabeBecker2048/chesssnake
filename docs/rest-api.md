---
title: REST API
---

Anything that speaks HTTP can play on a chesssnake server. Your client needs no
chess logic: it sends a move, and the server answers with the new position or
the reason the move was refused.

- Every route but `/health` is under `/v1`. Bodies are JSON.
- Your server also has interactive docs at `/docs`, where every route can be
  tried from the browser.
- New fields may be added to any response: ignore keys you do not know.

## A game in six requests

```sh
URL=http://localhost:8000

# 1. Log in. Send the token with everything after this.
TOKEN=$(curl -s $URL/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"..."}' | jq -r .token)
AUTH="Authorization: Bearer $TOKEN"

# 2. Challenge someone (opponent_id is their user id).
curl -s "$URL/v1/users?username=bob" -H "$AUTH"                     # find the id
curl -s $URL/v1/challenges -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"opponent_id": 2, "color": "white"}'

# 3. Bob accepts (with his own token). The answer is the new game.
curl -s -X POST $URL/v1/challenges/1/accept -H "$BOB_AUTH"

# 4. Move.
curl -s $URL/v1/games/1/moves -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"move": "e4"}'

# 5. See the opponent's move: read the game and compare "version".
curl -s $URL/v1/games/1 -H "$AUTH"

# 6. A picture of the board.
curl -s "$URL/v1/games/1/image?perspective=white" -H "$AUTH" -o board.png
```

For a script, use an [api token](accounts.html#logins-and-api-tokens) instead
of logging in. To be told about moves instead of asking, see
[Websocket API](websocket-api.html).

## Logging in

Send `Authorization: Bearer <token>` with every request. Only `/health`,
`/v1/info`, `/v1/auth/login` and `/v1/auth/register` work without one. A token
comes from logging in (it lasts `api.session_lifetime_days`, 30 by default) or
is an api token.

What each kind of account may do is in
[Accounts](accounts.html#users-and-administrators). Administrators can add
`player_id` to a request to act as that player, which is how
[bots](bots.html) play for people.

## Errors

Every error has the same shape:

```json
{ "error_type": "MoveIntoCheckError", "detail": "Making that move would put you in check" }
```

`detail` is fit to show a person. Nothing was changed by a request that failed.

| Status | Meaning | `error_type` |
|---|---|---|
| `400` | The move or draw action breaks the rules | a [chess error](moves.html#when-a-move-is-refused), `DrawWrongTurnError`, `DrawAlreadyOfferedError`, `DrawNotOfferedError`, `GameOverError` |
| `401` | No token, or an invalid or expired one; a failed login | `AuthError` |
| `403` | Not allowed: not your turn, not your game, not an admin, a disabled account | `ForbiddenError`, `NotYourTurnError` |
| `404` | No such game, user, challenge or token, or not one you may see | `GameNotFoundError`, `UserNotFoundError`, `ChallengeNotFoundError`, `TokenNotFoundError` |
| `409` | The game changed since you looked; a name is taken; a challenge that cannot be made | `VersionConflictError`, `UserExistsError`, `ChallengeError` |
| `422` | A malformed value | `InvalidIdError`, `UserValidationError`, or no `error_type` for a malformed body |
| `503` | The server is busy: try again shortly | `DatabaseBusyError` |

On `401`, log in again. On `409`, read the game again before retrying.

## Data

### GameState

A game, in progress or finished.

```json
{
  "id": 41,
  "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
  "status": 0,
  "termination": null,
  "draw": null,
  "version": 2,
  "generation": 1,
  "group_id": 0,
  "white_id": 1,
  "black_id": 2,
  "white_name": "alice",
  "black_name": "bob",
  "started_at": "2026-11-03T16:00:49.852248+00:00",
  "updated_at": "2026-11-03T16:01:02.117730+00:00"
}
```

| Field | Meaning |
|---|---|
| `id` | The game's id. Kept when the game finishes, and never reused. |
| `fen` | The position, as standard FEN. Whose turn it is is the second part: `w` or `b`. |
| `status` | `0` in play, `1` white won, `2` black won, `3` draw. |
| `termination` | Why it ended: `checkmate`, `resignation`, `stalemate`, `threefold_repetition`, `fifty_move_rule`, `insufficient_material`, `agreement`. `null` in play. |
| `draw` | Who has a draw offer open: `0` white, `1` black, `null` nobody. |
| `version` | Goes up with every change. See [Safe retries](#safe-retries). |
| `generation` | `1` for the first game between these colours in this group, `2` for the next, and so on. |
| `group_id` | The [group](bots.html#groups) the game is in. `0` unless a bot says otherwise. |

### MoveResult

What a move returns.

| Field | Meaning |
|---|---|
| `state` | The `GameState` after the move. |
| `from`, `to` | The squares, such as `"e2"` and `"e4"`. |
| `san` | The move as text: `"e4"`, `"Nxe5+"`, `"e8Q"`, `"0-0"`. |
| `check` | Whether it gives check. |
| `castle` | `"K"`, `"Q"` or `null`. |
| `promotion` | The new piece's letter, or `null`. |
| `en_passant` | Whether it was an en-passant capture. |
| `legal_moves` | The other side's legal moves now, as in [`legal-moves`](#reading-a-game). Empty when the game is over. |

### User

| Field | Meaning |
|---|---|
| `id`, `username` | A username is never all digits, so one field can take "an id or a name". |
| `role` | `"user"` or `"admin"`. |
| `has_password` | `false` for an account that can only use api tokens. |
| `created_at`, `disabled_at` | `disabled_at` is `null` for an active account. |
| `identities` | Linked outside ids, `{"provider", "external_id"}`. Shown only to that user and to admins. |

### Challenge

`id`, `group_id`, `challenger_id`, `challenger_name`, `challenged_id`,
`challenged_name`, `created_at`, and `color`: the colour the **challenger**
plays, `"white"`, `"black"` or `"random"`.

### LoginResult

```json
{
  "token": "css_9fJ...",
  "token_info": {"id": 12, "kind": "session", "name": "login",
                 "created_at": "2026-11-03T16:00:49+00:00", "expires_at": "2026-12-03T16:00:49+00:00"},
  "user": { }
}
```

`token` is shown only here. `user` is a `User`.

## Routes

### Server

| Route | Returns |
|---|---|
| `GET /health` | `{"status": "ok"}` when the server is up. No login. |
| `GET /v1/info` | `{"version", "registration", "websocket"}`. No login. |

### Your account

| Route | Body | Returns |
|---|---|---|
| `POST /v1/auth/login` | `{username, password}` | `LoginResult` |
| `POST /v1/auth/register` | `{username, password}` | `201 LoginResult`. Only when registration is open. |
| `POST /v1/auth/logout` | | `204`. Ends the token you sent. |
| `GET /v1/auth/me` | | `User` |
| `POST /v1/auth/password` | `{current_password, new_password}` | `204` |
| `POST /v1/auth/tokens` | `{name, current_password, expires_in_days?}` | `201 LoginResult`: a new api token |
| `GET /v1/auth/tokens` | | `{"tokens": [...]}` |
| `DELETE /v1/auth/tokens/{id}` | | `204` |
| `GET /v1/auth/settings` | | your [preferences](browser.html#your-account), as `{name: value}` |
| `PATCH /v1/auth/settings` | `{name: value}` | all of them, after the change |

### Users

| Route | Who | Returns |
|---|---|---|
| `GET /v1/users?username=bob` | anyone | `User` |
| `GET /v1/users/{id}` | anyone | `User` |
| `GET /v1/users/search?q=bo&limit=20&offset=0` | anyone | `{"users": [...]}`: names starting with `q` |
| `POST /v1/users` with `{username, password?, role?}` | admin | `201 User` |
| `PATCH /v1/users/{id}` with any of `{username, role, disabled, password}` | admin; anyone may change their own `username` | `User` |
| `GET /v1/identities/{provider}/{external_id}` | admin | the linked `User` |
| `POST /v1/identities/{provider}/{external_id}` with `{username}` | admin | the linked `User`, created the first time. See [Bots](bots.html). |
| `PUT /v1/users/{id}/identities/{provider}/{external_id}` | admin | `User`, now linked |
| `DELETE /v1/users/{id}/identities/{provider}/{external_id}` | admin, or that user | `User`, now unlinked |

### Challenges

| Route | Body | Returns |
|---|---|---|
| `POST /v1/challenges` | `{opponent_id, color?, group_id?}` | `201 Challenge`. `color` is the one you want; `"random"` if left out. |
| `GET /v1/challenges?direction=incoming` | | `{"challenges": [...]}`. `incoming`, `outgoing` or `all`. |
| `GET /v1/challenges/{id}` | | `Challenge` |
| `POST /v1/challenges/{id}/accept` | | `201 GameState`: the new game |
| `DELETE /v1/challenges/{id}` | | `204`. Declines one sent to you, or withdraws your own. |

A challenge is refused with `409` when a game between you is already in
progress in that group, or a challenge between you is already pending.

### Finding games

| Route | Returns |
|---|---|
| `GET /v1/games` | Your games in progress. `?player_id=` for someone else's, `?group_id=` for one group. |
| `GET /v1/games/live?limit=50` | Every game in progress on the server. |
| `GET /v1/games/finished?player_id=&limit=50&before=` | Finished games, newest first. Page back by passing the last id as `before`. |
| `GET /v1/games/between?player1=&player2=&group_id=0&status=all` | Every game between two players. `status` is `active`, `finished` or `all`. |
| `GET /v1/games/record?player1=&player2=&group_id=0` | `{"player1", "player2", "player1_wins", "player2_wins", "draws"}` |

The first four return `{"games": [...]}`.

### Playing a game

| Route | Body | Returns |
|---|---|---|
| `POST /v1/games/{id}/moves` | `{move, expected_version?}` | `MoveResult` |
| `POST /v1/games/{id}/resign` | `{expected_version?}` | `GameState` |
| `POST /v1/games/{id}/draw/offer` | `{expected_version?}` | `GameState` |
| `POST /v1/games/{id}/draw/accept` | `{expected_version?}` | `GameState` |
| `POST /v1/games/{id}/draw/decline` | `{expected_version?}` | `GameState` |

- `move` is SAN or UCI: see [Writing moves](moves.html).
- A draw can be offered only on your own turn. Offering while your opponent's
  offer is open accepts it.
- Administrators may add `player_id` to any of these.

### Reading a game

| Route | Returns |
|---|---|
| `GET /v1/games/{id}` | `GameState` |
| `GET /v1/games/{id}/legal-moves` | `{"moves": [{"from": "e2", "to": "e4", "san": "e4", "promotion": null}]}`. Castling has `"to": null`. |
| `GET /v1/games/{id}/history` | `{"moves": [{"ply": 1, "san": "e4"}, {"ply": 2, "san": "e5"}]}` |
| `GET /v1/games/{id}/pgn` | the game as PGN, as plain text |
| `GET /v1/games/{id}/fen` | the position as FEN, as plain text |
| `GET /v1/games/{id}/image` | a PNG of both sides with the names. `?perspective=white` or `black` for one board. |

Any logged-in user can read any game.

### Administrators

| Route | Body | Returns |
|---|---|---|
| `POST /v1/games` | `{white_id, black_id, group_id?}` | `GameState`: a new game, or the one those two already have in that group |
| `DELETE /v1/games/{id}` | | `204` |

## Safe retries

Every `GameState` has a `version` that goes up with each change. Send the one
you last saw as `expected_version`:

```json
{ "move": "e4", "expected_version": 5 }
```

If the game has changed since, the server answers `409 VersionConflictError`
and does nothing. That makes it safe to retry after a lost response, and stops
a move meant for one position landing in another.

## Writing a client

1. Log in, and keep the token. On any `401`, log in again.
2. Show `GET /v1/games` and `GET /v1/challenges?direction=incoming`.
3. Draw the board from the `fen`, or show the `image`.
4. Offer the moves from `legal-moves` (they also come back with every move).
5. Post the move with `expected_version`. On success, show `state` from the
   answer. On an error, show `detail` and keep what you had.
6. See the opponent's move over a [websocket](websocket-api.html), or by
   reading the game every few seconds and comparing `version`.
7. The game is over when `status` is not `0`.

The server's answer is always the truth: never change your board because of a
request that was refused.
