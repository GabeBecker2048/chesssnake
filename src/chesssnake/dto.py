"""The wire payloads shared by the client and the api-endpoint.

``GameState`` is the single definition of the serialized game state that crosses
the network; ``MoveResult`` is what a move returns; ``User`` is an account,
``Challenge`` a pending challenge, and ``LoginResult`` / ``TokenInfo`` what the
authentication routes return. All are stdlib dataclasses (no third-party dependency), so the client needs no
pydantic; FastAPI accepts them on the server side too.

The board itself is carried as standard **FEN** inside ``GameState.fen`` (which
also encodes whose turn it is, castling rights, the en-passant square, and the
move clocks). Status, draw offer, termination, version, the players (ids and
usernames) and timestamps are separate fields.

Each payload is rebuilt from JSON with ``from_dict``, which ignores keys it does
not know, so a field added to the server in a later version never breaks an
older client.

``GameState`` also reads its raw fields back as the engine's enums (``to_move``,
``result``, ``winner``, ``ending``, ``draw_offered_by``), with the same names as
the accessors of :class:`chesssnake.Game`, so a client never parses FEN or
compares status codes itself.
"""

from dataclasses import asdict, dataclass, field, fields

from .engine.enums import Color, GameStatus, Termination

#: Role names on the wire, mapped to the codes the database stores.
ROLES = {"user": 0, "admin": 1}
ROLE_NAMES = {code: name for name, code in ROLES.items()}

#: Challenge colours on the wire (the colour the challenger plays), mapped to codes.
COLORS = {"white": 0, "black": 1, "random": 2}
COLOR_NAMES = {code: name for name, code in COLORS.items()}


def _iso(value):
    """A timestamp as ISO 8601 text; already-text values and ``None`` pass through."""
    if value is None or isinstance(value, str):
        return value
    return value.isoformat()


def _known_fields(cls, data):
    names = {f.name for f in fields(cls)}
    return {key: value for key, value in data.items() if key in names}


@dataclass
class GameState:
    """Serialized state of a single game, exchanged between client and server."""

    fen: str
    status: int  # GameStatus: 0 in play, 1 white won, 2 black won, 3 draw
    version: int
    generation: int = 1  # which game between the triple (1 = first; higher = later rematch)
    draw: int | None = None  # open draw offer: 0 white, 1 black, None none
    termination: str | None = None  # Termination.value, or None while in play
    id: int | None = None  # the game's id on the server; None for a local game
    group_id: int = 0
    white_id: int = 0
    black_id: int = 1
    white_name: str = ""
    black_name: str = ""
    started_at: str | None = None  # ISO 8601, UTC
    updated_at: str | None = None  # ISO 8601, UTC; when the game finished, for an archived game
    #: The last move played, ``{"from", "to", "san", "promotion"}`` (``promotion`` a
    #: piece letter or ``None``), or ``None`` before the first move (0.15.4).
    last_move: dict | None = None

    def to_dict(self) -> dict:
        """Return the payload as a plain JSON-serializable dict."""
        return asdict(self)

    # --- the fields as the engine's types (computed, not sent) ----------------

    @property
    def to_move(self) -> Color:
        """Whose turn it is (from the FEN). Still the side to move once the game is over."""
        return Color.BLACK if self.fen.split()[1] == "b" else Color.WHITE

    @property
    def result(self) -> GameStatus:
        """``IN_PLAY``, ``WHITE_WON``, ``BLACK_WON`` or ``DRAW``."""
        return GameStatus(self.status)

    @property
    def is_over(self) -> bool:
        return self.status != GameStatus.IN_PLAY

    @property
    def winner(self) -> Color | None:
        """The colour that won, or ``None`` while in play and for a draw."""
        if self.status == GameStatus.WHITE_WON:
            return Color.WHITE
        if self.status == GameStatus.BLACK_WON:
            return Color.BLACK
        return None

    @property
    def ending(self) -> Termination | None:
        """How the game ended, as a :class:`Termination` (``termination`` is its text)."""
        return Termination(self.termination) if self.termination else None

    @property
    def draw_offered_by(self) -> Color | None:
        """The colour with an open draw offer, or ``None``."""
        return None if self.draw is None else Color(self.draw)

    def player_id(self, color) -> int:
        """The user id playing ``color`` (a :class:`Color` or ``"white"``/``"black"``)."""
        white = color == Color.WHITE or color == "white"
        return self.white_id if white else self.black_id

    def player_name(self, color) -> str:
        """The username playing ``color``."""
        white = color == Color.WHITE or color == "white"
        return self.white_name if white else self.black_name

    def color_of(self, user_id) -> Color | None:
        """The colour a user plays in this game, or ``None`` if they do not play in it."""
        if user_id == self.white_id:
            return Color.WHITE
        if user_id == self.black_id:
            return Color.BLACK
        return None

    @classmethod
    def from_dict(cls, data) -> "GameState":
        """Build a ``GameState`` from a decoded response dict, ignoring unknown keys."""
        return cls(**_known_fields(cls, data))

    @classmethod
    def from_row(cls, row) -> "GameState":
        """Build a ``GameState`` from the game dict the database layer returns."""
        return cls(
            fen=row["fen"],
            status=int(row["status"]),
            version=int(row["version"]),
            generation=int(row["generation"]),
            draw=int(row["draw"]) if row["draw"] is not None else None,
            termination=row["termination"],
            id=int(row["id"]),
            group_id=int(row["group_id"]),
            white_id=int(row["white_id"]),
            black_id=int(row["black_id"]),
            white_name=row["white_name"],
            black_name=row["black_name"],
            started_at=_iso(row["started_at"]),
            updated_at=_iso(row["updated_at"]),
            last_move=row.get("last_move"),
        )


@dataclass
class MoveResult:
    """The outcome of a played move: the move itself plus the resulting state.

    ``from_square``/``to_square`` are algebraic squares (e.g. ``"e2"``/``"e4"``);
    ``san`` is the move string (postable). On the wire they serialize to ``from``/
    ``to`` via :meth:`to_dict`.

    ``legal_moves`` lists the moves of the side now to move, in the shape of the
    ``legal-moves`` route (``{from, to, san, promotion}``): ``[]`` once the game has
    ended, ``None`` from a server older than 0.15.1.
    """

    state: GameState
    from_square: str
    to_square: str
    san: str
    check: bool = False
    castle: str | None = None
    promotion: str | None = None
    en_passant: bool = False
    legal_moves: list[dict] | None = None

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
            "en_passant": self.en_passant,
            "legal_moves": self.legal_moves,
        }

    @classmethod
    def from_dict(cls, data) -> "MoveResult":
        """Build a ``MoveResult`` from a decoded response dict."""
        return cls(
            state=GameState.from_dict(data["state"]),
            from_square=data["from"],
            to_square=data["to"],
            san=data["san"],
            check=data["check"],
            castle=data.get("castle"),
            promotion=data.get("promotion"),
            en_passant=data.get("en_passant", False),
            legal_moves=data.get("legal_moves"),
        )


@dataclass
class User:
    """An account, as the api-endpoint reports it. Never carries a password hash."""

    id: int
    username: str
    role: str = "user"  # "user" or "admin"
    created_at: str | None = None  # ISO 8601, UTC
    disabled_at: str | None = None
    identities: list[dict] = field(default_factory=list)  # [{"provider", "external_id"}]
    has_password: bool = False  # whether the account can log in with a password
    #: The groups whose games this user administers (0.15.4). Like ``identities``,
    #: shown only to the user themselves and to administrators.
    admin_groups: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return the payload as a plain JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> "User":
        """Build a ``User`` from a decoded response dict, ignoring unknown keys."""
        return cls(**_known_fields(cls, data))

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @classmethod
    def from_row(cls, row, *, show_identities=True) -> "User":
        """
        Build a ``User`` from the user dict the database layer returns.

        :param show_identities: ``False`` hides the linked external ids, which only
            the user themselves and administrators may see.
        """
        return cls(
            id=int(row["id"]),
            username=row["username"],
            role=ROLE_NAMES[int(row["role"])],
            created_at=_iso(row["created_at"]),
            disabled_at=_iso(row["disabled_at"]),
            identities=[dict(identity) for identity in row.get("identities", [])] if show_identities else [],
            has_password=bool(row.get("has_password", False)),
            admin_groups=[int(g) for g in row.get("admin_groups", [])] if show_identities else [],
        )


@dataclass
class Challenge:
    """A pending challenge: ``challenger`` asked ``challenged`` for a game in ``group_id``."""

    id: int
    group_id: int
    challenger_id: int
    challenger_name: str
    challenged_id: int
    challenged_name: str
    color: str = "random"  # the colour the challenger plays: "white", "black" or "random"
    created_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> "Challenge":
        return cls(**_known_fields(cls, data))

    @classmethod
    def from_row(cls, row) -> "Challenge":
        return cls(
            id=int(row["id"]),
            group_id=int(row["group_id"]),
            challenger_id=int(row["challenger_id"]),
            challenger_name=row["challenger_name"],
            challenged_id=int(row["challenged_id"]),
            challenged_name=row["challenged_name"],
            color=COLOR_NAMES[int(row["color"])],
            created_at=_iso(row["created_at"]),
        )


@dataclass
class TokenInfo:
    """A token's metadata. The secret itself is only ever in ``LoginResult.token`` or a create response."""

    id: int
    kind: str  # "session" (from logging in) or "api" (named, for scripts and bots)
    name: str | None = None
    created_at: str | None = None
    expires_at: str | None = None  # None: never expires (api tokens only)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> "TokenInfo":
        return cls(**_known_fields(cls, data))

    @classmethod
    def from_row(cls, row) -> "TokenInfo":
        return cls(
            id=int(row["id"]),
            kind=row["kind"],
            name=row["name"],
            created_at=_iso(row["created_at"]),
            expires_at=_iso(row["expires_at"]),
        )


@dataclass
class LoginResult:
    """What logging in, registering or creating an api token returns: the secret, once."""

    token: str
    token_info: TokenInfo
    user: User | None = None

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "token_info": self.token_info.to_dict(),
            "user": self.user.to_dict() if self.user is not None else None,
        }

    @classmethod
    def from_dict(cls, data) -> "LoginResult":
        user = data.get("user")
        return cls(
            token=data["token"],
            token_info=TokenInfo.from_dict(data["token_info"]),
            user=User.from_dict(user) if user is not None else None,
        )
