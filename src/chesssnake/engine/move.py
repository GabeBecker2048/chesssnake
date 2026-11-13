"""The `Move` value: one move that was played."""

from dataclasses import dataclass

from .enums import PieceType
from .piece import Piece


@dataclass(frozen=True, slots=True)
class Move:
    """
    A move that was played, as :meth:`Board.move` and :meth:`Game.move` return it.

    An immutable value with string squares; it holds no reference to the board.

    :ivar from_square: Where the piece started (``"e2"``; the king's square when castling).
    :ivar to_square: Where it ended (``"e4"``; the king's destination when castling).
    :ivar piece: The :class:`Piece` that moved (the pawn, for a promotion).
    :ivar san: The move in chesssnake notation, with ``+`` or ``#`` when it gives
        check or mate (``"Nf3"``, ``"exd8Q+"``, ``"0-0"``). This is what the game's
        history records; :meth:`Game.pgn` writes it in PGN form.
    :ivar promotion: The :class:`PieceType` promoted to, or ``None``.
    :ivar captured: The :class:`Piece` captured (the pawn, en passant), or ``None``.
    :ivar castle: ``"K"`` (kingside) or ``"Q"`` (queenside) for castling, else ``None``.
    :ivar en_passant: Whether the move was an en-passant capture.
    """

    from_square: str
    to_square: str
    piece: Piece
    san: str
    promotion: "PieceType | None" = None
    captured: "Piece | None" = None
    castle: "str | None" = None
    en_passant: bool = False

    @property
    def uci(self) -> str:
        """The move in UCI form (``"e2e4"``, ``"e7e8q"``, ``"e1g1"`` for castling)."""
        promo = self.promotion.value.lower() if self.promotion is not None else ""
        return f"{self.from_square}{self.to_square}{promo}"

    def __str__(self) -> str:
        return self.san
