"""
Remote-capable ``Game``.

By default this is exactly the in-memory ``chesslib`` game (no network, no extra
dependencies). Pass ``remote=True`` (with an ``api_url`` or the
``CHESSSNAKE_API_URL`` environment variable) to load/persist the game through a
``chesssnake api-endpoint`` REST server: the chess engine still runs locally and
only serialized state crosses the wire, so many clients can share one database.
"""

import os

from ..chesslib.Game import Game as BaseGame
from ..chesslib import Chess


def _make_client(api_url=None, client=None):
    """Build (or accept an injected) ApiClient for remote operations."""
    if client is not None:
        return client
    from .client import ApiClient
    url = api_url or os.getenv("CHESSSNAKE_API_URL")
    if not url:
        raise ValueError(
            "A remote game requires an api_url argument or the CHESSSNAKE_API_URL "
            "environment variable."
        )
    return ApiClient(url)


class Game(BaseGame):
    """
    A chess game that optionally persists to a chesssnake api-endpoint.

    :param remote: If True, load-or-create and (optionally) sync this game via the API.
    :param auto_sync: If True, push state to the API after every move / draw action
        (implies ``remote=True``).
    :param api_url: Base URL of the api-endpoint. Falls back to ``CHESSSNAKE_API_URL``.
    """

    def __init__(self, white_id=0, black_id=1, group_id=0, white_name='', black_name='',
                 remote=False, auto_sync=False, api_url=None, _client=None):
        self.remote = remote or auto_sync
        self.auto_sync = auto_sync
        self._client = None

        if self.remote:
            self._client = _make_client(api_url, _client)
            state = self._client.get_or_create_game(group_id, white_id, black_id, white_name, black_name)
            super().__init__(
                white_id, black_id, group_id,
                white_name=state["wname"] if state["wname"] is not None else white_name,
                black_name=state["bname"] if state["bname"] is not None else black_name,
                board=self._board_from_state(state),
                turn=state["turn"],
                draw=state["draw"],
            )
        else:
            super().__init__(white_id, black_id, group_id, white_name, black_name)

    # --- state (de)serialization ------------------------------------------

    @staticmethod
    def _board_from_state(state):
        if state["pawnmove"] is not None:
            i, j = Chess.Board.get_coords(state["pawnmove"])
            pawnmove = Chess.Square(i, j)
        else:
            pawnmove = None
        board = Chess.Board(
            board=Chess.Board.assemble_board(state["board"], state["moved"]),
            two_moveP=pawnmove,
        )
        board.status = int(state["status"])
        return board

    def _state_payload(self):
        boardstring, moved = Chess.Board.disassemble_board(self.board)
        return {
            "board": boardstring,
            "turn": self.turn,
            "pawnmove": self.board.two_moveP.c_notation if self.board.two_moveP else None,
            "draw": self.draw,
            "moved": moved,
            "status": self.board.status,
            "wname": self.wname,
            "bname": self.bname,
        }

    # --- persistence -------------------------------------------------------

    def sync(self):
        """Push the current full game state to the API (no-op for local games)."""
        if self.remote:
            self._client.update_game(self.gid, self.wid, self.bid, self._state_payload())

    def move(self, move, img=False, save=None):
        result = super().move(move, img=img, save=save)
        if self.auto_sync:
            self.sync()
        return result

    def draw_offer(self, player_id):
        super().draw_offer(player_id)
        if self.auto_sync:
            self._client.update_draw(self.gid, self.wid, self.bid, self.draw, self.board.status)

    def draw_accept(self, player_id):
        super().draw_accept(player_id)
        if self.auto_sync:
            self._client.update_draw(self.gid, self.wid, self.bid, self.draw, self.board.status)

    def draw_decline(self, player_id):
        super().draw_decline(player_id)
        if self.auto_sync:
            self._client.clear_draw(self.gid, self.wid, self.bid)

    def end(self):
        """If the game is over, delete it from the remote database. Returns True if ended."""
        if self.board.status != 0:
            if self.remote:
                self._client.delete_game(self.gid, self.wid, self.bid)
            return True
        return False


class Challenge:
    """Client wrapper for the challenge endpoints of a chesssnake api-endpoint."""

    @staticmethod
    def challenge(challenger, opponent, gid=0, api_url=None, _client=None):
        """Issue or accept a challenge. Returns True if an existing challenge was accepted."""
        return _make_client(api_url, _client).challenge(challenger, opponent, gid)

    @staticmethod
    def exists(player1, player2, gid=0, api_url=None, _client=None):
        """Return the pending challenge between two players, or None."""
        return _make_client(api_url, _client).challenge_exists(player1, player2, gid)

    @staticmethod
    def delete(challenger, challenged, gid=0, api_url=None, _client=None):
        """Delete a pending challenge."""
        _make_client(api_url, _client).delete_challenge(challenger, challenged, gid)
