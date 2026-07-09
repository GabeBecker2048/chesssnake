"""
FastAPI application backing ``chesssnake api-endpoint``.

This is a thin persistence layer: it stores and retrieves serialized game state
in PostgreSQL. The chess engine runs on the client, so this server never imports
the ``engine`` — it only moves strings and ids in and out of the database.

Run it with ``chesssnake api-endpoint`` (see ``chesssnake.cli``), or point an ASGI
server at ``chesssnake.api.server:app``. Database credentials are read from the
``CHESSDB_*`` environment variables on startup; set ``CHESSSNAKE_INIT_DB=1`` to
also initialize the schema on startup.

Game/challenge routes are versioned under ``/v1``. Set ``CHESSSNAKE_API_KEY`` to
require an ``X-API-Key`` header on those routes (``/health`` stays open).
"""

import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..db import errors, sql
from ..db import postgres as ops
from ..dto import GameState

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
# The game-state wire shape lives in chesssnake.dto.GameState (shared with the
# client). The small request bodies below are server-only.


class GameCreate(BaseModel):
    group_id: int = 0
    white_id: int = 0
    black_id: int = 1
    white_name: str = ""
    black_name: str = ""


class DrawUpdate(BaseModel):
    draw: int | None = None
    status: int = 0


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


@app.exception_handler(errors.SQLError)
async def _handle_sql_error(_request, exc):
    return _error(500, exc)


@app.exception_handler(errors.GameError)
async def _handle_game_error(_request, exc):
    return _error(400, exc)


# --- Routes ----------------------------------------------------------------


# /health is unversioned and unauthenticated (for liveness probes).
@app.get("/health")
async def health():
    return {"status": "ok"}


# Everything else is versioned under /v1 and gated by the (optional) API key.
v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@v1.post("/games", response_model=GameState)
async def create_game(body: GameCreate):
    row = ops.game_get_or_create(body.group_id, body.white_id, body.black_id, body.white_name, body.black_name)
    return GameState.from_row(row)


@v1.put("/games/{group_id}/{white_id}/{black_id}")
async def update_game(group_id: int, white_id: int, black_id: int, state: GameState):
    ops.game_update(
        group_id,
        white_id,
        black_id,
        state.board,
        state.turn,
        state.pawnmove,
        state.draw,
        state.moved,
        state.status,
        state.wname,
        state.bname,
    )
    return {"status": "ok"}


@v1.patch("/games/{group_id}/{white_id}/{black_id}/draw")
async def patch_draw(group_id: int, white_id: int, black_id: int, body: DrawUpdate):
    ops.game_update_draw(group_id, white_id, black_id, body.draw, body.status)
    return {"status": "ok"}


@v1.delete("/games/{group_id}/{white_id}/{black_id}/draw")
async def clear_draw(group_id: int, white_id: int, black_id: int):
    ops.game_clear_draw(group_id, white_id, black_id)
    return {"status": "ok"}


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
