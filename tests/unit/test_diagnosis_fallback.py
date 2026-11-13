"""An illegal move gets its specific error only when the reason is established.

The diagnosis that picks the specific error (``engine/_parse.py``) runs only after
a move has failed to match the legal list. If it finds no reason, or fails with an
unexpected exception, the move must be refused with the plain IllegalMoveError:
a wrong reason is worse than none.
"""

import logging

import pytest

from chesssnake.engine import Board, _parse, errors

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
PINNED = "4r1k1/8/8/8/8/8/4B3/4K3 w - - 0 1"  # the bishop on e2 is pinned by the rook on e8
CASTLE_INTO_CHECK = "4k1r1/8/8/8/8/8/8/4K2R w K - 0 1"  # g1 is attacked

# (diagnosis function, position, move) for each of the three input paths
PATHS = [
    ("_diagnose_san", START, "Bxd2"),
    ("_diagnose_san", PINNED, "Bd3"),
    ("_diagnose_castle", CASTLE_INTO_CHECK, "O-O"),
    ("_diagnose_uci", PINNED, "e2d3"),
]


def _refused_with(fen, move):
    board = Board(fen)
    with pytest.raises(errors.ChessError) as caught:
        board.move(move)
    assert board.fen == fen  # a refused move changes nothing
    return caught.value


@pytest.mark.parametrize("name,fen,move", PATHS)
def test_a_diagnosis_that_finds_no_reason_gives_illegal_move(monkeypatch, name, fen, move):
    monkeypatch.setattr(_parse, name, lambda *args: None)
    error = _refused_with(fen, move)
    assert type(error) is errors.IllegalMoveError
    assert str(error) == f'"{move}" is not a legal move'


@pytest.mark.parametrize("name,fen,move", PATHS)
def test_a_diagnosis_that_crashes_gives_illegal_move_and_is_logged(monkeypatch, caplog, name, fen, move):
    def broken(*args):
        raise IndexError("a bug in the diagnosis")

    monkeypatch.setattr(_parse, name, broken)
    with caplog.at_level(logging.ERROR, logger="chesssnake.engine._parse"):
        error = _refused_with(fen, move)
    assert type(error) is errors.IllegalMoveError
    assert any(r.exc_info and "a bug in the diagnosis" in str(r.exc_info[1]) for r in caplog.records)


@pytest.mark.parametrize(
    "fen,move",
    [(PINNED, "Bd3"), (PINNED, "e2d3"), (CASTLE_INTO_CHECK, "O-O"), (CASTLE_INTO_CHECK, "e1g1")],
)
def test_check_is_reported_only_when_confirmed(fen, move):
    assert type(_refused_with(fen, move)) is errors.MoveIntoCheckError


def test_an_unexplained_move_is_not_blamed_on_check():
    # The FEN names e6 as the en-passant square, but no black pawn stands on e5, so
    # dxe6 is impossible for a reason the diagnosis does not model. It used to fall
    # through to "that would put you in check", which is false here.
    error = _refused_with("4k3/8/8/3P4/8/8/8/4K3 w - e6 0 1", "dxe6")
    assert type(error) is errors.IllegalMoveError
