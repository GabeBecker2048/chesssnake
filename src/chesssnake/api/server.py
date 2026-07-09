"""
FastAPI application backing ``chesssnake api-endpoint``.

The server is authoritative: clients send **moves** (and draw actions), and the
server runs the chess engine to validate and apply them against the stored game,
persists the result, and returns the new state (or a structured error). This makes
the server the single source of truth for the rules and lets any frontend — in any
language — use the chess backend over REST without implementing chess itself.

Run it with ``chesssnake api-endpoint`` (see ``chesssnake.cli``), or point an ASGI
server at ``chesssnake.api.server:app``. Database credentials are read from the
``CHESSDB_*`` environment variables on startup; set ``CHESSSNAKE_INIT_DB=1`` to
also initialize the schema on startup.

Game/challenge routes are versioned under ``/v1``. Set ``CHESSSNAKE_API_KEY`` to
require an ``X-API-Key`` header on those routes (``/health`` stays open).
"""

import io
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..db import errors, sql
from ..db import postgres as ops
from ..dto import GameState, MoveResult
from ..engine import errors as chess_errors
from ..serialize import game_from_state, state_from_game

# Header carrying the optional API key.
API_KEY_HEADER = "X-API-Key"


@asynccontextmanager
async def lifespan(_app):
    # Initialize the connection pool from environment credentials (once).
    if sql.connection_pool is None:
        sql.initialize_connection_pool()
    if os.getenv("CHESSSNAKE_INIT_DB"):
        sql.psql_db_schema_init()
    yield


app = FastAPI(title="chesssnake api-endpoint", lifespan=lifespan)


# --- Auth ------------------------------------------------------------------


async def require_api_key(x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)):
    """Require a matching ``X-API-Key`` header iff ``CHESSSNAKE_API_KEY`` is set.

    Read per-request (not cached) so the key can be configured at deploy time and
    toggled without restarting. When unset, authentication is disabled.
    """
    configured = os.getenv("CHESSSNAKE_API_KEY")
    if configured and x_api_key != configured:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# --- Schemas ---------------------------------------------------------------
# Wire game state lives in chesssnake.dto (GameState/MoveResult). The request
# bodies below are server-only.


class GameCreate(BaseModel):
    group_id: int = 0
    white_id: int = 0
    black_id: int = 1
    white_name: str = ""
    black_name: str = ""


class MoveBody(BaseModel):
    move: str


class DrawBody(BaseModel):
    player_id: int


class ChallengeBody(BaseModel):
    group_id: int = 0
    challenger: int
    challenged: int


# --- Exception handlers ----------------------------------------------------
# Map domain errors to structured JSON so the client can re-raise the same types.


def _error(status_code, exc):
    return JSONResponse(
        status_code=status_code,
        content={"error_type": type(exc).__name__, "detail": str(exc)},
    )


@app.exception_handler(errors.SQLIdError)
async def _handle_id_error(_request, exc):
    return _error(422, exc)


@app.exception_handler(errors.ChallengeError)
async def _handle_challenge_error(_request, exc):
    return _error(409, exc)


@app.exception_handler(errors.GameNotFoundError)
async def _handle_not_found(_request, exc):
    return _error(404, exc)


@app.exception_handler(errors.SQLError)
async def _handle_sql_error(_request, exc):
    return _error(500, exc)


@app.exception_handler(errors.GameError)
async def _handle_game_error(_request, exc):
    return _error(400, exc)


@app.exception_handler(chess_errors.ChessError)
async def _handle_chess_error(_request, exc):
    # Illegal/invalid move or draw action — the client re-raises the matching type.
    return _error(400, exc)


# --- Routes ----------------------------------------------------------------


# /health is unversioned and unauthenticated (for liveness probes).
@app.get("/health")
async def health():
    return {"status": "ok"}


# Everything else is versioned under /v1 and gated by the (optional) API key.
v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@v1.post("/games")
async def create_game(body: GameCreate):
    row = ops.game_get_or_create(body.group_id, body.white_id, body.black_id, body.white_name, body.black_name)
    return GameState.from_row(row).to_dict()


@v1.get("/games/{group_id}/{white_id}/{black_id}")
async def get_game(group_id: int, white_id: int, black_id: int):
    row = ops.game_get(group_id, white_id, black_id)
    if row is None:
        raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
    return GameState.from_row(row).to_dict()


@v1.post("/games/{group_id}/{white_id}/{black_id}/moves")
async def play_move(group_id: int, white_id: int, black_id: int, body: MoveBody):
    def mutate(row):
        game = game_from_state(GameState.from_row(row), group_id, white_id, black_id)
        m = game.move(body.move)  # runs the engine; raises ChessError on illegal input
        new_state = state_from_game(game)
        result = MoveResult(
            state=new_state,
            from_square=m.prev.c_notation,
            to_square=m.to.c_notation,
            check=game.board.check_for_check(game.turn),
            castle=m.castle,
            promotion=m.promotion,
            en=m.en,
        )
        return new_state.to_dict(), result

    return ops.apply_game_change(group_id, white_id, black_id, mutate).to_dict()


def _draw_action(group_id, white_id, black_id, player_id, method):
    def mutate(row):
        game = game_from_state(GameState.from_row(row), group_id, white_id, black_id)
        getattr(game, method)(player_id)  # draw_offer / draw_accept / draw_decline
        new_state = state_from_game(game)
        return new_state.to_dict(), new_state

    return ops.apply_game_change(group_id, white_id, black_id, mutate).to_dict()


@v1.post("/games/{group_id}/{white_id}/{black_id}/draw/offer")
async def draw_offer(group_id: int, white_id: int, black_id: int, body: DrawBody):
    return _draw_action(group_id, white_id, black_id, body.player_id, "draw_offer")


@v1.post("/games/{group_id}/{white_id}/{black_id}/draw/accept")
async def draw_accept(group_id: int, white_id: int, black_id: int, body: DrawBody):
    return _draw_action(group_id, white_id, black_id, body.player_id, "draw_accept")


@v1.post("/games/{group_id}/{white_id}/{black_id}/draw/decline")
async def draw_decline(group_id: int, white_id: int, black_id: int, body: DrawBody):
    return _draw_action(group_id, white_id, black_id, body.player_id, "draw_decline")


@v1.get("/games/{group_id}/{white_id}/{black_id}/image")
async def game_image(group_id: int, white_id: int, black_id: int):
    row = ops.game_get(group_id, white_id, black_id)
    if row is None:
        raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
    game = game_from_state(GameState.from_row(row), group_id, white_id, black_id)
    buffer = io.BytesIO()
    game.render().save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@v1.delete("/games/{group_id}/{white_id}/{black_id}")
async def delete_game(group_id: int, white_id: int, black_id: int):
    ops.game_delete(group_id, white_id, black_id)
    return {"status": "ok"}


@v1.get("/games")
async def list_current_games(player_id: int, group_id: int = 0):
    return {"opponents": ops.current_games(player_id, group_id)}


@v1.get("/games/{group_id}/exists")
async def game_exists(group_id: int, player1: int, player2: int):
    return {"game": ops.game_exists(player1, player2, group_id)}


@v1.post("/challenges")
async def post_challenge(body: ChallengeBody):
    accepted = ops.challenge(body.challenger, body.challenged, body.group_id)
    return {"accepted": accepted}


@v1.get("/challenges/{group_id}/exists")
async def challenge_exists(group_id: int, player1: int, player2: int):
    return {"challenge": ops.challenge_exists(player1, player2, group_id)}


@v1.delete("/challenges")
async def delete_challenge(body: ChallengeBody):
    ops.challenge_delete(body.challenger, body.challenged, body.group_id)
    return {"status": "ok"}


app.include_router(v1)
