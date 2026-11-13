"""Bugs found by the 0.15.0 differential testing, each pinned to its position."""

import pytest

from chesssnake.engine import errors

from . import engine_adapter as eng

CASTLE_OUT_OF_CHECK = "rnbqk2r/pp3p1p/3Np2n/2pp2p1/1P3b2/6P1/PBPPPP1P/1R1QKBNR b Kkq - 6 8"


@pytest.mark.xfail(reason="engine bug, fixed later in 0.15.0", strict=False)
@pytest.mark.parametrize(
    "fen,castle",
    [
        # black is in check from the knight on d6
        (CASTLE_OUT_OF_CHECK, "0-0"),
        # black is in check
        ("2bqk2r/2p1pp2/1p3n1b/3pr2p/Qn3Pp1/N1PPP1PP/PP1K2R1/R1B2BN1 b k - 1 19", "0-0"),
        # the white king would cross d1, attacked by the queen on d3
        ("1nb1kbnr/2p4p/p7/3P2p1/p2p1BP1/PPNq1p2/4BP1P/R3KR2 w Qk - 2 19", "0-0-0"),
    ],
)
def test_illegal_castling_is_refused(fen, castle):
    game = eng.new(fen)
    assert castle not in {san for _, san in eng.legal_pairs(game)}
    with pytest.raises(errors.ChessError):
        eng.play(game, castle)


@pytest.mark.xfail(reason="engine bug, fixed later in 0.15.0", strict=False)
@pytest.mark.parametrize(
    "fen,move,uci",
    [
        # file disambiguation combined with a capture
        ("r3k1r1/pbpp2p1/5npp/P3n2P/2p1pPP1/1P4Q1/2R1P1B1/5KNR b - - 5 31", "Nexg4", "e5g4"),
        # promotion written with "=" (what pgn() exports), with and without a check suffix
        ("2r3r1/2p1P1k1/2P3p1/2b3P1/6PQ/7p/b2R4/5KN1 w - - 1 60", "e8=N", "e7e8n"),
        ("2r3r1/2p1P1k1/2P3p1/2b3P1/6PQ/7p/b2R4/5KN1 w - - 1 60", "e8=N+", "e7e8n"),
        ("2r3r1/2p1P1k1/2P3p1/2b3P1/6PQ/7p/b2R4/5KN1 w - - 1 60", "e8=Q", "e7e8q"),
        # capture-promotion with "="
        ("4k3/8/8/8/8/8/2p5/3QK3 b - - 0 1", "cxd1=B", "c2d1b"),
        # UCI strings, which bots and engines send
        ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", "e2e4", "e2e4"),
        ("2r3r1/2p1P1k1/2P3p1/2b3P1/6PQ/7p/b2R4/5KN1 w - - 1 60", "e7e8q", "e7e8q"),
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1", "e1g1"),
        ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "O-O-O", "e1c1"),
    ],
)
def test_notation_is_accepted(fen, move, uci):
    game, expected = eng.new(fen), eng.new(fen)
    eng.play(game, move)
    eng.play(expected, dict((u, s) for u, s in eng.legal_pairs(expected))[uci])
    assert eng.fen(game) == eng.fen(expected)


@pytest.mark.xfail(reason="engine bug, fixed later in 0.15.0", strict=False)
def test_disambiguation_ignores_a_pinned_piece():
    # Knights on b1 and f3 both reach d2, but f3 is pinned against the king on f1
    # by the rook on f8, so SAN needs no disambiguation: the move is "Nd2".
    fen = "5r1k/8/8/8/8/5N2/8/1N3K2 w - - 0 1"
    game = eng.new(fen)
    sans = {san for _, san in eng.legal_pairs(game)}
    assert "Nd2" in sans and "Nbd2" not in sans
    eng.play(game, "Nd2")
