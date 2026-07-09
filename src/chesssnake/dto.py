"""The wire payload shared by the client and the api-endpoint.

``GameState`` is the single definition of the serialized game-state shape that
crosses the network. It is a stdlib dataclass (no third-party dependency), so the
client can use it without pulling in pydantic; FastAPI accepts it directly as a
request/response model on the server side.

Values are primitives on the wire: ``turn``/``draw`` are ints (0/1) or ``None``,
``status`` is an int. The engine-side enum conversions happen in the client.
"""

from dataclasses import asdict, dataclass


@dataclass
class GameState:
    """Serialized state of a single game, exchanged between client and server."""

    board: str
    turn: int
    moved: str
    status: int
    pawnmove: str | None = None
    draw: int | None = None
    wname: str | None = None
    bname: str | None = None

    def to_dict(self) -> dict:
        """Return the payload as a plain JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> "GameState":
        """Build a ``GameState`` from a raw ``Games`` database row (dict-like)."""
        return cls(
            board=row["board"],
            turn=int(row["turn"]),
            moved=row["moved"],
            status=int(row["status"]),
            # the pawnmove column is CHAR(2)-padded; trim it back to notation
            pawnmove=row["pawnmove"].strip() if row["pawnmove"] is not None else None,
            draw=int(row["draw"]) if row["draw"] is not None else None,
            wname=row["wname"],
            bname=row["bname"],
        )
