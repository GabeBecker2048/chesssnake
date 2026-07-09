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
- [Player identity and versioning](#player-identity-and-versioning)
- [Generations and the game archive](#generations-and-the-game-archive)
- [Endpoints](#endpoints)
  - [Health](#get-health)
  - [Create or load a game](#post-v1games)
  - [Get a game's state](#get-v1gamesgwb)
  - [List past games (archive)](#get-v1gamesgwbarchive)
  - [Play a move](#post-v1gamesgwbmoves)
  - [Resign](#post-v1gamesgwbresign)
  - [Offer / accept / decline a draw](#post-v1gamesgwbdrawaction)
  - [List legal moves](#get-v1gamesgwblegal-moves)
  - [Move history](#get-v1gamesgwbhistory)
  - [Export PGN](#get-v1gamesgwbpgn)
  - [Get the FEN](#get-v1gamesgwbfen)
  - [Render the board as an image](#get-v1gamesgwbimage)
  - [Delete a game](#delete-v1gamesgwb)
  - [List a player's current games](#get-v1games)
  - [Check whether a game exists](#get-v1gamesgexists)
  - [Head-to-head record](#get-v1gamesgrecord)
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
| `fen` | string | The full position as standard [FEN](#fen) — placement, side to move, castling, en passant, and the move clocks. |
| `status` | integer | Outcome: `0` = in play, `1` = white won, `2` = black won, `3` = draw. |
| `version` | integer | Monotonic version, bumped on every state change (for [optimistic concurrency](#optimistic-concurrency)). |
| `generation` | integer | Which game between this triple this is (`1` = first; higher = a later rematch) — see [generations](#generations-and-the-game-archive). |
| `draw` | integer \| null | Who has an open draw offer: `0` = white, `1` = black, `null` = none. |
| `termination` | string \| null | Why a finished game ended (see [result model](#result-model)), or `null` while in play. |
| `wname` | string \| null | White's display name. |
| `bname` | string \| null | Black's display name. |

Example (after `1. e4`):

```json
{
  "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
  "status": 0,
  "version": 2,
  "generation": 1,
  "draw": null,
  "termination": null,
  "wname": "Bob",
  "bname": "Phil"
}
```

Whose turn it is comes from the FEN (the field after the placement: `w` or `b`).

### `MoveResult`

The outcome of a played move — the move itself plus the resulting `GameState`.
Returned only by [play a move](#post-v1gamesgwbmoves).

| Field | Type | Meaning |
|---|---|---|
| `state` | `GameState` | The full state **after** the move. |
| `from` | string | Origin square of the piece that moved, e.g. `"e2"`. |
| `to` | string | Destination square, e.g. `"e4"`. |
| `san` | string | The move as a postable string (e.g. `"e4"`, `"Nf3"`, `"exd5"`, `"e8Q"`, `"0-0"`, with a `+`/`#` suffix on check/mate). |
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
  "san": "e4",
  "check": false,
  "castle": null,
  "promotion": null,
  "en": false
}
```

### Result model

The game outcome is `state.status` plus `state.termination`:

- **`status`** — `0` in play, `1` white won, `2` black won, `3` draw. The game is
  over when `status != 0`; the winner (if any) is directly encoded (no need to infer
  it from whose turn it is).
- **`termination`** — *why* it ended: `"checkmate"`, `"resignation"`, `"stalemate"`,
  `"threefold_repetition"`, `"fifty_move_rule"`, `"insufficient_material"`, or
  `"agreement"`. It is `null` while the game is in play.

Draw-by-rule endings (stalemate, threefold, fifty-move, insufficient material) are
detected **automatically** by the server and end the game.

`check` in a `MoveResult` is true only for a *non-terminal* check (a checkmate is
`status` 1/2 with `termination` `"checkmate"`).

### Move notation

Moves are standard algebraic notation strings, exactly as the engine parses them:

- Pawn moves: `e4`, `d5`. Captures: `exd5`. Promotion: `e8Q`, `exd8Q` (piece letter
  appended, no `=`).
- Piece moves: `Nf3`, `Bb5`, `Qh4`, `Ke2`, `Ra1`. Captures: `Nxe5`.
- Disambiguation: `Rad1` (file), `R1a3` (rank), `Nbd2`.
- Castling: `0-0` (king-side) and `0-0-0` (queen-side). The letter-O forms `O-O` / `O-O-O`
  are accepted as equivalents; the engine emits the zero forms in `san`.
- A trailing `+` (check) or `#` (checkmate) is accepted but never required.

### FEN

The board is stored and transmitted as standard **Forsyth-Edwards Notation** — the
universal one-line encoding used across the chess ecosystem (Stockfish, python-chess,
board editors, opening databases, …). A FEN has six space-separated fields:

```
rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1
```

1. **Placement** — ranks 8→1 separated by `/`; each rank lists files a→h with piece
   letters (uppercase = white, lowercase = black) and digits for runs of empty squares.
2. **Active color** — `w` or `b` (whose turn it is).
3. **Castling availability** — any of `KQkq`, or `-`.
4. **En-passant target** — the square a pawn skipped (e.g. `e3`), or `-`.
5. **Halfmove clock** — plies since the last pawn move or capture (for the fifty-move rule).
6. **Fullmove number** — starts at 1, increments after Black moves.

Because it's standard FEN, any chess library or tool can render or analyze a
chesssnake position directly. You can also fetch it as plain text from
[`GET …/fen`](#get-v1gamesgwbfen).

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
| `403 Forbidden` | The supplied `player_id` isn't allowed to act (not their turn, or not in the game) | `NotYourTurnError` |
| `404 Not Found` | The referenced game does not exist | `GameNotFoundError` |
| `409 Conflict` | Stale `expected_version`, **or** an invalid challenge (self-challenge, duplicate, or a game already exists) | `VersionConflictError`, `ChallengeError` |
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
did not change anything. The action was rejected atomically.

---

## Player identity and versioning

Mutating routes (`/moves`, `/resign`, `/draw/*`) accept two optional controls.

### Player identity (`player_id`)

Pass the id of the player performing the action. The server validates it:

- for a **move**, `player_id` must be the side whose turn it is, else `403 NotYourTurnError`;
- for **resign / draw**, `player_id` must be a participant (`white_id` or `black_id`).

Omitting `player_id` on a move applies it for whichever side is to move (no check).
There is no per-player secret — this guards against acting for the wrong side, not
against a client that deliberately spoofs an id. Combine it with the service
[API key](#authentication) to gate access to the whole endpoint.

### Optimistic concurrency (`expected_version`)

Every `GameState` carries a `version` that increases on each change. Pass the
`version` you last saw as `expected_version`; if the game has moved on since, the
server rejects the action with `409 VersionConflictError` instead of applying it
against a newer position. This makes retries after a dropped response **safe**: a
retry that carries the now-stale version is refused rather than double-applied. On a
`409`, re-read the state (`GET …`) and decide whether to retry.

Even without `expected_version`, every action runs inside a `SELECT … FOR UPDATE`
transaction, so concurrent actions on one game are serialized and never corrupt each
other — versioning just lets the *client* detect that it was working from stale state.

---

## Generations and the game archive

A triple `(group_id, white_id, black_id)` can own **many** games over time — one per
**generation**. The *current* game is the one with the highest generation.

- `POST /v1/games` returns the current game if it's still in play, or — once the
  current game is **finished** — creates a **fresh** game at the next generation
  (so the same two players can rematch). Finished games are preserved.
- Mutations (`/moves`, `/resign`, `/draw/*`) always act on the current game.
- Read routes take an optional `?generation=N` to view a past (finished, read-only)
  game; the default is the current game. `GET …/archive` lists every generation.
- `GET /v1/games` (current games) and `GET …/exists` report **only active** games —
  so a finished game between two players no longer blocks a new challenge.

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

Open the **current** game for a triple: return it if one is in progress, create one
if none exists, or start a **new generation** if the current game is already
finished (see [generations](#generations-and-the-game-archive)). This is how a client
"opens" a game or starts a rematch.

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
  starting position, `status: 0`, `draw: null`, and its `generation` (1 for the first
  game between the triple, higher for a rematch after a finished game).
- **Errors:** `422 SQLIdError` if any id is out of BIGINT range; `401` if a key is
  required and missing.
- **Client behavior:** call this to obtain the current state, then drive the game with
  `/moves`. It never resets a game in progress; once a game **ends**, calling it again
  starts the next generation (the finished game stays in the [archive](#get-v1gamesgwbarchive)).

---

### `GET /v1/games/{g}/{w}/{b}`

Fetch a game's state without modifying it.

- **Query params:** `generation` (optional) — a past game to view; default = current.
- **Response** `200 OK` — a [`GameState`](#gamestate).
- **Errors:** `404 GameNotFoundError` if there is no such game (or generation);
  `422 SQLIdError`; `401`.
- **Client behavior:** use this to refresh — e.g. poll it to detect that the opponent
  has moved (compare `version`, `fen`, or `status`). Prefer this over re-`POST`ing
  `/v1/games` when you only want to read (it won't create/rematch as a side effect).

The `generation` query param is accepted the same way on `/legal-moves`, `/history`,
`/pgn`, `/fen`, `/image`, and `DELETE`.

---

### `GET /v1/games/{g}/{w}/{b}/archive`

List every game (generation) between the triple — the current game plus finished
ones — oldest first.

- **Response** `200 OK`

  ```json
  { "games": [
    { "generation": 1, "fen": "…", "status": 2, "termination": "checkmate", "updated_at": "2026-07-08T22:41:03" },
    { "generation": 2, "fen": "…", "status": 0, "termination": null, "updated_at": "2026-07-08T22:44:10" }
  ] }
  ```
- **Errors:** `422 SQLIdError`, `401`. (An empty `games` list if the triple has no games.)
- **Client behavior:** build a "past games" screen; fetch a specific one with
  `?generation=`.

---

### `POST /v1/games/{g}/{w}/{b}/moves`

Play a move. **The server validates and applies it** against the stored game and
persists the new state atomically.

- **Request body**

  | Field | Type | Required | Notes |
  |---|---|---|---|
  | `move` | string | yes | the move in algebraic notation (see [move notation](#move-notation)) |
  | `player_id` | integer | no | if given, must be the side to move (else `403`) — see [player identity](#player-identity-player_id) |
  | `expected_version` | integer | no | optimistic-concurrency guard (else `409`) — see [versioning](#optimistic-concurrency-expected_version) |

  ```json
  { "move": "e4", "player_id": 1, "expected_version": 1 }
  ```

- **Response** `200 OK` — a [`MoveResult`](#moveresult). By the time you receive it,
  the move is already stored server-side and `state.version` has increased.
- **Errors:**
  - `400` with an engine `error_type` if the move is illegal or malformed — e.g.
    `InvalidNotationError` (`"move": "xyz"`), `PieceNotFoundError` (`"move": "e5"` as
    white's first move), `MoveIntoCheckError`, `GameOverError` (the game already
    ended), etc. **Nothing is stored** when a move is rejected.
  - `403 NotYourTurnError` if `player_id` isn't the side to move;
    `409 VersionConflictError` if `expected_version` is stale.
  - `404 GameNotFoundError`, `422 SQLIdError`, `401`.

  Example rejection:

  ```json
  { "error_type": "InvalidNotationError", "detail": "\"xyz\" is not in valid algebraic notation" }
  ```

- **Client behavior:** on `200`, replace your view with `result.state`; use `from`/`to`
  (or `san`) to highlight the move and `check`/`state.status`/`state.termination` to
  show check/checkmate/draw. On an error, show `detail` and keep your current state.

---

### `POST /v1/games/{g}/{w}/{b}/resign`

Resign the game; the opponent wins.

- **Request body**: `{ "player_id": 2, "expected_version": 5 }` — `player_id` (the
  resigning participant) is required; `expected_version` is optional.
- **Response** `200 OK` — the resulting [`GameState`](#gamestate): `status` is the
  opponent's win (`1`/`2`) and `termination` is `"resignation"`.
- **Errors:** `400 GameOverError` (already ended); `403 NotYourTurnError` (not a
  participant); `409 VersionConflictError`; `404`, `422`, `401`.

---

### `POST /v1/games/{g}/{w}/{b}/draw/{action}`

Negotiate a draw. `{action}` is one of `offer`, `accept`, `decline`.

- **Request body**: `{ "player_id": 1, "expected_version": 3 }` — `player_id` (a
  participant) is required; `expected_version` is optional.

- **Semantics** (all enforced by the engine):
  - `offer` — record a draw offer from `player_id`. You may only offer on your own
    turn. If the *opponent* already had an offer outstanding, offering back **accepts**
    it (the game ends in a draw).
  - `accept` — accept the opponent's outstanding offer; the game ends in a draw
    (`status` becomes `3`, `termination` `"agreement"`).
  - `decline` — clear the opponent's outstanding offer; play continues (`draw` becomes
    `null`).
- **Response** `200 OK` — the resulting [`GameState`](#gamestate).
- **Errors:**
  - `400 DrawWrongTurnError` — offered a draw when it isn't your turn.
  - `400 DrawAlreadyOfferedError` — you already have an offer outstanding.
  - `400 DrawNotOfferedError` — accepted/declined with no offer to act on.
  - `400 GameOverError` — the game already ended.
  - `403 NotYourTurnError`, `409 VersionConflictError`, `404`, `422`, `401`.
- **Client behavior:** reflect the returned `draw`/`status`. When `status` becomes `3`,
  render "draw" and stop accepting moves.

---

### `GET /v1/games/{g}/{w}/{b}/legal-moves`

List every legal move in the current position — for highlighting destinations or
validating input before submitting.

- **Response** `200 OK`

  ```json
  { "moves": [ { "from": "e2", "to": "e4", "san": "e4", "promotion": null }, "..." ] }
  ```

  Each `san` is directly postable to [`/moves`](#post-v1gamesgwbmoves). For castling,
  `to` is `null` and `san` is `"0-0"`/`"0-0-0"` (the equivalent letter-O forms
  `"O-O"`/`"O-O-O"` are also accepted when posting a move). A finished game returns `[]`.
- **Errors:** `404 GameNotFoundError`, `422`, `401`.

---

### `GET /v1/games/{g}/{w}/{b}/history`

The moves played so far, in order.

- **Response** `200 OK` — `{ "moves": [ { "ply": 1, "san": "e4" }, { "ply": 2, "san": "e5" } ] }`.
- **Errors:** `404 GameNotFoundError`, `422`, `401`.

---

### `GET /v1/games/{g}/{w}/{b}/pgn`

The game as **PGN** (`text/plain`) — standard headers + movetext + result token,
ready to paste into any chess tool.

- **Response** `200 OK`, `Content-Type: text/plain`:

  ```
  [White "Alice"]
  [Black "Bob"]
  [Result "1-0"]
  [Termination "resignation"]

  1. e4 e5 2. Nf3 Nc6 1-0
  ```
- **Errors:** `404 GameNotFoundError`, `422`, `401`.

---

### `GET /v1/games/{g}/{w}/{b}/fen`

The current position as a [FEN](#fen) string (`text/plain`). The same value is also
in every JSON response as `state.fen`.

- **Response** `200 OK`, `Content-Type: text/plain`, e.g. `rnbqkbnr/... b KQkq e3 0 1`.
- **Errors:** `404 GameNotFoundError`, `422`, `401`.

---

### `GET /v1/games/{g}/{w}/{b}/image`

Render the board to a PNG **on the server**, so a frontend can display it without any
chess/rendering code of its own.

- **Query params:**
  - `perspective` (optional) — `white` or `black` for a **single board** from that
    side's point of view (board only, no names). Omit for the default **wide** image
    (both orientations side by side; the player-name strip is included only if the game
    has at least one name — a nameless game renders just the two boards).
  - `generation` (optional) — render a past game.
- **Response** `200 OK`, `Content-Type: image/png` — raw PNG bytes.
- **Errors:** `422` (bad `perspective` → request-validation error, or an out-of-range
  id → `SQLIdError`), `404 GameNotFoundError`, `401`. (Error bodies are JSON.)
- **Client behavior:** display/cache the bytes. The image reflects the latest stored
  position; request it again after a move to refresh.

---

### `DELETE /v1/games/{g}/{w}/{b}`

Delete a game and its moves.

- **Query params:** `generation` (optional) — a specific game to delete; default = the
  current game.
- **Response** `200 OK` → `{ "status": "ok" }` (no-op + `200` if nothing matched).
- **Errors:** `422 SQLIdError`, `401`.

---

### `GET /v1/games`

List the opponents a player has an **active** (in-play) game with, in a group.

- **Query params:** `player_id` (required), `group_id` (optional, default `0`).
- **Response** `200 OK`

  ```json
  { "opponents": [2, 5, 9] }
  ```

  Only games in progress count (finished games are excluded), so each opponent appears
  at most once.
- **Errors:** `422 SQLIdError`, `401`.
- **Client behavior:** use it to build an "ongoing games" list. To load a specific game
  you also need each player's color; pair it with `GET /v1/games/{g}/exists`. For
  *finished* games, use `GET …/archive`.

---

### `GET /v1/games/{g}/exists`

Look up whether an **active** game exists between two players (in either color
arrangement). Finished games don't count — so this returns `null` once a game ends,
which is what lets a rematch be challenged.

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

### `GET /v1/games/{g}/record`

The head-to-head win/draw/loss record between two players in a group, across all
**finished** games — every generation and **both color arrangements** (games where
either player had white). In-play games are excluded.

- **Query params:** `player1` (required), `player2` (required). `{g}` is the group.
- **Response** `200 OK`

  ```json
  { "player1": 1, "player2": 2, "player1_wins": 3, "player2_wins": 1, "draws": 2 }
  ```

  `player1_wins` is how many finished games `player1` won (whether as white or black);
  `player2_wins` likewise; `draws` counts drawn games. All zero if they've never
  finished a game. Swapping `player1`/`player2` just swaps the two win fields.
- **What counts:** a game contributes as soon as it has a result (`status != 0`). A win
  by **checkmate or resignation** counts as a win for that side; **every** kind of draw
  (agreement, stalemate, threefold repetition, fifty-move, insufficient material) counts
  as a draw — the `termination` reason doesn't matter. Only games **still in play** are
  excluded, so a game a player abandons mid-way never appears in the record.
- **Errors:** `422 SQLIdError`, `401`.

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
  - `get_or_create_game(...)` / `get_state(...)` → a `GameState`; `move(...)` → a
    `MoveResult`; `resign` / `offer_draw` / `accept_draw` / `decline_draw` →
    `GameState`; `legal_moves` / `history` → lists; `pgn` / `fen` → `str`;
    `image(...)` → raw PNG `bytes`.
  - On any non-2xx response it reads `{error_type, detail}` and **re-raises the exact
    matching exception type** — the same `ChessError` subclasses the engine raises
    locally (e.g. `MoveIntoCheckError`) and the persistence `GameError` subclasses
    (e.g. `GameNotFoundError`, `NotYourTurnError`, `VersionConflictError`). So
    server-side and local errors look identical to your `except` clauses. A response
    without a recognized `error_type` (e.g. a `401`) surfaces as a generic `GameError`.

- **`Game.remote(...)`** (`chesssnake.Game`) wraps `ApiClient` as a `Game`:
  - Construct with `player_id=` to have that player asserted on every action; the
    client also tracks `version` and sends it as `expected_version` automatically, so
    a retry after a dropped response is refused rather than double-applied.
  - `move("e4")` calls the moves endpoint, mirrors the returned state into a local
    board (so `render()`, `to_move`, `is_over`, `fen`, etc. work without another
    request), and returns a `MoveResult`. An illegal move raises the mapped `ChessError`.
  - `resign()`, `draw_offer/accept/decline()`, `legal_moves()`, `pgn()`, `history()`,
    `refresh()` map to the corresponding routes.
  - Read state through the accessors: `to_move` (`Color`), `is_over`, `result`
    (`GameStatus`), `winner` (`Color | None`), `termination` (`Termination | None`),
    `draw_offered_by` (`Color | None`).
  - `render()` / `save(path)` draw the mirrored board locally (the Python client has
    Pillow); you don't need the image endpoint unless you want the server to render.

The **local** engine (`Game.local(...)`) exposes the same features in-process
(`move`, `resign`, `legal_moves`, `pgn`, `fen`, auto draw-by-rule) — the client and
server run identical rules.

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
   `GameState` (keep its `version`).
2. **Render:** parse the [FEN](#fen) with any chess library, or `GET …/image` and show
   the PNG.
3. **Show options (optional):** `GET …/legal-moves` to highlight destinations; each
   `san` is directly postable.
4. **Submit a move:** `POST …/moves` with `{"move": "<algebraic>", "player_id": <me>,
   "expected_version": <last version>}`.
   - `200` → replace your state with `result.state` (note the new `version`); use
     `from`/`to`/`san` for highlights and `check` / `state.status` / `state.termination`
     for check/checkmate/draw messaging.
   - `4xx` with `error_type` → show `detail`; **keep your current state** (nothing
     changed on the server). On `409 VersionConflictError`, re-read and retry.
5. **See the opponent's move:** poll `GET /v1/games/{g}/{w}/{b}` and watch `version` /
   `fen` / `status` (there is no push/websocket channel).
6. **End states:** `status` `1`/`2` is a win for white/black, `3` a draw;
   `termination` says why. After the game ends, actions return `GameOverError`.
7. **Resign, draws, PGN, matchmaking:** use the `/resign`, `/draw/*`, `/pgn`, and
   `/challenges` routes.
8. **Auth:** if the server requires it, send `X-API-Key` on every `/v1` request; expect
   `401` otherwise.

The golden rule: **treat the server's response as the truth.** Never advance your view
on a rejected request, and re-sync from the server whenever in doubt.
