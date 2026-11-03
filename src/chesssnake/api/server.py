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

User, game and challenge routes are versioned under ``/v1``. Set
``api.require_auth`` to require an ``X-API-Key`` header on those routes
(``/health`` stays open). Players are users: create them with ``POST /v1/users``
(or get-or-create one by an external id with ``POST /v1/users/{provider}/{id}``)
before starting a game between them. Mutating game routes accept an optional
``player_id`` (validated → 403), ``expected_version`` (optimistic concurrency →
409) and ``generation`` (the game the client thinks it is in → 409 when that game
is over).
"""

import io
import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, model_validator

from ..config import Settings, resolve
from ..db import engine as db_engine
from ..db import errors, schema
from ..db import operations as ops
from ..dto import GameState, MoveResult, User
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
    white_id: int
    black_id: int

    @model_validator(mode="after")
    def _distinct_players(self):
        if self.white_id == self.black_id:
            raise ValueError("white_id and black_id must be different users")
        return self


class MoveBody(BaseModel):
    move: str
    player_id: int | None = None
    expected_version: int | None = None
    generation: int | None = None


class DrawBody(BaseModel):
    player_id: int
    expected_version: int | None = None
    generation: int | None = None


class ResignBody(BaseModel):
    player_id: int
    expected_version: int | None = None
    generation: int | None = None


class ChallengeBody(BaseModel):
    group_id: int = 0
    challenger: int
    challenged: int


class UsernameBody(BaseModel):
    # Validated by the database layer against USERNAME_RE, so a bad name is a
    # UserValidationError in the usual {error_type, detail} envelope rather
    # than pydantic's list-shaped 422.
    username: str


# --- Exception handlers ----------------------------------------------------


def _error(status_code, exc):
    return JSONResponse(status_code=status_code, content={"error_type": type(exc).__name__, "detail": str(exc)})


# Exception class -> HTTP status. Starlette resolves a raised exception by walking
# its MRO and taking the first registered class, so subclasses must be listed
# before the bases they refine (SQLIdError before SQLError before GameError).
_ERROR_STATUS = (
    (errors.SQLIdError, 422),
    (errors.UserValidationError, 422),
    (errors.ChallengeError, 409),
    (errors.GenerationConflictError, 409),
    (errors.VersionConflictError, 409),
    (errors.UserExistsError, 409),
    (errors.NotYourTurnError, 403),
    (errors.GameNotFoundError, 404),
    (errors.UserNotFoundError, 404),
    (errors.SQLBusyError, 503),
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


def _load_game(row, history=None):
    """
    Reconstruct an engine game from a stored game dict (+ optional loaded history).

    The database stores only the plies actually played, so the starting
    position's key is prepended here, where the engine that knows it lives.
    """
    state = GameState.from_row(row)
    if history is None:
        return game_from_state(state)
    return game_from_state(
        state,
        position_history=[_INITIAL_KEY, *history["position_keys"]],
        move_history=history["move_sans"],
    )


def _require_game(group_id, white_id, black_id, generation=None):
    """Fetch a game dict (current, or a specific ``generation``) or raise 404."""
    row = ops.game_get(group_id, white_id, black_id, generation)
    if row is None:
        detail = f"No game for group {group_id} between {white_id} and {black_id}"
        if generation is not None:
            detail += f" (generation {generation})"
        raise errors.GameNotFoundError(detail)
    return row


def _change(game, row, now, new_moves=(), result=None):
    """
    Describe what to persist after an engine action, and the state to return.

    A finished game carries an ``outcome``, which is what makes the database
    layer move it to the archive rather than update it in place.
    """
    state = state_from_game(
        game,
        int(row["version"]) + 1,
        int(row["generation"]),
        id=int(row["id"]),
        started_at=row["started_at"].isoformat(),
        updated_at=now.isoformat(),
    )
    outcome = None
    if game.is_over and game.termination is not None:
        outcome = (int(game.result), game.termination.value)
        # A finished game has no open draw offer (the engine leaves an accepted
        # one set), and the archive does not store one: return what is stored.
        state.draw = None
    return state, ops.GameChange(
        fen=state.fen,
        draw=state.draw,
        new_moves=list(new_moves),
        result=state if result is None else result,
        outcome=outcome,
    )


def _user(row, detail):
    if row is None:
        raise errors.UserNotFoundError(detail)
    return User.from_row(row).to_dict()


# --- Routes ----------------------------------------------------------------


health_router = APIRouter()


# Deliberately the one `async def` route. Everything else here does blocking work
# and runs in the threadpool, but this touches nothing, so leaving it on the event
# loop means it answers immediately even when every worker thread is busy. That is
# what stops a merely-busy server from being declared unhealthy: the container's
# HEALTHCHECK gives it a 2 second timeout, and before the threadpool move this
# route was measured at 325 ms while only eight board renders were in flight.
@health_router.get("/health")
async def health():
    return {"status": "ok"}


# Unversioned/open; the api-key dependency is attached per-app in create_app so
# the router itself stays reusable across apps with different settings.
v1 = APIRouter(prefix="/v1")


# --- Users ---


@v1.post("/users", status_code=201)
def create_user(body: UsernameBody):
    return User.from_row(ops.user_create(body.username)).to_dict()


@v1.get("/users")
def find_user(username: str):
    return _user(ops.user_get_by_name(username), f"No user named {username!r}")


@v1.get("/users/{user_id}")
def get_user(user_id: int):
    return _user(ops.user_get(user_id), f"No user with id {user_id}")


@v1.patch("/users/{user_id}")
def rename_user(user_id: int, body: UsernameBody):
    return User.from_row(ops.user_rename(user_id, body.username)).to_dict()


@v1.get("/users/{provider}/{external_id}")
def get_user_by_identity(provider: str, external_id: str):
    return _user(ops.identity_get(provider, external_id), f"No user is linked to {provider} id {external_id!r}")


# 200, not 201, like POST /v1/games: this is get-or-create, and most calls get.
@v1.post("/users/{provider}/{external_id}")
def get_or_create_user_by_identity(provider: str, external_id: str, body: UsernameBody):
    return User.from_row(ops.user_get_or_create_by_identity(provider, external_id, body.username)).to_dict()


@v1.put("/users/{user_id}/identities/{provider}/{external_id}")
def link_identity(user_id: int, provider: str, external_id: str):
    return User.from_row(ops.identity_link(user_id, provider, external_id)).to_dict()


# --- Games ---


@v1.post("/games")
def create_game(body: GameCreate):
    row = ops.game_get_or_create(body.group_id, body.white_id, body.black_id, INITIAL_FEN)
    return GameState.from_row(row).to_dict()


@v1.get("/games")
def list_current_games(player_id: int, group_id: int | None = None):
    return {"games": [GameState.from_row(row).to_dict() for row in ops.current_games(player_id, group_id)]}


# One segment, so it cannot be confused with the three-segment triple routes or
# the two-segment /games/{group_id}/exists and /record.
@v1.get("/games/{game_id}")
def get_game_by_id(game_id: int):
    row = ops.game_get_by_id(game_id)
    if row is None:
        raise errors.GameNotFoundError(f"No game with id {game_id}")
    return GameState.from_row(row).to_dict()


@v1.get("/games/{group_id}/{white_id}/{black_id}")
def get_game(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    return GameState.from_row(_require_game(group_id, white_id, black_id, generation)).to_dict()


@v1.get("/games/{group_id}/{white_id}/{black_id}/archive")
def game_archive(group_id: int, white_id: int, black_id: int):
    return {"games": [GameState.from_row(row).to_dict() for row in ops.game_archive(group_id, white_id, black_id)]}


@v1.post("/games/{group_id}/{white_id}/{black_id}/moves")
def play_move(group_id: int, white_id: int, black_id: int, body: MoveBody):
    def mutate(row, history, now):
        game = _load_game(row, history)
        if body.player_id is not None and not game.is_players_turn(body.player_id):
            raise errors.NotYourTurnError(f"It is not player {body.player_id}'s turn to move")
        m = game.move(body.move)  # runs the engine; raises ChessError on illegal input
        san = game.move_history[-1]
        ply = history["max_ply"] + 1
        state, change = _change(game, row, now, new_moves=[(ply, san, game.position_history[-1])])
        change.result = MoveResult(
            state=state,
            from_square=m.prev.c_notation,
            to_square=m.to.c_notation,
            san=san,
            check=game.board.check_for_check(game.turn),
            castle=m.castle,
            promotion=m.promotion,
            en=m.en,
        )
        return change

    return ops.apply_game_change(group_id, white_id, black_id, mutate, body.expected_version, body.generation).to_dict()


def _draw_or_resign(group_id, white_id, black_id, body, method):
    def mutate(row, history, now):
        game = _load_game(row, history)
        if body.player_id not in (white_id, black_id):
            raise errors.NotYourTurnError(f"Player {body.player_id} is not in this game")
        getattr(game, method)(body.player_id)  # draw_offer / draw_accept / draw_decline / resign
        return _change(game, row, now)[1]

    return ops.apply_game_change(group_id, white_id, black_id, mutate, body.expected_version, body.generation).to_dict()


@v1.post("/games/{group_id}/{white_id}/{black_id}/resign")
def resign(group_id: int, white_id: int, black_id: int, body: ResignBody):
    return _draw_or_resign(group_id, white_id, black_id, body, "resign")


@v1.post("/games/{group_id}/{white_id}/{black_id}/draw/offer")
def draw_offer(group_id: int, white_id: int, black_id: int, body: DrawBody):
    return _draw_or_resign(group_id, white_id, black_id, body, "draw_offer")


@v1.post("/games/{group_id}/{white_id}/{black_id}/draw/accept")
def draw_accept(group_id: int, white_id: int, black_id: int, body: DrawBody):
    return _draw_or_resign(group_id, white_id, black_id, body, "draw_accept")


@v1.post("/games/{group_id}/{white_id}/{black_id}/draw/decline")
def draw_decline(group_id: int, white_id: int, black_id: int, body: DrawBody):
    return _draw_or_resign(group_id, white_id, black_id, body, "draw_decline")


@v1.get("/games/{group_id}/{white_id}/{black_id}/legal-moves")
def legal_moves(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    row = _require_game(group_id, white_id, black_id, generation)
    return {"moves": _load_game(row).legal_moves()}


@v1.get("/games/{group_id}/{white_id}/{black_id}/history")
def history(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    row = _require_game(group_id, white_id, black_id, generation)
    return {"moves": ops.game_history(int(row["id"]))}


@v1.get("/games/{group_id}/{white_id}/{black_id}/pgn")
def pgn(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    row = _require_game(group_id, white_id, black_id, generation)
    game = _load_game(row)
    game.move_history = [m["san"] for m in ops.game_history(int(row["id"]))]
    return PlainTextResponse(game.pgn())


@v1.get("/games/{group_id}/{white_id}/{black_id}/fen")
def fen(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    return PlainTextResponse(GameState.from_row(_require_game(group_id, white_id, black_id, generation)).fen)


@v1.get("/games/{group_id}/{white_id}/{black_id}/image")
def game_image(
    group_id: int,
    white_id: int,
    black_id: int,
    generation: int | None = None,
    perspective: Literal["white", "black"] | None = None,
):
    row = _require_game(group_id, white_id, black_id, generation)
    buffer = io.BytesIO()
    _load_game(row).render(perspective=perspective).save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@v1.delete("/games/{group_id}/{white_id}/{black_id}")
def delete_game(group_id: int, white_id: int, black_id: int, generation: int | None = None):
    ops.game_delete(group_id, white_id, black_id, generation)
    return {"status": "ok"}


@v1.get("/games/{group_id}/exists")
def game_exists(group_id: int, player1: int, player2: int):
    row = ops.game_exists(player1, player2, group_id)
    return {"game": GameState.from_row(row).to_dict() if row is not None else None}


@v1.get("/games/{group_id}/record")
def game_record(group_id: int, player1: int, player2: int):
    return ops.game_record(player1, player2, group_id)


@v1.post("/challenges")
def post_challenge(body: ChallengeBody):
    return {"accepted": ops.challenge(body.challenger, body.challenged, body.group_id)}


@v1.get("/challenges/{group_id}/exists")
def challenge_exists(group_id: int, player1: int, player2: int):
    return {"challenge": ops.challenge_exists(player1, player2, group_id)}


@v1.delete("/challenges")
def delete_challenge(body: ChallengeBody):
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
            # An in-memory database gets a StaticPool, which hands the SAME
            # connection to every caller without serializing it. That was
            # survivable while every request ran on the event loop; now that the
            # routes run in a threadpool, two requests would issue BEGIN on one
            # connection and sqlite3 raises "cannot start a transaction within a
            # transaction". It is not worth supporting either way: an in-memory
            # database loses every game when the process restarts.
            if db_engine.is_memory_url(db_engine.parse_url(settings.database.url)):
                raise errors.SQLError(
                    "An in-memory SQLite database cannot be served: it is discarded when the "
                    "process exits, and it cannot handle concurrent requests.\n"
                    "  got:      "
                    f"{settings.database.url}\n"
                    "  expected: sqlite:///chesssnake.db          (a file, relative)\n"
                    "            sqlite:////var/lib/chesssnake/chesssnake.db   (a file, absolute)"
                )
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
