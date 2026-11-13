"""The `Piece` value: what stands on a square."""

from dataclasses import dataclass

from .enums import Color, PieceType


@dataclass(frozen=True, slots=True)
class Piece:
    """
    A chess piece: a type and a color, nothing else.

    A ``Piece`` is an immutable value, so two pieces compare equal when they are the
    same type and color, and a piece can be used as a dict key. It knows nothing of
    where it stands or how it moves; ask the :class:`~chesssnake.engine.board.Board`
    for that.

    :ivar type: The :class:`~chesssnake.engine.enums.PieceType`.
    :ivar color: The :class:`~chesssnake.engine.enums.Color`.
    """

    type: PieceType
    color: Color

    @property
    def symbol(self) -> str:
        """The FEN letter: uppercase for white (``"N"``), lowercase for black (``"n"``)."""
        letter = self.type.value
        return letter if self.color is Color.WHITE else letter.lower()

    @classmethod
    def from_symbol(cls, symbol: str) -> "Piece":
        """
        The piece for a FEN letter (``"N"`` is a white knight, ``"n"`` a black one).

        :raises ValueError: if ``symbol`` is not one of ``PNBRQK`` in either case.
        """
        if len(symbol) != 1 or symbol.upper() not in "PNBRQK":
            raise ValueError(f"not a piece letter: {symbol!r}")
        return PIECES[PieceType(symbol.upper()), Color.WHITE if symbol.isupper() else Color.BLACK]

    def __str__(self) -> str:
        return self.symbol


# The twelve pieces, created once. The board only ever holds these instances, which
# lets the move generator compare pieces by identity (``is``) in its hot loops.
PIECES: dict[tuple[PieceType, Color], Piece] = {(t, c): Piece(t, c) for t in PieceType for c in Color}
