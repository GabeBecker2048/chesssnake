"""Unit tests for FEN serialization (the board's storage format)."""

from chesssnake.engine import INITIAL_FEN, Game, from_fen, to_fen


def test_initial_position_fen():
    assert Game().fen == INITIAL_FEN == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_fen_tracks_turn_en_passant_and_clocks():
    g = Game()
    g.move("e4")  # double push sets the en-passant target and flips the turn
    assert g.fen == "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    g.move("e5")
    g.move("Nf3")  # a non-pawn, non-capture move ticks the halfmove clock
    assert g.fen == "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"


def test_fen_round_trip_midgame():
    g = Game()
    for m in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]:
        g.move(m)
    board, turn = from_fen(g.fen)
    assert to_fen(board, turn) == g.fen
    assert str(board) == str(g.board)


def test_castling_rights_drop_after_king_moves():
    g = Game()
    for m in ["e4", "e5", "Ke2"]:  # white king moves -> white loses both castling rights
        g.move(m)
    assert g.fen.split()[2] == "kq"  # only black retains rights


def test_game_exposes_all_fen_fields():
    g = Game()
    # a fresh game: full castling rights, no en-passant target, move 1, clock 0
    assert g.castling_rights == "KQkq"
    assert g.en_passant is None
    assert g.fullmove_number == 1
    assert g.halfmove_clock == 0

    g.move("e4")  # a double push exposes the en-passant target (FEN's skipped square)
    assert g.en_passant == "e3"
    assert g.board.en_passant == "e3"  # stored on the board in FEN algebraic form

    g.move("Nf6")  # any non-double-push move clears the en-passant target
    assert g.en_passant is None
    assert g.fullmove_number == 2  # incremented after Black's move
    assert g.halfmove_clock == 1  # a non-pawn, non-capture move ticked the clock


def test_castling_rights_drop_when_rook_is_captured():
    # Black bishop on g2 can capture the white h1 rook, dropping White's "K" right.
    board, turn = from_fen("4k3/8/8/8/8/8/6b1/R3K2R b KQkq - 0 1")
    g = Game(board=board, turn=turn)
    assert g.castling_rights == "KQkq"
    g.move("Bxh1")
    assert g.castling_rights == "Qkq"  # king-side right lost with the rook


def test_castling_rights_is_none_when_none_available():
    # A position with no castling rights ("-") reads back as None (like en_passant).
    board, turn = from_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    g = Game(board=board, turn=turn)
    assert g.castling_rights is None
    assert g.fen.split()[2] == "-"  # the raw FEN token is still "-"


def test_from_fen_reconstructs_playable_position():
    # A position with only kings and a white pawn about to promote.
    board, turn = from_fen("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1")
    g = Game(board=board, turn=turn)
    g.move("b8Q")
    assert g.fen.startswith("1Q2k3/")
