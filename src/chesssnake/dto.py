"""The wire payloads shared by the client and the api-endpoint.

``GameState`` is the single definition of the serialized game state that crosses
the network; ``MoveResult`` is what a move returns. Both are stdlib dataclasses
(no third-party dependency), so the client needs no pydantic; FastAPI accepts them
on the server side too.

The board itself is carried as standard **FEN** inside ``GameState.fen`` (which
also encodes whose turn it is, castling rights, the en-passant square, and the
move clocks). Status/draw-offer/termination/version and player names are separate.
"""

from dataclasses import asdict, dataclass


@dataclass
class GameState:
    """Serialized state of a single game, exchanged between client and server."""

    fen: str
    status: int  # GameStatus: 0 in play, 1 white won, 2 black won, 3 draw
    version: int
    generation: int = 1  # which game between the triple (1 = first; higher = later rematch)
    draw: int | None = None  # open draw offer: 0 white, 1 black, None none
    termination: str | None = None  # Termination.value, or None while in play
    wname: str | None = None
    bname: str | None = None

    def to_dict(self) -> dict:
        """Return the payload as a plain JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "GameState":
        """Build a ``GameState`` from a raw ``Games`` database row (dict-like)."""
        return cls(
            fen=row["fen"],
            status=int(row["status"]),
            version=int(row["version"]),
            generation=int(row["generation"]),
            draw=int(row["draw"]) if row["draw"] is not None else None,
            termination=row["termination"],
            wname=row["wname"],
            bname=row["bname"],
        )


@dataclass
class MoveResult:
    """The outcome of a played move: the move itself plus the resulting state.

    ``from_square``/``to_square`` are algebraic squares (e.g. ``"e2"``/``"e4"``);
    ``san`` is the move string (postable). On the wire they serialize to ``from``/
    ``to`` via :meth:`to_dict`.
    """

    state: GameState
    from_square: str
    to_square: str
    san: str
    check: bool = False
    castle: str | None = None
    promotion: str | None = None
    en: bool = False

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict (uses ``from``/``to`` wire keys)."""
        return {
            "state": self.state.to_dict(),
            "from": self.from_square,
            "to": self.to_square,
            "san": self.san,
            "check": self.check,
            "castle": self.castle,
            "promotion": self.promotion,
            "en": self.en,
        }

    @classmethod
    def from_dict(cls, data) -> "MoveResult":
        """Build a ``MoveResult`` from a decoded response dict."""
        return cls(
            state=GameState(**data["state"]),
            from_square=data["from"],
            to_square=data["to"],
            san=data["san"],
            check=data["check"],
            castle=data.get("castle"),
            promotion=data.get("promotion"),
            en=data.get("en", False),
        )
