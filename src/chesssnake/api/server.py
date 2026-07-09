"""
FastAPI application backing ``chesssnake api-endpoint``.

The server is authoritative: clients send **moves** (and draw/resign actions), and
the server runs the chess engine to validate and apply them against the stored
game, persists the result, and returns the new state (or a structured error).

Run it with ``chesssnake api-endpoint`` (see ``chesssnake.cli``), or point an ASGI
server at ``chesssnake.api.server:app``. Database credentials are read from the
``CHESSDB_*`` environment variables on startup; set ``CHESSSNAKE_INIT_DB=1`` to
also initialize the schema on startup.

Game/challenge routes are versioned under ``/v1``. Set ``CHESSSNAKE_API_KEY`` to
require an ``X-API-Key`` header on those routes (``/health`` stays open).
Mutating routes accept an optional ``player_id`` (validated → 403) and an optional
``expected_version`` (optimistic concurrency → 409).
"""

import io
import os
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ..db import errors, sql
from ..db import postgres as ops
from ..dto import GameState, MoveResult
from ..engine import INITIAL_FEN, from_fen, position_key
from ..engine import errors as chess_errors
from ..serialize import game_from_state, state_from_game

API_KEY_HEADER = "X-API-Key"

# Precompute the starting position's repetition key (engine-derived) for new games.
_INITIAL_KEY = position_key(*from_fen(INITIAL_FEN))


@asynccontextmanager
async def lifespan(_app):
    if sql.connection_pool is None:
        sql.initialize_connection_pool()
    if os.getenv("CHESSSNAKE_INIT_DB"):
        sql.psql_db_schema_init()
    yield


app = FastAPI(title="chesssnake api-endpoint", lifespan=lifespan)


# --- Auth ------------------------------------------------------------------


async def require_api_key(x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)):
    """Require a matching ``X-API-Key`` header iff ``CHESSSNAKE_API_KEY`` is set."""
    configured = os.getenv("CHESSSNAKE_API_KEY")
    if configured and x_api_key != configured:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# --- Request bodies (game state lives in chesssnake.dto) -------------------


class GameCreate(BaseModel):
    group_id: int = 0
    white_id: int = 0
    black_id: int = 1
    white_name: str = ""
    black_name: str = ""


class MoveBody(BaseModel):
    move: str
    player_id: int | None = None
    expected_version: int | None = None


class DrawBody(BaseModel):
    player_id: int
    expected_version: int | None = None


class ResignBody(BaseModel):
    player_id: int
    expected_version: int | None = None


class ChallengeBody(BaseModel):
    group_id: int = 0
    challenger: int
    challenged: int


# --- Exception handlers ----------------------------------------------------


def _error(status_code, exc):
    return JSONResponse(status_code=status_code, content={"error_type": type(exc).__name__, "detail": str(exc)})


@app.exception_handler(errors.SQLIdError)
async def _handle_id_error(_request, exc):
    return _error(422, exc)


@app.exception_handler(errors.ChallengeError)
async def _handle_challenge_error(_request, exc):
    return _error(409, exc)


@app.exception_handler(errors.VersionConflictError)
async def _handle_version_conflict(_request, exc):
    return _error(409, exc)


@app.exception_handler(errors.NotYourTurnError)
async def _handle_not_your_turn(_request, exc):
    return _error(403, exc)


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
    return _error(400, exc)


# --- Helpers ---------------------------------------------------------------


def _load_game(group_id, white_id, black_id, row, history=None):
    """Reconstruct an engine game from a stored row (+ optional loaded history)."""
    state = GameState.from_row(row)
    kwargs = {}
    if history is not None:
        kwargs = {"position_history": history["position_keys"], "move_history": history["move_sans"]}
    return game_from_state(state, group_id, white_id, black_id, **kwargs)


def _columns(state: GameState) -> dict:
    return {"fen": state.fen, "draw": state.draw, "status": state.status, "termination": state.termination}


# --- Routes ----------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@v1.post("/games")
async def create_game(body: GameCreate):
    row = ops.game_get_or_create(
        body.group_id, body.white_id, body.black_id, INITIAL_FEN, _INITIAL_KEY, body.white_name, body.black_name
    )
    return GameState.from_row(row).to_dict()


@v1.get("/games/{group_id}/{white_id}/{black_id}")
async def get_game(group_id: int, white_id: int, black_id: int):
    row = ops.game_get(group_id, white_id, black_id)
    if row is None:
        raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
    return GameState.from_row(row).to_dict()


@v1.post("/games/{group_id}/{white_id}/{black_id}/moves")
async def play_move(group_id: int, white_id: int, black_id: int, body: MoveBody):
    def mutate(row, history):
        game = _load_game(group_id, white_id, black_id, row, history)
        if body.player_id is not None and not game.is_players_turn(body.player_id):
            raise errors.NotYourTurnError(f"It is not player {body.player_id}'s turn to move")
        m = game.move(body.move)  # runs the engine; raises ChessError on illegal input
        new_version = int(row["version"]) + 1
        new_state = state_from_game(game, new_version)
        san = game.move_history[-1]
        result = MoveResult(
            state=new_state,
            from_square=m.prev.c_notation,
            to_square=m.to.c_notation,
            san=san,
            check=game.board.check_for_check(game.turn),
            castle=m.castle,
            promotion=m.promotion,
            en=m.en,
        )
        new_move_rows = [{"ply": history["max_ply"] + 1, "san": san, "position_key": game.position_history[-1]}]
        return _columns(new_state), new_move_rows, result

    return ops.apply_game_change(group_id, white_id, black_id, mutate, body.expected_version).to_dict()


def _draw_or_resign(group_id, white_id, black_id, player_id, expected_version, method):
    def mutate(row, history):
        game = _load_game(group_id, white_id, black_id, row, history)
        if player_id not in (white_id, black_id):
            raise errors.NotYourTurnError(f"Player {player_id} is not in this game")
        getattr(game, method)(player_id)  # draw_offer / draw_accept / draw_decline / resign
        new_state = state_from_game(game, int(row["version"]) + 1)
        return _columns(new_state), [], new_state

    return ops.apply_game_change(group_id, white_id, black_id, mutate, expected_version).to_dict()


@v1.post("/games/{group_id}/{white_id}/{black_id}/resign")
async def resign(group_id: int, white_id: int, black_id: int, body: ResignBody):
    return _draw_or_resign(group_id, white_id, black_id, body.player_id, body.expected_version, "resign")


@v1.post("/games/{group_id}/{white_id}/{black_id}/draw/offer")
async def draw_offer(group_id: int, white_id: int, black_id: int, body: DrawBody):
    return _draw_or_resign(group_id, white_id, black_id, body.player_id, body.expected_version, "draw_offer")


@v1.post("/games/{group_id}/{white_id}/{black_id}/draw/accept")
async def draw_accept(group_id: int, white_id: int, black_id: int, body: DrawBody):
    return _draw_or_resign(group_id, white_id, black_id, body.player_id, body.expected_version, "draw_accept")


@v1.post("/games/{group_id}/{white_id}/{black_id}/draw/decline")
async def draw_decline(group_id: int, white_id: int, black_id: int, body: DrawBody):
    return _draw_or_resign(group_id, white_id, black_id, body.player_id, body.expected_version, "draw_decline")


@v1.get("/games/{group_id}/{white_id}/{black_id}/legal-moves")
async def legal_moves(group_id: int, white_id: int, black_id: int):
    row = ops.game_get(group_id, white_id, black_id)
    if row is None:
        raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
    return {"moves": _load_game(group_id, white_id, black_id, row).legal_moves()}


@v1.get("/games/{group_id}/{white_id}/{black_id}/history")
async def history(group_id: int, white_id: int, black_id: int):
    if ops.game_get(group_id, white_id, black_id) is None:
        raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
    return {"moves": ops.game_history(group_id, white_id, black_id)}


@v1.get("/games/{group_id}/{white_id}/{black_id}/pgn")
async def pgn(group_id: int, white_id: int, black_id: int):
    row = ops.game_get(group_id, white_id, black_id)
    if row is None:
        raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
    sans = [m["san"] for m in ops.game_history(group_id, white_id, black_id)]
    game = _load_game(group_id, white_id, black_id, row)
    game.move_history = sans
    return PlainTextResponse(game.pgn())


@v1.get("/games/{group_id}/{white_id}/{black_id}/fen")
async def fen(group_id: int, white_id: int, black_id: int):
    row = ops.game_get(group_id, white_id, black_id)
    if row is None:
        raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
    return PlainTextResponse(GameState.from_row(row).fen)


@v1.get("/games/{group_id}/{white_id}/{black_id}/image")
async def game_image(group_id: int, white_id: int, black_id: int):
    row = ops.game_get(group_id, white_id, black_id)
    if row is None:
        raise errors.GameNotFoundError(f"No game for group {group_id} between {white_id} and {black_id}")
    buffer = io.BytesIO()
    _load_game(group_id, white_id, black_id, row).render().save(buffer, format="PNG")
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
    return {"accepted": ops.challenge(body.challenger, body.challenged, body.group_id)}


@v1.get("/challenges/{group_id}/exists")
async def challenge_exists(group_id: int, player1: int, player2: int):
    return {"challenge": ops.challenge_exists(player1, player2, group_id)}


@v1.delete("/challenges")
async def delete_challenge(body: ChallengeBody):
    ops.challenge_delete(body.challenger, body.challenged, body.group_id)
    return {"status": "ok"}


app.include_router(v1)
