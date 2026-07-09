"""Bridge between the wire payload (:mod:`chesssnake.dto`) and the engine.

The api-endpoint (which runs the engine) turns a stored :class:`GameState` into an
engine :class:`Game`, applies an action, and turns the result back into a
:class:`GameState`. This conversion lives here, in one place, on top of FEN.
"""

from .dto import GameState
from .engine import from_fen, to_fen
from .engine.enums import GameStatus, Termination
from .engine.game import Game as EngineGame


def game_from_state(state: GameState, group_id, white_id, black_id, position_history=None, move_history=None):
    """Build a full engine :class:`Game` from stored state (what the server drives).

    ``position_history`` (the list of past position keys) is loaded so that the
    reconstructed game detects threefold repetition exactly as an in-memory game
    would; ``move_history`` (SAN) is loaded so PGN export works server-side.
    """
    board, turn = from_fen(state.fen)
    game = EngineGame(
        white_id=white_id,
        black_id=black_id,
        group_id=group_id,
        white_name=state.wname or "",
        black_name=state.bname or "",
        board=board,
        turn=turn,
        draw=state.draw,
        move_history=move_history,
        position_history=position_history,
    )
    game.board.status = GameStatus(int(state.status))
    game.board.termination = Termination(state.termination) if state.termination is not None else None
    return game


def state_from_game(game: EngineGame, version: int) -> GameState:
    """Serialize an engine :class:`Game` back into a :class:`GameState` for storage."""
    return GameState(
        fen=to_fen(game.board, game.turn),
        status=int(game.board.status),
        version=version,
        draw=int(game.draw) if game.draw is not None else None,
        termination=game.board.termination.value if game.board.termination is not None else None,
        wname=game.wname,
        bname=game.bname,
    )


def board_and_turn(state: GameState):
    """Reconstruct ``(board, turn)`` from state, with status/termination applied.

    Used by the client to mirror server state locally (for rendering + accessors).
    """
    board, turn = from_fen(state.fen)
    board.status = GameStatus(int(state.status))
    board.termination = Termination(state.termination) if state.termination is not None else None
    return board, turn
