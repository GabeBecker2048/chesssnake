"""Unit tests for the chess-completeness features: draw rules, resign, legal moves, PGN.

These run on the local engine (no DB/server), which is the same engine the server
drives — so passing here means local and remote games share identical rules.
"""

from chesssnake.engine import Color, Game, GameStatus, Termination, from_fen


def _game(fen):
    board, turn = from_fen(fen)
    return Game(board=board, turn=turn)


def test_insufficient_material_after_capture():
    # White Nf6 captures Black's last piece (a knight on g8) -> K+N vs K.
    g = _game("4k1n1/8/5N2/8/8/8/8/4K3 w - - 0 1")
    g.move("Nxg8")
    assert g.result == GameStatus.DRAW
    assert g.termination == Termination.INSUFFICIENT_MATERIAL


def test_fifty_move_rule():
    # Halfmove clock at 99; a non-pawn, non-capture move ticks it to 100.
    g = _game("r3k2r/8/8/8/8/8/8/R3K2R w - - 99 60")
    g.move("Ra4")
    assert g.board.halfmove_clock == 100
    assert g.result == GameStatus.DRAW
    assert g.termination == Termination.FIFTY_MOVE


def test_threefold_repetition():
    # Shuffle both knights back to the start position until it occurs three times.
    g = _game("1n2k3/8/8/8/8/8/8/1N2K3 w - - 0 1")
    for m in ["Nc3", "Nc6", "Nb1", "Nb8", "Nc3", "Nc6", "Nb1", "Nb8"]:
        g.move(m)
    assert g.result == GameStatus.DRAW
    assert g.termination == Termination.THREEFOLD


def test_resign_gives_opponent_the_win():
    g = Game(white_id=10, black_id=20)
    g.move("e4")
    g.resign(20)  # black resigns
    assert g.result == GameStatus.WHITE_WON
    assert g.winner == Color.WHITE
    assert g.termination == Termination.RESIGNATION


def test_legal_moves_from_start():
    moves = Game().legal_moves()
    assert len(moves) == 20  # 16 pawn moves + 4 knight moves
    sans = {m["san"] for m in moves}
    assert {"e4", "e3", "Nf3", "Nc3"} <= sans


def test_legal_moves_exclude_self_check(make_board):
    # White king e1, knight e2 pinned by a rook on e8: the knight has no legal move.
    board = make_board({(7, 4): "K0", (6, 4): "N0", (0, 4): "R1", (0, 0): "K1"})
    g = Game(board=board, turn=0)
    knight_moves = [m for m in g.legal_moves() if m["from"] == "e2"]
    assert knight_moves == []


def test_legal_moves_include_castling():
    g = Game()
    for m in ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]:
        g.move(m)
    sans = {m["san"] for m in g.legal_moves()}
    assert "0-0" in sans


def test_pgn_export():
    g = Game(white_name="Alice", black_name="Bob")
    for m in ["e4", "e5", "Nf3", "Nc6"]:
        g.move(m)
    pgn = g.pgn()
    assert '[White "Alice"]' in pgn
    assert '[Result "*"]' in pgn
    assert "1. e4 e5 2. Nf3 Nc6 *" in pgn


def test_pgn_marks_checkmate():
    g = Game()
    for m in ["f3", "e5", "g4", "Qh4"]:  # fool's mate
        g.move(m)
    pgn = g.pgn()
    assert "Qh4#" in pgn
    assert '[Result "0-1"]' in pgn
    assert '[Termination "checkmate"]' in pgn
