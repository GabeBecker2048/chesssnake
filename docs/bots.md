---
title: Bots
---

A bot, such as a Discord bot, lets people play through it: they type a move in
a chat, and the bot plays it for them and posts the board. chesssnake is built
for this. The bot needs no chess logic, and its players need no passwords.

The examples use the [Python client](python-client.html); every call is also a
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
from chesssnake import Game, connect

client = connect("https://chess.example", token="css_...")
```

It has to be an administrator to act for other players.

## 2. Map your users onto chesssnake users

Your platform has its own ids. One call turns one into a chesssnake user,
creating it the first time and finding it every time after:

```python
user = client.get_or_create_user_by_identity("discord", member.id, member.name)
user.id          # the chesssnake user id
```

The first argument is a name of your choosing for where the id comes from. If
the username is taken, the call fails with `UserExistsError`: try another name.

Someone who already has a chesssnake account can be linked to it instead, so
their bot games and their browser games are the same account:

```python
client.link_identity(user_id, "discord", member.id)      # e.g. behind a /link command
client.get_user_by_identity("discord", member.id)        # who is this?
client.unlink_identity(user_id, "discord", member.id)
```

## 3. Act for a player

Pass `player_id` to act as that player:

```python
white = client.get_or_create_user_by_identity("discord", alice.id, alice.name)
black = client.get_or_create_user_by_identity("discord", bob.id, bob.name)

# Start a game directly, or go through a challenge the other player accepts:
state = client.create_game(white.id, black.id, group_id=guild.id)
# challenge = client.challenge(black.id, group_id=guild.id, player_id=white.id)
# state = client.accept_challenge(challenge.id, player_id=black.id)

result = client.move(state.id, "e4", player_id=white.id)
client.resign(state.id, player_id=black.id)
```

The server still enforces whose turn it is: a move for the wrong player raises
`NotYourTurnError`. An illegal move raises the matching
[chess error](moves.html#when-a-move-is-refused), whose message is fit to post
back to the player.

## 4. Post the board

```python
png = client.image(state.id)                       # both sides and the names
png = client.image(state.id, perspective="white")  # one board
```

`png` is the bytes of a PNG, ready to upload. `result.san` is the move as
text, and `result.state.status` and `.termination` say whether and how the
game ended.

## Groups

`group_id` keeps communities apart. Two players can have one game in progress
per group, so use something like the Discord server's id: the same two people
can then play in two servers at once. Games made in the web UI are in group
`0`.

```python
client.current_games(player=white.id, group_id=guild.id)
client.games_between(white.id, black.id, group_id=guild.id, status="active")
client.record(white.id, black.id, group_id=guild.id)     # wins, losses, draws
```

## Good to know

- Games made by a bot show up in the web UI like any other, and can be watched
  there. A linked player can log in and carry on in the browser.
- Send `expected_version` with moves if two messages could race: see
  [REST API](rest-api.html#safe-retries).
- With [live updates](live-updates.html) on, a bot can be told about moves
  instead of asking: see [Python client](python-client.html#waiting-for-the-opponent).
