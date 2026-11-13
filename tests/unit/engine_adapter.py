"""The one place the engine verification tests touch the engine.

Perft, the differential tests and the round-trip tests all go through these few
functions, so a change to the engine's API means changing this file, not every test.
"""

from chesssnake.engine import Game


def new(fen: str) -> Game:
    """A game from a FEN position."""
    return Game.from_fen(fen)


def fen(game: Game) -> str:
    return game.fen


def legal_uci(game: Game) -> set[str]:
    """The legal moves as UCI strings (castling as the king's two-square move)."""
    return {uci for uci, _ in legal_pairs(game)}


def legal_pairs(game: Game) -> list[tuple[str, str]]:
    """``(uci, san)`` for every legal move, ``san`` being what the engine lists."""
    out = []
    for m in game.legal_moves():
        frm, to, promo = m["from"], m["to"], m["promotion"]
        if to is None:  # castling: the king's destination
            rank = frm[1]
            to = ("g" if m["san"] == "0-0" else "c") + rank
        out.append((frm + to + (promo or "").lower(), m["san"]))
    return out


def play(game: Game, move: str) -> None:
    game.move(move)


def perft(fen_str: str, depth: int) -> int:
    """Leaf count to ``depth`` plies (the standard move-generator check)."""
    game = new(fen_str)
    return _perft(game, depth)


def _perft(game: Game, depth: int) -> int:
    pairs = legal_pairs(game)
    if depth == 1:
        return len(pairs)
    total = 0
    start = game.fen
    for _, san in pairs:
        child = new(start)
        child.move(san)
        total += _perft(child, depth - 1)
    return total
