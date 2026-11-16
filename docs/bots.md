---
title: Bots
---

A bot, such as a Discord bot, lets people play through it: they type a move in
a chat, and the bot plays it for them and posts the board. chesssnake is built
for this. The bot needs no chess logic, and its players need no passwords.

The examples use the [Python client](python-client.html), mostly its async
form, since chat libraries are asyncio. Every call is also a
[REST](rest-api.html) route.

## 1. Give the bot an account

On the server's machine, make an administrator with no password and an api
token for it:

```sh
chesssnake user create discord-bot --admin --no-password
chesssnake user token discord-bot --name bot      # prints the token, once
```

The bot connects with that token:

```python
from chesssnake import connect

client = connect("https://chess.example", token="css_...", asynchronous=True)
```

It has to be an administrator to act for other players.

## 2. Act as a player

Your platform has its own ids. `as_identity` gives a client that acts as the
chesssnake user linked to one of them:

```python
alice = client.as_identity("discord", member.id, create_as=member.name)
```

The first argument is a name of your choosing for where the id comes from.
With `create_as`, a user is made the first time, named after it; if the name
is taken it becomes `name_1`, `name_2` and so on. Without it, an unknown id
raises `UserNotFoundError`, which is how a bot asks people to sign up first.
The user is looked up once, then remembered.

Everything that acts takes the player from there:

```python
game = await alice.game_against(bob, group_id=guild.id)   # their one game, or None
result = await alice.move(game, "e4")
await alice.offer_draw(game)
await alice.challenge(bob, group_id=guild.id)             # bob is another as_identity
await bob.accept_challenge(challenge)
```

`client.as_user(user_id)` does the same for a chesssnake id. Underneath, each
call passes `player_id`, which you can also pass yourself to any action. The
server still enforces whose turn it is: a move for the wrong player raises
`NotYourTurnError`. An illegal move raises the matching
[chess error](moves.html#when-a-move-is-refused), whose message is fit to post
back to the player.

## 3. Let people link their account

Someone who already plays in the browser can use the same account through the
bot. They make a link code on their Account page (or with `chesssnake
link-code`) and give it to the bot, for example with a `/link` command whose
argument only they can see:

```python
user, previous_user_id = await client.redeem_link_code("discord", member.id, code)
```

The code proves the account is theirs without the bot ever seeing a password.
It works once and expires after ten minutes. If the Discord id was linked to
another account (one the bot made for them earlier), the link moves and that
account's games stay with it. Linking directly, without a code, is also there
for administrators:

```python
await client.link_identity(user_id, "discord", member.id)
await client.unlink_identity(user_id, "discord", member.id)
await client.get_user_by_identity("discord", member.id)        # who is this?
```

## 4. Post the board

```python
png = await client.image(game)                       # both sides, the last move highlighted
png = await client.image(game, perspective="white")  # one board
```

`png` is the bytes of a PNG, ready to upload. `result.san` is the move as text,
and the state answers the rest: `state.to_move`, `state.is_over`,
`state.winner`, `state.ending`, `state.last_move` (see
[Game state](python-client.html#game-state)).

## 5. Hear about moves made elsewhere

Games made by a bot show up in the web UI, and a linked player can carry on
there. To post those moves too, follow every game:

```python
me = await client.me()
async with client.events() as stream:
    await stream.follow(all=True)
    async for event in stream:
        if event["type"] == "game" and event.get("requested_by") != me.id:
            ...   # someone moved without the bot: post the board
        elif event["type"] == "game_started":
            ...
```

Every game event says who made the change: `actor_id`, the player it was made
as, and `requested_by`, the user who sent it. The bot's own actions have its
own id in `requested_by`, which is how it skips what it already posted. When
the server has [live updates](live-updates.html) off, `events()` raises
`RealtimeUnavailable`; poll `live_games(group_id=...)` instead.

## Groups

`group_id` keeps communities apart. Two players can have one game in progress
per group, so use something like the Discord server's id: the same two people
can then play in two servers at once. Games made in the web UI are in group
`0`.

```python
await client.current_games(player=user_id, group_id=guild.id)
await client.live_games(group_id=guild.id)
await client.finished_games(group_id=guild.id)
await alice.record_against(bob, group_id=guild.id)    # wins, losses, draws
```

An administrator can make someone a [group admin](accounts.html#group-admins):
they manage the games of that one group (start and delete games, act for its
players) and nothing else. A bot can map a community's moderators onto this.

## Good to know

- Send `expected_version` with moves if two messages could race: see
  [REST API](rest-api.html#safe-retries).
- Test your bot against a real server with no setup: see [Testing](testing.html).
