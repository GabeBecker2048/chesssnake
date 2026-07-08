"""
FastAPI application backing ``chesssnake api-endpoint``.

This is a thin persistence layer: it stores and retrieves serialized game state
in PostgreSQL. The chess engine runs on the client, so this server never imports
``chesslib`` — it only moves strings and ids in and out of the database.

Run it with ``chesssnake api-endpoint`` (see ``chesssnake.cli``), or point an ASGI
server at ``chesssnake.api.server:app``. Database credentials are read from the
``CHESSDB_*`` environment variables on startup; set ``CHESSSNAKE_INIT_DB=1`` to
also initialize the schema on startup.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..postgres import operations as ops
from ..postgres import GameError, PSql_Utils


@asynccontextmanager
async def lifespan(_app):
    # Initialize the connection pool from environment credentials (once).
    if PSql_Utils.connection_pool is None:
        PSql_Utils.initialize_connection_pool()
    if os.getenv("CHESSSNAKE_INIT_DB"):
        PSql_Utils.psql_db_schema_init()
    yield


app = FastAPI(title="chesssnake api-endpoint", lifespan=lifespan)


# --- Schemas ---------------------------------------------------------------

class GameCreate(BaseModel):
    group_id: int = 0
    white_id: int = 0
    black_id: int = 1
    white_name: str = ""
    black_name: str = ""


class GameState(BaseModel):
    board: str
    turn: int
    pawnmove: str | None = None
    draw: int | None = None
    moved: str
    status: int
    wname: str | None = None
    bname: str | None = None


class DrawUpdate(BaseModel):
    draw: int | None = None
    status: int = 0


class ChallengeBody(BaseModel):
    group_id: int = 0
    challenger: int
    challenged: int


def _state(row):
    """Project a raw Games row into the client-facing state payload."""
    return {
        "board": row["board"],
        "turn": int(row["turn"]),
        "pawnmove": row["pawnmove"].strip() if row["pawnmove"] is not None else None,
        "draw": int(row["draw"]) if row["draw"] is not None else None,
        "moved": row["moved"],
        "status": int(row["status"]),
        "wname": row["wname"],
        "bname": row["bname"],
    }


# --- Exception handlers ----------------------------------------------------
# Map domain errors to structured JSON so the client can re-raise the same types.

def _error(status_code, exc):
    return JSONResponse(
        status_code=status_code,
        content={"error_type": type(exc).__name__, "detail": str(exc)},
    )


@app.exception_handler(GameError.SQLIdError)
async def _handle_id_error(_request, exc):
    return _error(422, exc)


@app.exception_handler(GameError.ChallengeError)
async def _handle_challenge_error(_request, exc):
    return _error(409, exc)


@app.exception_handler(GameError.SQLError)
async def _handle_sql_error(_request, exc):
    return _error(500, exc)


@app.exception_handler(GameError.GameError)
async def _handle_game_error(_request, exc):
    return _error(400, exc)


# --- Routes ----------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/games")
async def create_game(body: GameCreate):
    row = ops.game_get_or_create(
        body.group_id, body.white_id, body.black_id, body.white_name, body.black_name
    )
    return _state(row)


@app.put("/games/{group_id}/{white_id}/{black_id}")
async def update_game(group_id: int, white_id: int, black_id: int, state: GameState):
    ops.game_update(
        group_id, white_id, black_id,
        state.board, state.turn, state.pawnmove, state.draw,
        state.moved, state.status, state.wname, state.bname,
    )
    return {"status": "ok"}


@app.patch("/games/{group_id}/{white_id}/{black_id}/draw")
async def patch_draw(group_id: int, white_id: int, black_id: int, body: DrawUpdate):
    ops.game_update_draw(group_id, white_id, black_id, body.draw, body.status)
    return {"status": "ok"}


@app.delete("/games/{group_id}/{white_id}/{black_id}/draw")
async def clear_draw(group_id: int, white_id: int, black_id: int):
    ops.game_clear_draw(group_id, white_id, black_id)
    return {"status": "ok"}


@app.delete("/games/{group_id}/{white_id}/{black_id}")
async def delete_game(group_id: int, white_id: int, black_id: int):
    ops.game_delete(group_id, white_id, black_id)
    return {"status": "ok"}


@app.get("/games")
async def list_current_games(player_id: int, group_id: int = 0):
    return {"opponents": ops.current_games(player_id, group_id)}


@app.get("/games/{group_id}/exists")
async def game_exists(group_id: int, player1: int, player2: int):
    return {"game": ops.game_exists(player1, player2, group_id)}


@app.post("/challenges")
async def post_challenge(body: ChallengeBody):
    accepted = ops.challenge(body.challenger, body.challenged, body.group_id)
    return {"accepted": accepted}


@app.get("/challenges/{group_id}/exists")
async def challenge_exists(group_id: int, player1: int, player2: int):
    return {"challenge": ops.challenge_exists(player1, player2, group_id)}


@app.delete("/challenges")
async def delete_challenge(body: ChallengeBody):
    ops.challenge_delete(body.challenger, body.challenged, body.group_id)
    return {"status": "ok"}
