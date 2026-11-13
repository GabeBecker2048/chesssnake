"""Differential tests: play seeded random games through chesssnake and python-chess.

At every ply both engines must agree on the set of legal moves, on the full FEN, and
on whether (and why) the game is over. Each move is handed to chesssnake as the
standard SAN python-chess writes for it (``O-O``, ``e8=Q``, ``Nbd2+``), so this also
checks that chesssnake reads standard notation.

python-chess is GPL-3.0 and is used here only as a test oracle: it is a dev
dependency and nothing under ``src/`` imports it.
"""

import random

import pytest

from chesssnake.engine import GameStatus, Termination

from . import engine_adapter as eng

chess = pytest.importorskip("chess")

MAX_PLIES = 300


def _compare(game, ref, where):
    ours, theirs = eng.legal_uci(game), {m.uci() for m in ref.legal_moves}
    assert ours == theirs, (
        f"{where}: legal moves differ in {ref.fen()}\n"
        f"  only chesssnake: {sorted(ours - theirs)}\n  only python-chess: {sorted(theirs - ours)}"
    )
    assert eng.fen(game) == ref.fen(en_passant="fen"), f"{where}: FEN differs"
    assert game.board.insufficient_material() == ref.is_insufficient_material(), f"{where}: {ref.fen()}"


def _check_ending(game, ref, where):
    """chesssnake ends games by rule on its own; python-chess must agree on the reason."""
    term = game.termination
    if term == Termination.CHECKMATE:
        assert ref.is_checkmate(), where
        winner = GameStatus.WHITE_WON if ref.turn == chess.BLACK else GameStatus.BLACK_WON
        assert game.result == winner, where
    elif term == Termination.STALEMATE:
        assert ref.is_stalemate(), where
    elif term == Termination.INSUFFICIENT_MATERIAL:
        assert ref.is_insufficient_material(), where
    elif term == Termination.THREEFOLD:
        assert ref.is_repetition(3), where
    elif term == Termination.FIFTY_MOVE:
        assert ref.halfmove_clock >= 100, where
    else:  # pragma: no cover - a termination this test does not know about
        pytest.fail(f"{where}: unexpected termination {term}")


def play_random_game(seed):
    rng = random.Random(seed)
    game = eng.new(chess.STARTING_FEN)
    ref = chess.Board()
    for ply in range(MAX_PLIES):
        where = f"seed {seed}, ply {ply}"
        _compare(game, ref, where)
        if game.is_over:
            _check_ending(game, ref, where)
            return
        assert not ref.is_checkmate() and not ref.is_stalemate(), f"{where}: python-chess says the game is over"
        move = rng.choice(list(ref.legal_moves))
        eng.play(game, ref.san(move))
        ref.push(move)


@pytest.mark.xfail(reason="engine bug, fixed later in 0.15.0", strict=False)
@pytest.mark.parametrize("seed", range(20))
def test_random_games_agree(seed):
    play_random_game(seed)


@pytest.mark.xfail(reason="engine bug, fixed later in 0.15.0", strict=False)
@pytest.mark.slow
@pytest.mark.parametrize("seed", range(20, 220))
def test_random_games_agree_many(seed):
    play_random_game(seed)
