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

Everything under ``/v1`` needs ``Authorization: Bearer <token>`` except
``/v1/auth/login``, ``/v1/auth/register`` and ``/v1/info`` (see
:mod:`chesssnake.api.auth`); ``/health`` is unversioned and open, and so is the web
UI at ``/`` (:mod:`chesssnake.api.web`), whose page is only a client of ``/v1``. Players are users; games are normally created
by one user challenging another and the challenge being accepted, and every game
is addressed by its id. An administrator can create games directly, manage
accounts, and act for any player by passing ``player_id``.
"""

import io
import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, model_validator

from ..config import Settings, resolve
from ..db import engine as db_engine
from ..db import errors, schema
from ..db import operations as ops
from ..dto import COLORS, ROLES, Challenge, GameState, LoginResult, MoveResult, TokenInfo, User
from ..engine import INITIAL_FEN, Board
from ..engine import Game as EngineGame
from ..engine import errors as chess_errors
from ..serialize import game_from_state, state_from_game
from .auth import (
    Principal,
    acting_as,
    check_current_password,
    current_principal,
    hash_password,
    login,
    require_admin,
    validate_password,
)
from .realtime import Broker, InProcessBroker, websocket_endpoint
from .web import add_web_routes

logger = logging.getLogger(__name__)

# Precompute the starting position's repetition key (engine-derived) for new games.
_INITIAL_KEY = EngineGame().position_history[0]  # the starting position's repetition key

#: Longest name an api token may be given.
TOKEN_NAME_MAX = 64
#: Longest lifetime an api token may be given, in days (about ten years).
TOKEN_LIFETIME_MAX_DAYS = 3650


# --- Request bodies (responses live in chesssnake.dto) ---------------------
#
# Usernames, passwords and other free-text fields are validated by the database
# and auth layers rather than by pydantic, so a bad value is reported in the
# usual {error_type, detail} envelope instead of pydantic's list-shaped 422.


class Credentials(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class TokenCreate(BaseModel):
    name: str
    current_password: str
    expires_in_days: int | None = None


class UserCreate(BaseModel):
    username: str
    password: str | None = None
    role: Literal["user", "admin"] = "user"


class UserPatch(BaseModel):
    username: str | None = None
    role: Literal["user", "admin"] | None = None
    disabled: bool | None = None
    password: str | None = None


class UsernameBody(BaseModel):
    username: str


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


class ActionBody(BaseModel):
    player_id: int | None = None
    expected_version: int | None = None


class ChallengeCreate(BaseModel):
    opponent_id: int
    group_id: int = 0
    color: Literal["white", "black", "random"] = "random"
    player_id: int | None = None


class ChallengeAccept(BaseModel):
    player_id: int | None = None


# --- Exception handlers ----------------------------------------------------


def _error(status_code, exc, headers=None):
    return JSONResponse(
        status_code=status_code,
        content={"error_type": type(exc).__name__, "detail": str(exc)},
        headers=headers,
    )


# Exception class -> HTTP status. Starlette resolves a raised exception by walking
# its MRO and taking the first registered class, so subclasses must be listed
# before the bases they refine (SQLIdError before SQLError before GameError).
_ERROR_STATUS = (
    (errors.AuthError, 401),
    (errors.ForbiddenError, 403),
    (errors.SQLIdError, 422),
    (errors.UserValidationError, 422),
    (errors.ChallengeError, 409),
    (errors.VersionConflictError, 409),
    (errors.UserExistsError, 409),
    (errors.NotYourTurnError, 403),
    (errors.GameNotFoundError, 404),
    (errors.UserNotFoundError, 404),
    (errors.ChallengeNotFoundError, 404),
    (errors.TokenNotFoundError, 404),
    (errors.SQLBusyError, 503),
    (errors.SQLError, 500),
    (errors.GameError, 400),
    (chess_errors.ChessError, 400),
)


def _register_error_handlers(app: FastAPI) -> None:
    for exc_type, status_code in _ERROR_STATUS:
        # RFC 9110: a 401 says how to authenticate.
        headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None

        async def handler(_request, exc, _status=status_code, _headers=headers):
            return _error(_status, exc, _headers)

        app.add_exception_handler(exc_type, handler)


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


def _require_game(game_id: int):
    row = ops.game_get_by_id(game_id)
    if row is None:
        raise errors.GameNotFoundError(f"No game with id {game_id}")
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


def _user_out(row, me: Principal) -> dict:
    """A user for the wire. Linked external ids are shown only to that user and admins."""
    return User.from_row(row, show_identities=me.is_admin or int(row["id"]) == me.user_id).to_dict()


def _require_user(row, detail):
    if row is None:
        raise errors.UserNotFoundError(detail)
    return row


def _game_actor(me: Principal, player_id, row, *, require_actor):
    """
    The player an action in this game is performed as (see :func:`acting_as`).

    ``None`` only for an administrator who is not playing and named nobody: the
    move is then made for the side to move.

    :raises errors.NotYourTurnError: If the actor is not one of the players.
    """
    players = (int(row["white_id"]), int(row["black_id"]))
    actor = acting_as(me, player_id, participants=players, require_actor=require_actor)
    if actor is not None and actor not in players:
        raise errors.NotYourTurnError(f"Player {actor} is not in this game")
    return actor


def _require_challenge(challenge_id: int, me: Principal):
    """The challenge, if it exists and the caller is in it (or an admin); else 404."""
    challenge = ops.challenge_get(challenge_id)
    if challenge is None or not (me.is_admin or me.user_id in (challenge["challenger_id"], challenge["challenged_id"])):
        raise errors.ChallengeNotFoundError(f"No pending challenge {challenge_id}")
    return challenge


def _broker(request: Request) -> Broker:
    """
    This app's broker. Publishing goes through the request rather than a module
    global because the router is shared by every app built in a process.
    """
    return getattr(request.app.state, "broker", None) or Broker()


def _move_summary(result: MoveResult) -> dict:
    return {"san": result.san, "from": result.from_square, "to": result.to_square, "check": result.check}


def _login_result(raw, token, user=None):
    return LoginResult(
        token=raw,
        token_info=TokenInfo.from_row(token),
        user=User.from_row(user) if user is not None else None,
    ).to_dict()


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


def _public_router(settings: Settings) -> APIRouter:
    """
    The only /v1 routes reachable without a token.

    Built per app because they read that app's settings, and included on the app
    directly, NOT into `v1`: a router included into `v1` inherits its auth
    dependency.
    """
    public = APIRouter(prefix="/v1")

    @public.get("/info")
    def server_info():
        # What a client needs to know before it has an account: whether it can
        # make one, and whether to try the websocket or go straight to polling.
        return {
            "version": _version(),
            "registration": settings.api.registration,
            "websocket": settings.websocket.enabled,
        }

    @public.post("/auth/register", status_code=201)
    def register(body: Credentials):
        if settings.api.registration != "open":
            raise errors.ForbiddenError("Registration is closed; ask an administrator for an account")
        ops.validate_username(body.username)
        password_hash = hash_password(body.password)  # validates; outside any transaction
        user = ops.user_create(body.username, ops.ROLE_USER, password_hash)
        raw, token = ops.token_create(
            user["id"], ops.TOKEN_SESSION, name="login", lifetime_days=settings.api.session_lifetime_days
        )
        return _login_result(raw, token, user)

    @public.post("/auth/login")
    def log_in(body: Credentials):
        raw, token, user = login(body.username, body.password, settings.api.session_lifetime_days)
        return _login_result(raw, token, user)

    return public


# Everything here needs a token. The router-level dependency is the guarantee that
# no route can forget it; routes that need to know *who* also declare `me`, and
# FastAPI resolves the dependency once per request either way.
v1 = APIRouter(prefix="/v1", dependencies=[Depends(current_principal)])


# --- Account ---


@v1.post("/auth/logout", status_code=204)
def log_out(request: Request, me: Principal = Depends(current_principal)):
    ops.token_delete(me.token_id)
    _broker(request).recheck_token(me.token_id)  # its websockets close now, not at the next re-check
    return Response(status_code=204)


@v1.get("/auth/me")
def whoami(me: Principal = Depends(current_principal)):
    return _user_out(_require_user(ops.user_get(me.user_id), "Your account no longer exists"), me)


@v1.post("/auth/password", status_code=204)
def change_password(request: Request, body: PasswordChange, me: Principal = Depends(current_principal)):
    validate_password(body.new_password)
    stored = check_current_password(me, body.current_password)
    new_hash = hash_password(body.new_password)
    # Ends the user's other login sessions but keeps this one and their api
    # tokens: those are separate credentials, and a bot should not die because
    # its owner changed a password.
    ops.user_set_password(me.user_id, new_hash, revoke="sessions", keep_token_id=me.token_id, expected_hash=stored)
    _broker(request).recheck_user(me.user_id)
    return Response(status_code=204)


@v1.post("/auth/tokens", status_code=201)
def create_token(body: TokenCreate, me: Principal = Depends(current_principal)):
    name = body.name.strip()
    if not (1 <= len(name) <= TOKEN_NAME_MAX):
        raise errors.UserValidationError(f"A token name must be 1 to {TOKEN_NAME_MAX} characters")
    days = body.expires_in_days
    if days is not None and not (1 <= days <= TOKEN_LIFETIME_MAX_DAYS):
        raise errors.UserValidationError(f"expires_in_days must be 1 to {TOKEN_LIFETIME_MAX_DAYS}")
    # Re-asking for the password means a stolen session cannot mint itself a
    # credential that outlives the session.
    stored = check_current_password(me, body.current_password)
    raw, token = ops.token_create(me.user_id, ops.TOKEN_API, name=name, lifetime_days=days, expected_hash=stored)
    return _login_result(raw, token)


@v1.get("/auth/tokens")
def list_tokens(user_id: int | None = None, me: Principal = Depends(current_principal)):
    target = me.user_id if user_id is None else user_id
    if target != me.user_id:
        require_admin(me)
    return {"tokens": [TokenInfo.from_row(token).to_dict() for token in ops.tokens_list(target)]}


@v1.delete("/auth/tokens/{token_id}", status_code=204)
def revoke_token(request: Request, token_id: int, me: Principal = Depends(current_principal)):
    # Someone else's token is "not found" rather than "forbidden": a user should
    # not learn which token ids exist.
    if not ops.token_delete(token_id, None if me.is_admin else me.user_id):
        raise errors.TokenNotFoundError(f"No token {token_id}")
    _broker(request).recheck_token(token_id)
    return Response(status_code=204)


@v1.get("/auth/settings")
def get_settings(me: Principal = Depends(current_principal)):
    """Your settings, every one with its default filled in."""
    return ops.user_settings_get(me.user_id)


@v1.patch("/auth/settings")
def update_settings(changes: dict[str, Any] = Body(...), me: Principal = Depends(current_principal)):
    """
    Change some of your settings: ``{"auto_queen": true}``. Returns them all.

    The names and types are checked by the operations layer
    (``ops.USER_SETTING_DEFAULTS``), so adding a setting does not touch this route.
    The server only stores them; clients (the web UI) act on them.
    """
    return ops.user_settings_update(me.user_id, changes)


# --- Users ---


@v1.post("/users", status_code=201)
def create_user(body: UserCreate, me: Principal = Depends(current_principal)):
    require_admin(me)
    ops.validate_username(body.username)
    password_hash = hash_password(body.password) if body.password is not None else None
    return _user_out(ops.user_create(body.username, ROLES[body.role], password_hash), me)


@v1.get("/users")
def find_user(username: str, me: Principal = Depends(current_principal)):
    return _user_out(_require_user(ops.user_get_by_name(username), f"No user named {username!r}"), me)


# Literal, so registered before /users/{user_id}, whose int parameter would
# otherwise be tried against "search" first.
@v1.get("/users/search")
def search_users(
    q: str = "",
    limit: int = Query(20, ge=1, le=ops.LIST_LIMIT_MAX),
    offset: int = Query(0, ge=0),
    me: Principal = Depends(current_principal),
):
    """Users whose name starts with ``q``, ignoring case; an empty ``q`` lists everyone."""
    return {"users": [_user_out(row, me) for row in ops.users_search(q, limit, offset)]}


@v1.get("/users/{user_id}")
def get_user(user_id: int, me: Principal = Depends(current_principal)):
    return _user_out(_require_user(ops.user_get(user_id), f"No user with id {user_id}"), me)


@v1.patch("/users/{user_id}")
def update_user(request: Request, user_id: int, body: UserPatch, me: Principal = Depends(current_principal)):
    """A user may rename themselves; everything else, and other accounts, is admin-only."""
    if not me.is_admin:
        if user_id != me.user_id:
            raise errors.ForbiddenError("You can only change your own account")
        if body.role is not None or body.disabled is not None or body.password is not None:
            raise errors.ForbiddenError(
                "Only an administrator can change roles, disable accounts or reset passwords; "
                "change your own password with POST /v1/auth/password"
            )
    _require_user(ops.user_get(user_id), f"No user with id {user_id}")
    new_hash = hash_password(body.password) if body.password is not None else None  # before any transaction
    if body.username is not None:
        ops.user_rename(user_id, body.username)
    if body.role is not None:
        ops.user_set_role(user_id, ROLES[body.role])
    if body.disabled is not None:
        ops.user_set_disabled(user_id, body.disabled)
    if new_hash is not None:
        # An admin reset: assume the old password leaked, so every token goes.
        ops.user_set_password(user_id, new_hash, revoke="all")
    if body.disabled or new_hash is not None:
        _broker(request).recheck_user(user_id)
    return _user_out(ops.user_get(user_id), me)


@v1.get("/users/{provider}/{external_id}")
def get_user_by_identity(provider: str, external_id: str, me: Principal = Depends(current_principal)):
    require_admin(me)
    row = ops.identity_get(provider, external_id)
    return _user_out(_require_user(row, f"No user is linked to {provider} id {external_id!r}"), me)


# 200, not 201, like POST /v1/games: this is get-or-create, and most calls get.
@v1.post("/users/{provider}/{external_id}")
def get_or_create_user_by_identity(
    provider: str, external_id: str, body: UsernameBody, me: Principal = Depends(current_principal)
):
    require_admin(me)
    return _user_out(ops.user_get_or_create_by_identity(provider, external_id, body.username), me)


@v1.put("/users/{user_id}/identities/{provider}/{external_id}")
def link_identity(user_id: int, provider: str, external_id: str, me: Principal = Depends(current_principal)):
    require_admin(me)
    return _user_out(ops.identity_link(user_id, provider, external_id), me)


@v1.delete("/users/{user_id}/identities/{provider}/{external_id}")
def unlink_identity(user_id: int, provider: str, external_id: str, me: Principal = Depends(current_principal)):
    """
    Admins unlink anyone's; a user may unlink their own (but not link one).

    Linking stays admin-only because it asserts that the external account is this
    user, which nobody can prove by claiming it: a bot that has checked it (a
    Discord `/link` command, with an admin token) does the linking. Unlinking only
    gives up a claim, so it is safe to let the user do it.
    """
    if user_id != me.user_id:
        require_admin(me)
    return _user_out(ops.identity_unlink(user_id, provider, external_id), me)


# --- Challenges ---


@v1.post("/challenges", status_code=201)
def create_challenge(request: Request, body: ChallengeCreate, me: Principal = Depends(current_principal)):
    challenger = acting_as(me, body.player_id)
    challenge = Challenge.from_row(
        ops.challenge_create(challenger, body.opponent_id, body.group_id, COLORS[body.color])
    ).to_dict()
    _broker(request).challenge("created", challenge)
    return challenge


@v1.get("/challenges")
def list_challenges(
    direction: Literal["incoming", "outgoing", "all"] = "all",
    user_id: int | None = None,
    me: Principal = Depends(current_principal),
):
    target = me.user_id if user_id is None else user_id
    if target != me.user_id:
        require_admin(me)
    return {"challenges": [Challenge.from_row(c).to_dict() for c in ops.challenges_for(target, direction)]}


@v1.get("/challenges/{challenge_id}")
def get_challenge(challenge_id: int, me: Principal = Depends(current_principal)):
    return Challenge.from_row(_require_challenge(challenge_id, me)).to_dict()


@v1.post("/challenges/{challenge_id}/accept", status_code=201)
def accept_challenge(
    request: Request,
    challenge_id: int,
    body: ChallengeAccept | None = None,
    me: Principal = Depends(current_principal),
):
    challenge = _require_challenge(challenge_id, me)
    player_id = body.player_id if body is not None else None
    if player_id is None and me.is_admin and me.user_id not in (challenge["challenger_id"], challenge["challenged_id"]):
        # Only the challenged player can accept, so that is who an admin acts as.
        player_id = challenge["challenged_id"]
    actor = acting_as(me, player_id)
    state = GameState.from_row(ops.challenge_accept(challenge_id, INITIAL_FEN, accepted_by=actor)).to_dict()
    # From the challenge read before accepting: accepting deletes the row.
    broker = _broker(request)
    broker.challenge("removed", Challenge.from_row(challenge).to_dict())
    broker.game_started(state)
    return state


@v1.delete("/challenges/{challenge_id}", status_code=204)
def delete_challenge(request: Request, challenge_id: int, me: Principal = Depends(current_principal)):
    """Decline (as the challenged player) or withdraw (as the challenger)."""
    challenge = _require_challenge(challenge_id, me)
    if not ops.challenge_delete(challenge_id):
        raise errors.ChallengeNotFoundError(f"No pending challenge {challenge_id}")
    _broker(request).challenge("removed", Challenge.from_row(challenge).to_dict())
    return Response(status_code=204)


# --- Games ---


@v1.post("/games")
def create_game(request: Request, body: GameCreate, me: Principal = Depends(current_principal)):
    """Admin-only: start (or fetch) a game directly, without a challenge."""
    require_admin(me)
    state = GameState.from_row(ops.game_get_or_create(body.group_id, body.white_id, body.black_id, INITIAL_FEN))
    if state.version == 1:
        # Published even when this fetched a game nobody has moved in yet: the
        # players cannot know its id in advance, and a repeat is harmless.
        _broker(request).game_started(state.to_dict())
    return state.to_dict()


@v1.get("/games")
def list_current_games(
    player_id: int | None = None, group_id: int | None = None, me: Principal = Depends(current_principal)
):
    games = ops.current_games(me.user_id if player_id is None else player_id, group_id)
    return {"games": [GameState.from_row(row).to_dict() for row in games]}


# The literal routes are registered before /games/{game_id}, whose int parameter
# would otherwise be tried against "between" and "record" first.
@v1.get("/games/between")
def games_between(
    player1: int,
    player2: int,
    group_id: int = 0,
    status: Literal["active", "finished", "all"] = "all",
):
    rows = ops.games_between(player1, player2, group_id, status)
    return {"games": [GameState.from_row(row).to_dict() for row in rows]}


@v1.get("/games/live")
def live_games(limit: int = Query(50, ge=1, le=ops.LIST_LIMIT_MAX)):
    """Every game in progress, in any group, most recently changed first: what spectators browse."""
    return {"games": [GameState.from_row(row).to_dict() for row in ops.games_live(limit)]}


@v1.get("/games/finished")
def finished_games(
    player_id: int | None = None,
    limit: int = Query(50, ge=1, le=ops.LIST_LIMIT_MAX),
    before: int | None = None,
):
    """Finished games, newest first; ``before`` (a game id) pages back, ``player_id`` narrows to one player."""
    rows = ops.games_finished(player_id, limit, before)
    return {"games": [GameState.from_row(row).to_dict() for row in rows]}


@v1.get("/games/record")
def game_record(player1: int, player2: int, group_id: int = 0):
    return ops.game_record(player1, player2, group_id)


@v1.get("/games/{game_id}")
def get_game(game_id: int):
    return GameState.from_row(_require_game(game_id)).to_dict()


@v1.delete("/games/{game_id}", status_code=204)
def delete_game(request: Request, game_id: int, me: Principal = Depends(current_principal)):
    require_admin(me)
    if not ops.game_delete(game_id):
        raise errors.GameNotFoundError(f"No game with id {game_id}")
    _broker(request).game_removed(game_id)
    return Response(status_code=204)


@v1.post("/games/{game_id}/moves")
def play_move(request: Request, game_id: int, body: MoveBody, me: Principal = Depends(current_principal)):
    actor = _game_actor(me, body.player_id, _require_game(game_id), require_actor=False)

    def mutate(row, history, now):
        game = _load_game(row, history)
        # A finished game is "over" before it is anyone's turn: let the engine
        # refuse with GameOverError rather than blaming the turn order.
        if actor is not None and not game.is_over and not game.is_players_turn(actor):
            raise errors.NotYourTurnError(f"It is not player {actor}'s turn to move")
        m = game.move(body.move)  # runs the engine; raises ChessError on illegal input
        san = game.move_history[-1]
        state, change = _change(game, row, now, new_moves=[(history["max_ply"] + 1, san, game.position_history[-1])])
        change.result = MoveResult(
            state=state,
            from_square=m.from_square,
            to_square=m.to_square,
            san=san,
            check=game.board.is_check(),
            castle=m.castle,
            promotion=m.promotion.value if m.promotion is not None else None,
            en=m.en_passant,
            # the next player's options, so they need not ask (sent on the websocket too)
            legal_moves=[] if game.is_over else game.legal_moves(),
        )
        return change

    result = ops.apply_game_change(game_id, mutate, body.expected_version)
    # After the commit: a socket must never hear of a move the database refused.
    _broker(request).game_changed(result.state.to_dict(), _move_summary(result), legal_moves=result.legal_moves)
    return result.to_dict()


def _draw_or_resign(request, game_id, body, me, method):
    actor = _game_actor(me, body.player_id, _require_game(game_id), require_actor=True)

    def mutate(row, history, now):
        game = _load_game(row, history)
        getattr(game, method)(actor)  # draw_offer / draw_accept / draw_decline / resign
        return _change(game, row, now)[1]

    state = ops.apply_game_change(game_id, mutate, body.expected_version).to_dict()
    _broker(request).game_changed(state)
    return state


@v1.post("/games/{game_id}/resign")
def resign(request: Request, game_id: int, body: ActionBody | None = None, me: Principal = Depends(current_principal)):
    return _draw_or_resign(request, game_id, body or ActionBody(), me, "resign")


@v1.post("/games/{game_id}/draw/offer")
def draw_offer(
    request: Request, game_id: int, body: ActionBody | None = None, me: Principal = Depends(current_principal)
):
    return _draw_or_resign(request, game_id, body or ActionBody(), me, "draw_offer")


@v1.post("/games/{game_id}/draw/accept")
def draw_accept(
    request: Request, game_id: int, body: ActionBody | None = None, me: Principal = Depends(current_principal)
):
    return _draw_or_resign(request, game_id, body or ActionBody(), me, "draw_accept")


@v1.post("/games/{game_id}/draw/decline")
def draw_decline(
    request: Request, game_id: int, body: ActionBody | None = None, me: Principal = Depends(current_principal)
):
    return _draw_or_resign(request, game_id, body or ActionBody(), me, "draw_decline")


@v1.get("/games/{game_id}/legal-moves")
def legal_moves(game_id: int):
    return {"moves": _load_game(_require_game(game_id)).legal_moves()}


@v1.get("/games/{game_id}/history")
def history(game_id: int):
    _require_game(game_id)
    return {"moves": ops.game_history(game_id)}


@v1.get("/games/{game_id}/pgn")
def pgn(game_id: int):
    game = _load_game(_require_game(game_id))
    game.move_history = [m["san"] for m in ops.game_history(game_id)]
    return PlainTextResponse(game.pgn())


@v1.get("/games/{game_id}/fen")
def fen(game_id: int):
    return PlainTextResponse(_require_game(game_id)["fen"])


@lru_cache(maxsize=64)
def _board_png(fen: str, white_name: str, black_name: str, perspective: str | None) -> bytes:
    """
    The PNG for a position, cached: the 64 most recent images, about 100 KB each.

    These four values are everything the image shows (a server image has no
    last-move highlight), so the key is complete, and a rename or a move gives a new
    key. Repeated views of a position, from spectators, refreshes or a bot posting
    the board again, skip rendering and encoding (together about 40 ms).
    ``compress_level=1`` encodes a third faster than PNG's default for about a
    tenth more bytes.
    """
    game = EngineGame(board=Board.from_fen(fen), white_name=white_name, black_name=black_name)
    buffer = io.BytesIO()
    game.render(perspective=perspective).save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


@v1.get("/games/{game_id}/image")
def game_image(game_id: int, perspective: Literal["white", "black"] | None = None):
    row = _require_game(game_id)
    png = _board_png(row["fen"], row["white_name"] or "", row["black_name"] or "", perspective)
    return Response(content=png, media_type="image/png")


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
            # connection to every caller without serializing it. Two requests
            # would issue BEGIN on one connection, and the database is lost when
            # the process exits anyway, so it is refused outright.
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
            # Refuse to serve a database from an older chesssnake rather than
            # failing on the first request that touches a changed table: there are
            # no migrations before 1.0, and create_all never alters a table.
            stale = schema.stale_tables(engine)
            if stale:
                db_engine.dispose_engine()
                raise errors.SQLError(
                    "This database was created by an older chesssnake and its schema has changed "
                    f"(tables: {', '.join(stale)}). There are no migrations before 1.0.0: recreate it with "
                    "`chesssnake init-db --drop`, which deletes everything in it."
                )
            if settings.database.init_schema:
                schema.create_all(engine)
            else:
                # A newer release added a table (0.14.0: user_settings). Its routes
                # would answer 500 until it exists, so say so now instead.
                missing = schema.missing_tables(engine)
                if missing:
                    db_engine.dispose_engine()
                    raise errors.SQLError(
                        f"This database is missing tables added by a newer chesssnake ({', '.join(missing)}). "
                        "Create them with `chesssnake init-db` (existing tables and data are kept), "
                        "or set database.init_schema = true."
                    )
        try:
            yield
        finally:
            # Only the app that created the engine disposes it, so a second app
            # shutting down cannot pull the connection pool out from under the first.
            if owns_engine:
                db_engine.dispose_engine()

    app = FastAPI(title="chesssnake api-endpoint", lifespan=lifespan)
    app.state.settings = settings
    # One broker per app (see realtime.py); a do-nothing one when websockets are off.
    app.state.broker = InProcessBroker(settings.websocket) if settings.websocket.enabled else Broker()
    _register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(_public_router(settings))
    app.include_router(v1)
    if settings.websocket.enabled:
        # Not on `v1`: its HTTP auth dependency cannot be satisfied by a websocket,
        # which authenticates with its first message instead.
        app.add_api_websocket_route("/v1/ws", websocket_endpoint)
    if settings.web.enabled:
        add_web_routes(app)
    return app


def _version() -> str:
    try:
        return package_version("chesssnake")
    except PackageNotFoundError:  # running from a source tree that was never installed
        return "unknown"


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
