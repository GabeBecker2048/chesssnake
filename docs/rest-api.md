# chesssnake REST API reference

The `chesssnake api-endpoint` is a **server-authoritative** chess service. Clients
do **not** implement chess: they send a move (or a draw action), and the server
runs the engine, validates the action against the stored game, applies it,
persists the result, and returns the new state — or a structured error describing
exactly what went wrong. Any HTTP client, in any language, can play a full game
without a chess engine of its own.

This document describes every route, the JSON shapes that go in and out, every
response you can get, and how a client is expected to interpret them.

- [Overview](#overview)
- [Authentication](#authentication)
- [Data models](#data-models)
- [Error handling](#error-handling)
- [Endpoints](#endpoints)
  - [Health](#get-health)
  - [Create or load a game](#post-v1games)
  - [Get a game's state](#get-v1gamesgwb)
  - [Play a move](#post-v1gamesgwbmoves)
  - [Offer / accept / decline a draw](#post-v1gamesgwbdrawaction)
  - [Render the board as an image](#get-v1gamesgwbimage)
  - [Delete a game](#delete-v1gamesgwb)
  - [List a player's current games](#get-v1games)
  - [Check whether a game exists](#get-v1gamesgexists)
  - [Issue or accept a challenge](#post-v1challenges)
  - [Check a pending challenge](#get-v1challengesgexists)
  - [Delete a challenge](#delete-v1challenges)
- [How the chesssnake Python client interprets responses](#how-the-chesssnake-python-client-interprets-responses)
- [Building your own client](#building-your-own-client)

---

## Overview

- **Base URL** — whatever host/port the server is bound to, e.g. `http://localhost:8000`.
- **Versioning** — every gameplay/challenge route is under the `/v1` prefix. `/health`
  is intentionally unversioned. New incompatible versions would be added under a new
  prefix (`/v2`) rather than changing `/v1`.
- **Content type** — request and response bodies are JSON (`application/json`), except
  the board image endpoint, which returns `image/png`.
- **Identifiers** — a game is uniquely identified by the triple
  `(group_id, white_id, black_id)`. All three are 64-bit integers (PostgreSQL
  `BIGINT`). `group_id` is just a namespace/discriminator (e.g. a Discord server id,
  a tournament id); it is not a foreign key. `white_id` always plays white and moves
  first.
- **Who is the server the authority on?** The rules. The server decides whether a move
  is legal, whose turn it is, and when the game is over. Clients render and collect
  input; they never decide legality.

### The game lifecycle at a glance

1. `POST /v1/games` to load-or-create the game for a triple → you get its `GameState`.
2. `POST /v1/games/{g}/{w}/{b}/moves` with `{"move": "e4"}` each turn → you get a
   `MoveResult` (or an error). The server has already stored the new state.
3. Poll `GET /v1/games/{g}/{w}/{b}` (or re-`POST` step 1) to see the opponent's moves.
4. Optionally `GET …/image` to display the board, `POST …/draw/*` to negotiate a draw,
   and `DELETE …` to remove a finished game.

---

## Authentication

Authentication is **optional and off by default**.

- If the server process has the environment variable `CHESSSNAKE_API_KEY` set, then
  **every `/v1` route requires** the header `X-API-Key: <that value>`. Requests
  without it, or with a wrong value, get **`401 Unauthorized`**.
- If `CHESSSNAKE_API_KEY` is unset, no key is required.
- `GET /health` is **always open** — it never requires the key (so load balancers and
  uptime checks can probe it).

```
X-API-Key: my-secret-key
```

A `401` body is FastAPI's standard shape: `{"detail": "Invalid or missing API key"}`
(note: no `error_type` field — see [Error handling](#error-handling)).

---

## Data models

### `GameState`

The persisted state of a game. Returned by the create, get-state, and draw endpoints,
and nested inside a `MoveResult`.

| Field | Type | Meaning |
|---|---|---|
| `board` | string | The serialized board (see [board serialization](#board-serialization)). |
| `turn` | integer | Whose turn it is: `0` = white, `1` = black. |
| `moved` | string | 6 characters of `0`/`1` — castling rights (see below). |
| `status` | integer | `0` = in play, `1` = checkmate, `2` = draw. |
| `pawnmove` | string \| null | The en-passant target square (e.g. `"e4"`) if a pawn just double-stepped, else `null`. |
| `draw` | integer \| null | Who has an open draw offer: `0` = white, `1` = black, `null` = none. |
| `wname` | string \| null | White's display name. |
| `bname` | string \| null | Black's display name. |

Example:

```json
{
  "board": "R1 N1 B1 Q1 K1 B1 N1 R1;P1 P1 P1 P1 P1 P1 P1 P1;-- -- -- -- -- -- -- --;-- -- -- -- -- -- -- --;-- -- -- -- P0 -- -- --;-- -- -- -- -- -- -- --;P0 P0 P0 P0 -- P0 P0 P0;R0 N0 B0 Q0 K0 B0 N0 R0",
  "turn": 1,
  "moved": "000000",
  "status": 0,
  "pawnmove": "e4",
  "draw": null,
  "wname": "Bob",
  "bname": "Phil"
}
```

### `MoveResult`

The outcome of a played move — the move itself plus the resulting `GameState`.
Returned only by [play a move](#post-v1gamesgwbmoves).

| Field | Type | Meaning |
|---|---|---|
| `state` | `GameState` | The full state **after** the move. |
| `from` | string | Origin square of the piece that moved, e.g. `"e2"`. |
| `to` | string | Destination square, e.g. `"e4"`. |
| `check` | boolean | Whether the move gives check to the side now to move. |
| `castle` | string \| null | `"K"` (king-side) or `"Q"` (queen-side) if the move was a castle, else `null`. |
| `promotion` | string \| null | The promoted-to piece letter (`"Q"`, `"R"`, `"B"`, `"N"`) if a pawn promoted, else `null`. |
| `en` | boolean | Whether the move was an en-passant capture. |

Example (after `1. e4`):

```json
{
  "state": { "...": "a GameState as above" },
  "from": "e2",
  "to": "e4",
  "check": false,
  "castle": null,
  "promotion": null,
  "en": false
}
```

> Checkmate/stalemate are read from `state.status` (`1`/`2`), not from a dedicated
> flag. `check` is true only for a non-terminal check. To detect a *win*: the game is
> over when `state.status != 0`; the winner is the side that just moved (i.e. the
> opposite of `state.turn`) when `status == 1`; `status == 2` is a draw.

### Move notation

Moves are standard algebraic notation strings, exactly as the engine parses them:

- Pawn moves: `e4`, `d5`. Captures: `exd5`. Promotion: `e8Q`, `exd8Q` (piece letter
  appended, no `=`).
- Piece moves: `Nf3`, `Bb5`, `Qh4`, `Ke2`, `Ra1`. Captures: `Nxe5`.
- Disambiguation: `Rad1` (file), `R1a3` (rank), `Nbd2`.
- Castling: `0-0` (king-side) and `0-0-0` (queen-side) — **zeros, not the letter O**.
- A trailing `+` (check) or `#` (checkmate) is accepted but never required.

### Board serialization

`board` is 8 ranks separated by `;`, from rank 8 (top / black's back rank) down to
rank 1. Each rank is 8 space-separated tokens, from file a to file h. A token is
either `--` (empty) or `<type><color>` where type is one of `K Q R B N P` and color
is `0` (white) or `1` (black). For example `Q0` is a white queen, `N1` a black knight.

`moved` is 6 characters of `0`/`1` recording castling rights (whether the relevant
king/rook has ever moved): in order — white a1-rook, white king, white h1-rook,
black a8-rook, black king, black h8-rook. `1` means "has moved" (castling with that
piece is no longer possible).

This is enough to fully reconstruct a position (together with `turn` and `pawnmove`
for en passant). Most frontends will just render `board`; the `moved`/`pawnmove`
fields matter only if you reconstruct a full engine position.

---

## Error handling

Every handled error returns a JSON envelope with a machine-readable type and a
human-readable detail:

```json
{ "error_type": "MoveIntoCheckError", "detail": "Making that move would put you in check" }
```

The HTTP status code indicates the category; `error_type` names the exact condition.

| Status | When | `error_type` values |
|---|---|---|
| `400 Bad Request` | The move or draw action is illegal / invalid chess input | any engine error: `InvalidNotationError`, `GameOverError`, `MoveIntoCheckError`, `PromotionError`, `InvalidCastleError`, `PieceNotFoundError`, `MultiplePiecesFoundError`, `NothingToCaptureError`, `CaptureOwnPieceError`, `PieceOnSquareError`, `DrawWrongTurnError`, `DrawAlreadyOfferedError`, `DrawNotOfferedError` |
| `404 Not Found` | The referenced game does not exist | `GameNotFoundError` |
| `409 Conflict` | An invalid challenge (self-challenge, duplicate, or a game already exists) | `ChallengeError` |
| `422 Unprocessable Entity` | An id is outside the BIGINT range | `SQLIdError` |
| `500 Internal Server Error` | A database failure | `SQLError` |
| `401 Unauthorized` | Missing/invalid API key (only when a key is configured) | *(none — see below)* |

Notes:

- **`401`** and FastAPI's own request-validation failures (malformed JSON, missing
  required body fields, a non-integer where an integer is required) use FastAPI's
  default shape `{"detail": ...}` and do **not** carry an `error_type`. Treat any
  response without `error_type` as a transport/validation error rather than a game
  rule violation.
- The full list of engine (`ChessError`) meanings is documented alongside
  `Game.move` in the engine; the common ones:
  - `InvalidNotationError` — the `move` string isn't valid algebraic notation.
  - `PieceNotFoundError` — no piece of that type can legally reach the target square.
  - `MultiplePiecesFoundError` — the move is ambiguous; add file/rank disambiguation.
  - `MoveIntoCheckError` — the move would leave your own king in check.
  - `NothingToCaptureError` / `CaptureOwnPieceError` / `PieceOnSquareError` — capture
    or occupancy mistakes.
  - `PromotionError` — a pawn reached the back rank without a promotion piece, or a
    promotion was specified off the back rank.
  - `InvalidCastleError` — castling isn't legal here.
  - `GameOverError` — the game already ended; no further moves/draws are allowed.
  - `DrawWrongTurnError` / `DrawAlreadyOfferedError` / `DrawNotOfferedError` — draw
    negotiation done out of turn / twice / with no offer outstanding.

**Expected client behavior:** on a non-2xx response, read the status and `error_type`,
surface `detail` to the user, and **do not** advance any local game state — the server
did not change anything. The move/draw was rejected atomically.

---

## Endpoints

Path parameters are written `{g}` = `group_id`, `{w}` = `white_id`, `{b}` =
`black_id`. All example URLs omit the base URL and (when required) the `X-API-Key`
header for brevity.

### `GET /health`

Liveness probe. Unversioned and never authenticated.

- **Response** `200 OK`

  ```json
  { "status": "ok" }
  ```

- **Client behavior:** use for readiness/uptime checks. A `200` means the process is
  up; it does not by itself guarantee the database is reachable.

---

### `POST /v1/games`

Load the game for a triple, **creating a fresh one if it doesn't exist** (idempotent
get-or-create). This is how a client "opens" a game.

- **Request body**

  | Field | Type | Default | Notes |
  |---|---|---|---|
  | `group_id` | integer | `0` | |
  | `white_id` | integer | `0` | plays white, moves first |
  | `black_id` | integer | `1` | |
  | `white_name` | string | `""` | display name (only set on creation) |
  | `black_name` | string | `""` | display name (only set on creation) |

  ```json
  { "group_id": 10, "white_id": 1, "black_id": 2, "white_name": "Bob", "black_name": "Phil" }
  ```

- **Response** `200 OK` — a [`GameState`](#gamestate). A brand-new game has the
  starting position, `turn: 0`, `status: 0`, `draw: null`.
- **Errors:** `422 SQLIdError` if any id is out of BIGINT range; `401` if a key is
  required and missing.
- **Client behavior:** call this once to obtain the current state, then drive the game
  with `/moves`. Calling it again always returns the *existing* row if the game already
  exists — it never resets a game in progress.

---

### `GET /v1/games/{g}/{w}/{b}`

Fetch the current state of an existing game without modifying it.

- **Response** `200 OK` — a [`GameState`](#gamestate).
- **Errors:** `404 GameNotFoundError` if there is no such game; `422 SQLIdError`;
  `401`.
- **Client behavior:** use this to refresh — e.g. poll it to detect that the opponent
  has moved (compare `turn`, `board`, or `status`). Prefer this over re-`POST`ing
  `/v1/games` when you only want to read (it won't create a game as a side effect).

---

### `POST /v1/games/{g}/{w}/{b}/moves`

Play a move. **The server validates and applies it** against the stored game and
persists the new state atomically.

- **Request body**

  ```json
  { "move": "e4" }
  ```

- **Response** `200 OK` — a [`MoveResult`](#moveresult). By the time you receive it,
  the move is already stored server-side.
- **Errors:**
  - `400` with an engine `error_type` if the move is illegal or malformed — e.g.
    `InvalidNotationError` (`"move": "xyz"`), `PieceNotFoundError` (`"move": "e5"` as
    white's first move), `MoveIntoCheckError`, `GameOverError` (the game already
    ended), etc. **Nothing is stored** when a move is rejected.
  - `404 GameNotFoundError`, `422 SQLIdError`, `401`.

  Example rejection:

  ```json
  { "error_type": "InvalidNotationError", "detail": "\"xyz\" is not in valid algebraic notation" }
  ```

- **Whose move is it?** The move is applied for the side whose turn it currently is
  (`state.turn`). The endpoint does not verify *which* human is calling — there is no
  per-player identity beyond the optional service-wide API key. A frontend is expected
  to only submit moves for the side to move.
- **Concurrency:** each move is applied inside a locked transaction
  (`SELECT … FOR UPDATE`), so two clients submitting for the same game are serialized —
  the second sees the first's result and is validated against it. There is no lost
  update.
- **Client behavior:** on `200`, replace your view with `result.state`; use `from`/`to`
  to highlight or animate the move and `check`/`state.status` to show check/checkmate.
  On `400`, show `detail` and keep your current state (the move didn't happen).

---

### `POST /v1/games/{g}/{w}/{b}/draw/{action}`

Negotiate a draw. `{action}` is one of `offer`, `accept`, `decline`.

- **Request body**

  ```json
  { "player_id": 1 }
  ```

  `player_id` must be the `white_id` or `black_id` of this game — it identifies who is
  performing the draw action.

- **Semantics** (all enforced by the engine):
  - `offer` — record a draw offer from `player_id`. You may only offer on your own
    turn. If the *opponent* already had an offer outstanding, offering back **accepts**
    it (the game ends in a draw).
  - `accept` — accept the opponent's outstanding offer; the game ends in a draw
    (`status` becomes `2`).
  - `decline` — clear the opponent's outstanding offer; play continues (`draw` becomes
    `null`).
- **Response** `200 OK` — the resulting [`GameState`](#gamestate). After an `offer`,
  `draw` is `0`/`1`; after an `accept`, `status` is `2`; after a `decline`, `draw` is
  `null`.
- **Errors:**
  - `400 DrawWrongTurnError` — offered a draw when it isn't your turn.
  - `400 DrawAlreadyOfferedError` — you already have an offer outstanding.
  - `400 DrawNotOfferedError` — accepted/declined with no offer to act on.
  - `400 GameOverError` — the game already ended.
  - `404 GameNotFoundError`, `422 SQLIdError`, `401`.
- **Client behavior:** reflect the returned `draw`/`status`. When `status` becomes `2`,
  render "draw" and stop accepting moves (further moves return `GameOverError`).

---

### `GET /v1/games/{g}/{w}/{b}/image`

Render the current board to a PNG **on the server**. This lets a frontend display the
board without any chess/rendering code of its own.

- **Response** `200 OK` with `Content-Type: image/png` — raw PNG bytes (a side-by-side
  white-oriented and black-oriented board with the player names).
- **Errors:** `404 GameNotFoundError`, `422 SQLIdError`, `401`. (Error bodies are JSON
  as usual, even though success is a PNG.)
- **Client behavior:** display or cache the bytes as an image. The image reflects the
  latest stored position; request it again after a move to refresh. (It does not
  highlight the last move — that information is available in `MoveResult` from the moves
  endpoint if you render highlights yourself.)

---

### `DELETE /v1/games/{g}/{w}/{b}`

Delete a game (typically after it has ended).

- **Response** `200 OK` → `{ "status": "ok" }`. Deleting a non-existent game is a
  no-op and still returns `200`.
- **Errors:** `422 SQLIdError`, `401`.
- **Client behavior:** after deletion, the triple is free to be re-created fresh by a
  subsequent `POST /v1/games`.

---

### `GET /v1/games`

List the opponents a player currently has active games with, in a group.

- **Query params:** `player_id` (required), `group_id` (optional, default `0`).
- **Response** `200 OK`

  ```json
  { "opponents": [2, 5, 9] }
  ```

  The list is the ids of the other player in each of `player_id`'s games in that group
  (empty list if none).
- **Errors:** `422 SQLIdError`, `401`.
- **Client behavior:** use it to build a "your games" list. To then load a specific
  game you still need to know which side each player is; pair it with
  `GET /v1/games/{g}/exists`.

---

### `GET /v1/games/{g}/exists`

Look up whether a game exists between two players (in either color arrangement).

- **Query params:** `player1` (required), `player2` (required). `{g}` is the group.
- **Response** `200 OK`

  ```json
  { "game": { "white_id": 1, "black_id": 2 } }
  ```

  or, when there is no such game:

  ```json
  { "game": null }
  ```

- **Errors:** `422 SQLIdError`, `401`.
- **Client behavior:** the returned `white_id`/`black_id` tell you the color
  assignment, which is what you need to address the game's other routes.

---

### `POST /v1/challenges`

Issue a challenge — or accept a reciprocal one. Matchmaking runs entirely server-side
so concurrent challenges stay consistent.

- **Request body**

  ```json
  { "group_id": 10, "challenger": 100, "challenged": 200 }
  ```

- **Response** `200 OK`

  ```json
  { "accepted": false }
  ```

  - `accepted: false` — no reciprocal challenge existed, so a new pending challenge was
    created.
  - `accepted: true` — the challenged player had already challenged the challenger, so
    the challenge is mutually agreed (the pending challenge is consumed). *(This route
    does not itself create the game — create it with `POST /v1/games` using the agreed
    colors.)*
- **Errors:** `409 ChallengeError` — you challenged yourself, you already have a
  pending challenge to that player, or an unresolved game between the two already
  exists (`detail` explains which). Also `422 SQLIdError`, `401`.
- **Client behavior:** on `accepted: true`, proceed to open the game; on `false`, show
  "challenge sent"; on `409`, surface `detail`.

---

### `GET /v1/challenges/{g}/exists`

Check for a pending challenge between two players (in either direction).

- **Query params:** `player1` (required), `player2` (required).
- **Response** `200 OK`

  ```json
  { "challenge": { "challenger": 100, "challenged": 200 } }
  ```

  or `{ "challenge": null }` if none is pending.
- **Errors:** `422 SQLIdError`, `401`.

---

### `DELETE /v1/challenges`

Withdraw/cancel a pending challenge. Note this route takes a **request body** (some
HTTP tooling requires opting in to send a body on `DELETE`).

- **Request body**

  ```json
  { "group_id": 10, "challenger": 100, "challenged": 200 }
  ```

- **Response** `200 OK` → `{ "status": "ok" }` (no-op if nothing was pending).
- **Errors:** `422 SQLIdError`, `401`.

---

## How the chesssnake Python client interprets responses

The bundled Python client turns the raw HTTP contract above into ordinary Python
objects and exceptions, so you rarely touch JSON directly.

- **`ApiClient`** (`chesssnake.remote.client`) is a thin wrapper over a `requests`-style
  session. It prepends `/v1`, attaches `X-API-Key` when constructed with `api_key=`,
  and parses responses:
  - `get_or_create_game(...)` / `get_state(...)` → a `GameState` dataclass.
  - `move(...)` → a `MoveResult` dataclass.
  - `offer_draw` / `accept_draw` / `decline_draw` → a `GameState`.
  - `image(...)` → raw PNG `bytes`.
  - On any non-2xx response it reads `{error_type, detail}` and **re-raises the exact
    matching exception type** — the same `ChessError` subclasses the engine raises
    locally (e.g. `MoveIntoCheckError`) and the persistence `GameError` subclasses
    (e.g. `GameNotFoundError`, `ChallengeError`). So server-side and local errors look
    identical to your `except` clauses. A response without a recognized `error_type`
    (e.g. a `401` or a validation error) surfaces as a generic `GameError`.

- **`Game.remote(...)`** (`chesssnake.Game`) wraps `ApiClient` as a `Game`:
  - `move("e4")` calls the moves endpoint, mirrors the returned state into a local
    board (so `render()`, `to_move`, `is_over`, etc. work without another request), and
    returns a `MoveResult`. An illegal move raises the mapped `ChessError`.
  - `draw_offer/accept/decline(player_id)` call the draw endpoints and mirror the
    result.
  - `refresh()` re-fetches the state (use it to pick up the opponent's move).
  - Read state through the accessors: `to_move` (`Color`), `is_over`, `result`
    (`GameStatus`), `winner` (`Color | None`), `draw_offered_by` (`Color | None`).
  - `render()` / `save(path)` draw the mirrored board locally (the Python client has
    Pillow); you don't need the image endpoint unless you want the server to render.

A minimal remote session:

```python
from chesssnake import Game
from chesssnake.engine.errors import MoveIntoCheckError

game = Game.remote(1, 2, group_id=10, api_url="http://localhost:8000")  # api_key="..." if required
result = game.move("e4")          # MoveResult; already persisted server-side
print(result.from_square, result.to_square, game.to_move)

try:
    game.move("Ke2")              # illegal? the server decides
except MoveIntoCheckError as e:
    print("rejected:", e)

game.refresh()                    # pull the opponent's reply
```

---

## Building your own client

You do not need Python or the chess engine — just HTTP. A typical frontend:

1. **Open the game:** `POST /v1/games` with the triple → store the returned
   `GameState`.
2. **Render:** either draw `board` yourself (parse the [serialization](#board-serialization))
   or `GET …/image` and show the PNG.
3. **Submit a move:** `POST …/moves` with `{"move": "<algebraic>"}`.
   - `200` → replace your state with `result.state`; use `from`/`to` for highlights and
     `check` / `state.status` for check/checkmate messaging.
   - `4xx` with `error_type` → show `detail`; **keep your current state** (nothing
     changed on the server).
4. **See the opponent's move:** poll `GET /v1/games/{g}/{w}/{b}` and diff `turn` /
   `board` / `status` (there is no push/websocket channel).
5. **End states:** when `status` is `1` (checkmate) the side that just moved won (the
   opposite of `turn`); `2` is a draw. After that, moves return `GameOverError`.
6. **Draws & matchmaking:** use the `/draw/*` and `/challenges` routes as described
   above.
7. **Auth:** if the server requires it, send `X-API-Key` on every `/v1` request; expect
   `401` otherwise.

The golden rule: **treat the server's response as the truth.** Never advance your view
on a rejected request, and re-sync from the server whenever in doubt.
