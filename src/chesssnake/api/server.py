"""
FastAPI application backing ``chesssnake api-endpoint``.

The server is authoritative: clients send **moves** (and draw/resign actions), and
the server runs the chess engine to validate and apply them against the stored
game, persists the result, and returns the new state (or a structured error).

Build it with :func:`create_app`, run it with ``chesssnake api-endpoint`` (see
``chesssnake.cli``), or point an ASGI server at
``chesssnake.api.server:create_app --factory`` (``:app`` also works). All settings
come from :mod:`chesssnake.config` — the config file, ``CHESSSNAKE__*``
environment variables, and command-line flags, in that order of precedence. Run
``chesssnake config show`` to see the effective values and where each came from.

Game/challenge routes are versioned under ``/v1``. Set ``api.require_auth`` to
require an ``X-API-Key`` header on those routes (``/health`` stays open).
Mutating routes accept an optional ``player_id`` (validated → 403) and an optional
``expected_version`` (optimistic concurrency → 409).
"""

import io
import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from ..config import Settings, resolve
from ..db import engine as db_engine
from ..db import errors, schema
from ..db import operations as ops
from ..dto import GameState, MoveResult
from ..engine import INITIAL_FEN, from_fen, position_key
from ..engine import errors as chess_errors
from ..serialize import game_from_state, state_from_game

API_KEY_HEADER = "X-API-Key"

logger = logging.getLogger(__name__)

# Precompute the starting position's repetition key (engine-derived) for new games.
_INITIAL_KEY = position_key(*from_fen(INITIAL_FEN))


# --- Auth ------------------------------------------------------------------


def _api_key_dependency(settings: Settings):
    """
    Build the ``/v1`` auth dependency for one app's settings.

    Whether a key is required is now an explicit setting rather than an inference
    from "is a key configured", so a deployment that meant to enable auth but
    failed to inject the secret is rejected at startup by
    :class:`~chesssnake.config.Settings` validation instead of quietly serving
    unauthenticated traffic.
    """

    async def require_api_key(x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)):
        if settings.api.require_auth and x_api_key != settings.api.api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

    return require_api_key


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


# Exception class -> HTTP status. Starlette resolves a raised exception by walking
# its MRO and taking the first registered class, so subclasses must be listed
# before the bases they refine (SQLIdError before SQLError before GameError).
_ERROR_STATUS = (
    (errors.SQLIdError, 422),
    (errors.ChallengeError, 409),
    (errors.VersionConflictError, 409),
    (errors.NotYourTurnError, 403),
    (errors.GameNotFoundError, 404),
    (errors.SQLError, 500),
    (errors.GameError, 400),
    (chess_errors.ChessError, 400),
)


def _register_error_handlers(app: FastAPI) -> None:
    for exc_type, status_code in _ERROR_STATUS:

        async def handler(_request, exc, _status=status_code):
            return _error(_status, exc)

        app.add_exception_handler(exc_type, handler)

    async def unauthorized(_request, exc):
        # Match the {error_type, detail} envelope every other error uses, so the
        # client's error mapping (remote/client.py:_raise) sees a real type
        # instead of falling back to a bare GameError.
        if exc.status_code == 401:
            return JSONResponse(status_code=401, content={"error_type": "AuthError", "detail": str(exc.detail)})
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    app.add_exception_handler(HTTPException, unauthorized)


# --- Helpers ---------------------------------------------------------------


def _load_game(group_id, white_id, black_id, row, history=None):
    """Reconstruct an engine game from a stored row (+ optional loaded history)."""
    state = GameState.from_row(row)
    kwargs = {}
    if history is not None:
        kwargs = {"position_history": history["position_keys"], "move_history": history["move_sans"]}
    return game_from_state(state, group_id, white_id, black_id, **kwargs)


def _require_game(group_id, white_id, black_id, generation=None):
    """Fetch a game row (current, or a specific ``generation``) or raise 404."""
    row = ops.game_get(group_id, white_id, black_id, generation)
    if row is None:
        detail = f"No game for group {group_id} between {white_id} and {black_id}"
        if generation is not None:
            detail += f" (generation {generation})"
        raise errors.GameNotFoundError(detail)
    return row


def _columns(state: GameState) -> dict:
    return {"fen": state.fen, "draw": state.draw, "status": state.status, "termination": state.termination}


# --- Routes ----------------------------------------------------------------


health_router = APIRouter()


@health_router.get("/health")
async def health():
    return {"status": "ok"}


# Unversioned/open; the api-key dependency is attached per-app in create_app so
# the router itself stays reusable across apps with different settings.
v1 = APIRouter(prefix="/v1")


@v1.post("/games")
async def create_game(body: GameCreate):
    row = ops.game_get_or_create(
        body.group_id, body.white_id, body.black_id, INITIAL_FEN, _INITIAL_KEY, body.white_name, body.black_name
    )
    return GameState.from_row(row).to_dict()


@v1.get("/games/{group_id}/{white_id}/{black_id}")
async def get_game(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    return GameState.from_row(_require_game(group_id, white_id, black_id, generation)).to_dict()


@v1.get("/games/{group_id}/{white_id}/{black_id}/archive")
async def game_archive(group_id: int, white_id: int, black_id: int):
    return {"games": ops.game_archive(group_id, white_id, black_id)}


@v1.post("/games/{group_id}/{white_id}/{black_id}/moves")
async def play_move(group_id: int, white_id: int, black_id: int, body: MoveBody):
    def mutate(row, history):
        game = _load_game(group_id, white_id, black_id, row, history)
        if body.player_id is not None and not game.is_players_turn(body.player_id):
            raise errors.NotYourTurnError(f"It is not player {body.player_id}'s turn to move")
        m = game.move(body.move)  # runs the engine; raises ChessError on illegal input
        new_state = state_from_game(game, int(row["version"]) + 1, int(row["generation"]))
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
        new_state = state_from_game(game, int(row["version"]) + 1, int(row["generation"]))
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
async def legal_moves(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    row = _require_game(group_id, white_id, black_id, generation)
    return {"moves": _load_game(group_id, white_id, black_id, row).legal_moves()}


@v1.get("/games/{group_id}/{white_id}/{black_id}/history")
async def history(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    row = _require_game(group_id, white_id, black_id, generation)
    return {"moves": ops.game_history(group_id, white_id, black_id, int(row["generation"]))}


@v1.get("/games/{group_id}/{white_id}/{black_id}/pgn")
async def pgn(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    row = _require_game(group_id, white_id, black_id, generation)
    game = _load_game(group_id, white_id, black_id, row)
    game.move_history = [m["san"] for m in ops.game_history(group_id, white_id, black_id, int(row["generation"]))]
    return PlainTextResponse(game.pgn())


@v1.get("/games/{group_id}/{white_id}/{black_id}/fen")
async def fen(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    return PlainTextResponse(GameState.from_row(_require_game(group_id, white_id, black_id, generation)).fen)


@v1.get("/games/{group_id}/{white_id}/{black_id}/image")
async def game_image(
    group_id: int,
    white_id: int,
    black_id: int,
    generation: int | None = None,
    perspective: Literal["white", "black"] | None = None,
):
    row = _require_game(group_id, white_id, black_id, generation)
    buffer = io.BytesIO()
    _load_game(group_id, white_id, black_id, row).render(perspective=perspective).save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@v1.delete("/games/{group_id}/{white_id}/{black_id}")
async def delete_game(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    ops.game_delete(group_id, white_id, black_id, generation)
    return {"status": "ok"}


@v1.get("/games")
async def list_current_games(player_id: int, group_id: int = 0):
    return {"opponents": ops.current_games(player_id, group_id)}


@v1.get("/games/{group_id}/exists")
async def game_exists(group_id: int, player1: int, player2: int):
    return {"game": ops.game_exists(player1, player2, group_id)}


@v1.get("/games/{group_id}/record")
async def game_record(group_id: int, player1: int, player2: int):
    return ops.game_record(player1, player2, group_id)


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


# --- Application factory ---------------------------------------------------


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Build the api-endpoint application.

    :param settings: Resolved configuration. When omitted, it is resolved from the
        config file and environment — which is what makes this a valid zero-argument
        ASGI factory (``uvicorn chesssnake.api.server:create_app --factory``).
    :type settings: chesssnake.config.Settings or None
    :return: A configured FastAPI application.
    :rtype: fastapi.FastAPI
    """
    settings = settings or resolve()
    for note in settings.advisories():
        logger.warning("%s", note)

    @asynccontextmanager
    async def lifespan(_app):
        # The guard keeps a second app in the same process (as the tests build)
        # from replacing a working engine; its database settings are ignored.
        owns_engine = db_engine.current_engine() is None
        if owns_engine:
            engine = db_engine.initialize_engine(
                settings.database.url,
                pool_min_size=settings.database.pool_min_size,
                pool_max_size=settings.database.pool_max_size,
                sqlite_busy_timeout=settings.database.sqlite_busy_timeout,
            )
            if settings.database.init_schema:
                schema.create_all(engine)
        try:
            yield
        finally:
            # Only the app that created the engine disposes it, so a second app
            # shutting down cannot pull the connection pool out from under the first.
            if owns_engine:
                db_engine.dispose_engine()

    app = FastAPI(title="chesssnake api-endpoint", lifespan=lifespan)
    app.state.settings = settings
    _register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(v1, dependencies=[Depends(_api_key_dependency(settings))])
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """
    Resolve ``chesssnake.api.server:app`` lazily (PEP 562).

    Keeps the traditional ASGI import string working without resolving
    configuration merely because someone imported this module — which would make
    the module unimportable whenever the config is invalid.
    """
    if name == "app":
        global _app
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
