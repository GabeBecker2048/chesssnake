"""Bridge between the wire payload (:mod:`chesssnake.dto`) and the engine.

Both the api-endpoint (which now runs the engine) and the client (which keeps a
local board mirror for rendering) need to turn a :class:`~chesssnake.dto.GameState`
into engine objects and back. That conversion lives here, in one place.
"""

from .dto import GameState
from .engine import Board, Square
from .engine.enums import GameStatus
from .engine.game import Game as EngineGame


def board_from_state(state: GameState) -> Board:
    """Reconstruct a :class:`Board` (incl. en-passant target and status) from state."""
    if state.pawnmove is not None:
        i, j = Board.get_coords(state.pawnmove)
        two_moveP = Square(i, j)
    else:
        two_moveP = None
    board = Board(board=Board.assemble_board(state.board, state.moved), two_moveP=two_moveP)
    board.status = GameStatus(int(state.status))
    return board


def game_from_state(state: GameState, group_id: int, white_id: int, black_id: int) -> EngineGame:
    """Build a full engine :class:`Game` from stored state (what the server drives)."""
    return EngineGame(
        white_id=white_id,
        black_id=black_id,
        group_id=group_id,
        white_name=state.wname or "",
        black_name=state.bname or "",
        board=board_from_state(state),
        turn=state.turn,
        draw=state.draw,
    )


def state_from_game(game: EngineGame) -> GameState:
    """Serialize an engine :class:`Game` back into a :class:`GameState` for storage."""
    boardstring, moved = Board.disassemble_board(game.board)
    return GameState(
        board=boardstring,
        turn=int(game.turn),
        moved=moved,
        status=int(game.board.status),
        pawnmove=game.board.two_moveP.c_notation if game.board.two_moveP else None,
        draw=int(game.draw) if game.draw is not None else None,
        wname=game.wname,
        bname=game.bname,
    )
