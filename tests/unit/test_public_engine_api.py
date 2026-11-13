"""The public engine API, pinned.

``chesssnake.engine.__all__`` and the public members of ``Board``, ``Move`` and
``Piece`` are what 1.0.0 will promise to keep. A change here is a decision, not a
side effect: if one of these tests fails, the API changed.
"""

import dataclasses

import pytest

import chesssnake.engine as engine
from chesssnake.engine import Board, Color, Game, GameStatus, Move, Piece, PieceType, Termination, errors

WK, BK = Piece(PieceType.KING, Color.WHITE), Piece(PieceType.KING, Color.BLACK)


def _public(cls):
    return {name for name in vars(cls) if not name.startswith("_")}


def test_engine_exports():
    assert sorted(engine.__all__) == sorted(
        [
            "Board",
            "Color",
            "Game",
            "GameStatus",
            "INITIAL_FEN",
            "Move",
            "Piece",
            "PieceType",
            "Termination",
            "errors",
            "render_board",
            "render_text",
        ]
    )


def test_board_surface():
    assert _public(Board) == {
        "copy",
        "fen",
        "from_fen",
        "is_attacked",
        "is_check",
        "is_checkmate",
        "is_insufficient_material",
        "is_stalemate",
        "legal_moves",
        "move",
        "piece_at",
        "pieces",
        "undo",
    }
    assert {k for k in vars(Board()) if not k.startswith("_")} == {
        "turn",
        "castling",
        "en_passant",
        "halfmove_clock",
        "fullmove_number",
        "status",
        "termination",
    }


def test_value_types():
    assert [f.name for f in dataclasses.fields(Piece)] == ["type", "color"]
    assert [f.name for f in dataclasses.fields(Move)] == [
        "from_square",
        "to_square",
        "piece",
        "san",
        "promotion",
        "captured",
        "castle",
        "en_passant",
    ]


# --- Board queries --------------------------------------------------------------


def test_starting_position_queries():
    board = Board()
    assert board.turn is Color.WHITE
    assert board.piece_at("e1") == WK
    assert board.piece_at("e4") is None
    assert board.pieces(PieceType.KNIGHT, Color.WHITE) == ["b1", "g1"]
    assert board.pieces(PieceType.KING, Color.BLACK) == ["e8"]
    assert board.is_attacked("f3", by=Color.WHITE)
    assert not board.is_attacked("e4", by=Color.WHITE)
    assert board.is_attacked("f6", by=Color.BLACK)
    assert not board.is_check() and not board.is_checkmate() and not board.is_stalemate()
    assert len(board.legal_moves()) == 20


def test_bad_square_names_raise():
    with pytest.raises(ValueError):
        Board().piece_at("z9")
    with pytest.raises(ValueError):
        Board().is_attacked("e0", by=Color.WHITE)


@pytest.mark.parametrize(
    "fen,reason",
    [
        ("not a fen", "6 fields"),
        ("8/8/8/8/8/8/8/8 w - - 0 1", "white king"),
        ("4k3/8/8/8/8/8/8/4K2X w - - 0 1", "piece letter"),
        ("4k3/8/8/8/8/8/8/4K3 x - - 0 1", "side to move"),
        ("4k3/8/8/8/8/8/8/4K3 w KX - 0 1", "castling"),
        ("4k3/8/8/8/8/8/8/4K3 w - e4 0 1", "en-passant"),
        ("4k3/8/8/8/8/8/8/4K3 w - - a 1", "clocks"),
        ("4k3/8/8/8/8/8/8/4K4 w - - 0 1", "8 squares"),
    ],
)
def test_invalid_fen_says_why(fen, reason):
    with pytest.raises(ValueError, match=reason):
        Board.from_fen(fen)


def test_move_returns_a_value_and_undo_restores_everything():
    board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 3 10")
    before = board.fen
    move = board.move("O-O")
    assert move == Move("e1", "g1", WK, "0-0", castle="K")
    assert move.uci == "e1g1"
    assert board.piece_at("f1") == Piece(PieceType.ROOK, Color.WHITE)
    assert board.castling == "kq"
    assert board.undo() == move
    assert board.fen == before
    with pytest.raises(IndexError):
        board.undo()


def test_undo_restores_a_finished_game():
    board = Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    move = board.move("Ra8")
    assert move.san == "Ra8#"
    assert board.status is GameStatus.WHITE_WON and board.termination is Termination.CHECKMATE
    board.undo()
    assert board.status is GameStatus.IN_PLAY and board.termination is None


def test_capture_promotion_and_en_passant_values():
    board = Board("1n2k3/P7/8/3pP3/8/8/8/4K3 w - d6 0 1")
    ep = board.copy().move("exd6")
    assert ep.en_passant and ep.captured == Piece(PieceType.PAWN, Color.BLACK) and ep.to_square == "d6"
    promo = board.move("axb8=Q+")
    assert promo.promotion is PieceType.QUEEN
    assert promo.captured == Piece(PieceType.KNIGHT, Color.BLACK)
    assert promo.san == "axb8Q+"
    assert promo.uci == "a7b8q"


def test_copy_is_independent():
    board = Board()
    other = board.copy()
    other.move("e4")
    assert board.fen != other.fen and board.piece_at("e2") is not None


def test_game_turn_is_the_boards():
    game = Game.from_fen("4k3/8/8/8/8/8/8/4K3 b - - 0 1")
    assert game.turn is Color.BLACK and game.board.turn is Color.BLACK
    game.move("Kd7")
    assert game.to_move is Color.WHITE


def test_history_records_canonical_notation():
    game = Game()
    for move in ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "e1g1"):
        game.move(move)
    assert game.move_history == ["e4", "e5", "Nf3", "Nc6", "Bc4", "Nf6", "0-0"]


# --- the specific errors survive the legal-list matching ---------------------------

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@pytest.mark.parametrize(
    "fen,move,error",
    [
        (START, "Nf6", errors.PieceNotFoundError),
        (START, "e5", errors.PieceNotFoundError),
        (START, "Nxf3", errors.NothingToCaptureError),
        (START, "Bxd2", errors.CaptureOwnPieceError),
        (START, "Nd2", errors.PieceOnSquareError),
        (START, "0-0", errors.InvalidCastleError),
        (START, "e5x", errors.InvalidNotationError),
        (START, "e2e5", errors.IllegalMoveError),
        (START, "e3e4", errors.IllegalMoveError),
        (START, "e2e4q", errors.PromotionError),
        (START, "e4Q", errors.PromotionError),
        ("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1", "b8", errors.PromotionError),
        ("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1", "b7b8", errors.PromotionError),
        # two rooks reach d1 and the move does not say which
        ("4k3/8/8/8/8/8/4K3/R6R w - - 0 1", "Rd1", errors.MultiplePiecesFoundError),
        # a capture written without its "x"
        ("4k3/8/8/8/8/8/8/R2nK3 w - - 0 1", "Rd1", errors.PieceOnSquareError),
        # the bishop on e2 is pinned by the rook on e8
        ("4r1k1/8/8/8/8/8/4B3/4K3 w - - 0 1", "Bd3", errors.MoveIntoCheckError),
        ("4r1k1/8/8/8/8/8/4B3/4K3 w - - 0 1", "e2d3", errors.MoveIntoCheckError),
        # the king may not step onto an attacked square
        ("4r1k1/8/8/8/8/8/8/3K4 w - - 0 1", "Ke1", errors.MoveIntoCheckError),
        # castling onto an attacked square: allowed path, attacked destination
        ("4kr2/8/8/8/8/8/8/4K2R w K - 0 1", "0-0", errors.InvalidCastleError),
        ("4k1r1/8/8/8/8/8/8/4K2R w K - 0 1", "O-O", errors.MoveIntoCheckError),
        ("4k1r1/8/8/8/8/8/8/4K2R w K - 0 1", "e1g1", errors.MoveIntoCheckError),
    ],
)
def test_specific_errors(fen, move, error):
    board = Board(fen)
    with pytest.raises(error):
        board.move(move)
    assert board.fen == fen  # a refused move changes nothing


def test_game_over_is_refused():
    board = Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    board.move("Ra8")
    with pytest.raises(errors.GameOverError):
        board.move("Kh8")
