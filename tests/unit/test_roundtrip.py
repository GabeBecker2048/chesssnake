"""Round trips: what the engine writes, it must read back.

- every SAN listed by ``legal_moves()`` is accepted by ``move()``;
- ``pgn()`` parses back in python-chess and replays in a fresh chesssnake game;
- a FEN read in is written out unchanged.
"""

import io
import random

import pytest

from . import engine_adapter as eng
from .test_perft import KIWIPETE, POS3, POS4, POS5, POS6, START

chess = pytest.importorskip("chess")
chess_pgn = pytest.importorskip("chess.pgn")

POSITIONS = [START, KIWIPETE, POS3, POS4, POS5, POS6]


@pytest.mark.parametrize("fen", POSITIONS)
def test_fen_round_trip(fen):
    assert eng.fen(eng.new(fen)) == fen


@pytest.mark.parametrize("fen", POSITIONS)
def test_every_listed_san_is_accepted(fen):
    for uci, san in eng.legal_pairs(eng.new(fen)):
        game = eng.new(fen)
        eng.play(game, san)
        ref = chess.Board(fen)
        ref.push_uci(uci)
        assert eng.fen(game) == ref.fen(en_passant="fen"), f"{san} ({uci}) from {fen}"


def _random_game(seed, plies=120):
    rng = random.Random(seed)
    game = eng.new(chess.STARTING_FEN)
    for _ in range(plies):
        if game.is_over:
            break
        _, san = rng.choice(eng.legal_pairs(game))
        eng.play(game, san)
    return game


@pytest.mark.parametrize("seed", range(5))
def test_pgn_round_trip(seed):
    game = _random_game(seed)
    pgn = game.pgn()

    parsed = chess_pgn.read_game(io.StringIO(pgn))
    assert parsed is not None and not parsed.errors, parsed.errors if parsed else pgn
    assert parsed.end().board().fen(en_passant="fen") == eng.fen(game)

    replay = eng.new(chess.STARTING_FEN)
    for node in parsed.mainline():
        eng.play(replay, node.san())
    assert eng.fen(replay) == eng.fen(game)
    assert replay.pgn() == pgn
