"""
:class:`PlayerClient`: an administrator's client acting as one player.

A bot plays for many people with one admin token, passing ``player_id`` on every
action. ``client.as_user(user)`` and ``client.as_identity(provider, external_id)``
return one of these instead, which fills ``player_id`` in and defaults listings to
that player:

.. code-block:: python

    alice = client.as_identity("discord", member.id, create_as=member.name)
    game = alice.current_games(group_id=guild.id)[0]
    alice.move(game, "e4")                    # player_id is alice's
    alice.challenge("bob", group_id=guild.id)

It wraps either client: with an :class:`~chesssnake.remote.async_client.AsyncApiClient`
every method is awaitable, as on the client itself. An identity is looked up on
the first call that needs it and cached; :meth:`PlayerClient.forget` drops the cache
(after an unlink, say). Anything not defined here passes through to the wrapped
client unchanged.
"""

from __future__ import annotations

from ..dto import User


def _id(value):
    return getattr(value, "id", value)


class PlayerClient:
    """
    One player, through an administrator's client (see the module docstring).

    :param client: The ``ApiClient`` or ``AsyncApiClient`` to act through.
    :param user: The player: an id, a ``User`` or a username.
    :param identity: ``(provider, external_id)`` instead of ``user``.
    :param create_as: With ``identity``: the username to create the player with
        if nobody is linked yet (``on_conflict="suffix"``).
    """

    def __init__(self, client, *, user=None, identity=None, create_as=None):
        if (user is None) == (identity is None):
            raise ValueError("Give exactly one of user= and identity=")
        self.client = client
        self.identity = identity
        self.create_as = create_as
        self._user = user if isinstance(user, User) else None
        self._spec = user
        #: The player's user id, once known (immediately for an int or a ``User``).
        self.id: int | None = _id(user) if isinstance(_id(user), int) and not isinstance(user, bool) else None

    def __repr__(self):
        who = self.id if self.id is not None else (self.identity or self._spec)
        return f"<PlayerClient {who!r}>"

    def __getattr__(self, name):
        # Everything else is the wrapped client's.
        return getattr(self.client, name)

    # --- who ---------------------------------------------------------------------

    def forget(self) -> None:
        """Forget the cached user (resolved again on next use)."""
        if self.identity is not None or isinstance(self._spec, str):
            self.id = None
        self._user = None

    def _remember(self, user: User) -> User:
        self._user = user
        self.id = user.id
        return user

    def user(self) -> User:
        """The player's account (fetched once, then cached)."""
        c = self.client
        if self._user is not None:
            return c._done(self._user)
        if self.identity is not None:
            provider, external_id = self.identity
            if self.create_as is not None:
                found = c.get_or_create_user_by_identity(provider, external_id, self.create_as, on_conflict="suffix")
            else:
                found = c.get_user_by_identity(provider, external_id)
        else:
            found = c.get_user(self._spec)
        return c._then(found, self._remember)

    def _with_id(self, fn):
        if self.id is not None:
            return self.client._then(self.client._done(self.id), fn)
        return self.client._then(self.user(), lambda user: fn(user.id))

    # --- actions as this player -----------------------------------------------------

    def move(self, game, move, expected_version=None):
        """Play ``move`` in ``game`` (an id or a ``GameState``) as this player."""
        return self._with_id(lambda uid: self.client.move(game, move, player_id=uid, expected_version=expected_version))

    def resign(self, game, expected_version=None):
        return self._with_id(lambda uid: self.client.resign(game, player_id=uid, expected_version=expected_version))

    def offer_draw(self, game, expected_version=None):
        return self._with_id(lambda uid: self.client.offer_draw(game, player_id=uid, expected_version=expected_version))

    def accept_draw(self, game, expected_version=None):
        return self._with_id(
            lambda uid: self.client.accept_draw(game, player_id=uid, expected_version=expected_version)
        )

    def decline_draw(self, game, expected_version=None):
        return self._with_id(
            lambda uid: self.client.decline_draw(game, player_id=uid, expected_version=expected_version)
        )

    def challenge(self, opponent, group_id=0, color="random"):
        """Challenge ``opponent`` (an id, a ``User``, a username or another ``PlayerClient``)."""
        if isinstance(opponent, PlayerClient):
            return opponent._with_id(lambda other: self.challenge(other, group_id, color))
        return self._with_id(lambda uid: self.client.challenge(opponent, group_id, color, player_id=uid))

    def accept_challenge(self, challenge):
        return self._with_id(lambda uid: self.client.accept_challenge(challenge, player_id=uid))

    def decline_challenge(self, challenge):
        """Decline a challenge to this player, or withdraw one they made."""
        return self.client.decline_challenge(challenge)

    withdraw_challenge = decline_challenge

    # --- listings for this player ------------------------------------------------------

    def challenges(self, direction="all", group_id=None):
        """This player's pending challenges, in one group if ``group_id`` is given."""

        def keep(found):
            return found if group_id is None else [c for c in found if c.group_id == group_id]

        return self._with_id(lambda uid: self.client._then(self.client.challenges(direction, user_id=uid), keep))

    def current_games(self, group_id=None):
        """This player's games in progress, in one group if ``group_id`` is given."""
        return self._with_id(lambda uid: self.client.current_games(uid, group_id=group_id))

    def finished_games(self, limit=50, before=None, group_id=None):
        return self._with_id(lambda uid: self.client.finished_games(uid, limit=limit, before=before, group_id=group_id))

    def games_with(self, opponent, group_id=0, status="all"):
        """Every game between this player and ``opponent`` in a group, oldest first."""
        return self._with_id(lambda uid: self.client.games_between(uid, _other(opponent), group_id, status))

    def record_against(self, opponent, group_id=0) -> dict:
        """``{"player1_wins", "player2_wins", "draws", ...}``, this player being ``player1``."""
        return self._with_id(lambda uid: self.client.record(uid, _other(opponent), group_id))

    def game_against(self, opponent=None, group_id=0):
        """
        The game in progress this player means: the one against ``opponent``, or
        their only one in the group. ``None`` if there is no such single game.
        """

        def pick(games):
            if opponent is not None:
                other = _other(opponent)
                games = [g for g in games if other in (g.white_id, g.black_id, g.white_name, g.black_name)]
            return games[0] if len(games) == 1 else None

        return self.client._then(self.current_games(group_id), pick)


def _other(opponent):
    if isinstance(opponent, PlayerClient):
        if opponent.id is None:
            raise ValueError("Resolve the other PlayerClient first (await/call .user())")
        return opponent.id
    return _id(opponent)
