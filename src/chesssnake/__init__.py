from .dto import Challenge, GameState, LoginResult, MoveResult, TokenInfo, User
from .engine.enums import Color, GameStatus, PieceType, Termination
from .remote.game import Game, connect


def __getattr__(name):
    # ApiClient lives with the HTTP code; resolving it lazily keeps `import
    # chesssnake` free of it, as it was before the client was exported here.
    if name == "ApiClient":
        from .remote.client import ApiClient

        return ApiClient
    if name == "AsyncApiClient":
        from .remote.async_client import AsyncApiClient

        return AsyncApiClient
    if name == "PlayerClient":
        from .remote.player import PlayerClient

        return PlayerClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ApiClient",
    "AsyncApiClient",
    "Challenge",
    "Color",
    "Game",
    "GameState",
    "GameStatus",
    "LoginResult",
    "MoveResult",
    "PieceType",
    "PlayerClient",
    "Termination",
    "TokenInfo",
    "User",
    "connect",
]
