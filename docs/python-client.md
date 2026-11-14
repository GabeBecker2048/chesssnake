---
title: Python client
---

`pip install 'chesssnake[client]'` lets your code play games on a chesssnake
server. The server checks every move, so your program and its opponent always
agree on the game.

```python
from chesssnake import Game, connect

client = connect("https://chess.example", username="alice", password="...")
state = client.current_games()[0]         # a game in progress
game = Game.remote(state, client=client)
game.move("e4")
```

## Connecting

`connect(api_url)` returns a logged-in client. It takes the first of these it
finds:

1. `username=` and `password=`
2. `token=`, an [api token](accounts.html#logins-and-api-tokens): the right choice for a script
3. the `CHESSSNAKE__CLIENT__TOKEN` environment variable
4. the login `chesssnake login` stored for that server

`api_url` can be left out when `CHESSSNAKE__CLIENT__API_URL` is set. If no
login is found, it raises `AuthError`.

## Starting a game

Games start with a challenge that the other player accepts:

```python
challenge = alice.challenge("bob", color="white")     # or "black", "random"

# as bob:
bob.challenges(direction="incoming")
state = bob.accept_challenge(challenge.id)            # the game starts
# or bob.decline_challenge(challenge.id); alice can withdraw_challenge(...)
```

Players are given by username or id. Two players can have one game in progress
at a time.

## Playing

`Game.remote(game_id_or_state, client=client)` is a
[`Game`](python.html) whose moves go to the server. Everything on the Python
library page works on it: `move`, `legal_moves`, `render`, `save`, `fen`,
`pgn`, the state properties.

```python
game = Game.remote(41, client=client)

game.move("e4")          # raises the same errors as a local game
game.refresh()           # fetch the latest state, e.g. the opponent's move
game.to_move, game.is_over, game.winner

game.offer_draw()        # you act as yourself: no player id needed
game.resign()
```

Besides chess errors, a move can raise `NotYourTurnError`, and
`VersionConflictError` when the game changed since you last looked: call
`refresh()` and decide again. These are in `chesssnake.db.errors`.

A finished game keeps its id and stays readable. A rematch is a new challenge.

## Waiting for the opponent

Either poll:

```python
import time

while game.to_move != my_color and not game.is_over:
    time.sleep(5)
    game.refresh()
```

or, when the server has [live updates](live-updates.html) on, be told:

```python
import select

with client.events(games=[game.id]) as stream:    # RealtimeUnavailable if they are off
    while not game.is_over:
        select.select([stream.fileno()], [], [])
        for event in stream.drain():
            if event["type"] == "game":
                game.refresh()
```

The stream reconnects by itself. The events are described in
[Websocket API](websocket-api.html#messages-you-receive); the stream adds
`disconnected`, `reconnected`, `ended` and `auth_error` of its own.

## Everything else

The client has a method for everything the server can do.

| | Methods |
|---|---|
| You | `me()`, `change_password(current, new)`, `settings()`, `update_settings(...)`, `logout()` |
| Tokens | `create_token(name, current_password, expires_in_days=None)`, `tokens()`, `revoke_token(id)` |
| Challenges | `challenge(opponent, group_id=0, color="random")`, `challenges(direction="all")`, `get_challenge(id)`, `accept_challenge(id)`, `decline_challenge(id)`, `withdraw_challenge(id)` |
| Finding games | `current_games()`, `get_game(id)`, `games_between(a, b)`, `record(a, b)` |
| One game | `move(id, move)`, `resign(id)`, `offer_draw(id)`, `accept_draw(id)`, `decline_draw(id)`, `legal_moves(id)`, `history(id)`, `pgn(id)`, `fen(id)`, `image(id, perspective=None)` |
| Users | `get_user(name_or_id)` |
| Administrators | `create_user(username, password=None, role="user")`, `update_user(id, username=, role=, disabled=, password=)`, `create_game(white, black)`, `delete_game(id)`, and the identity methods in [Bots](bots.html) |

They return small objects with the same fields as the
[REST API's data](rest-api.html#data): `GameState`, `MoveResult`, `User`,
`Challenge`.

```python
client.record("alice", "bob")
# {"player1": 1, "player2": 2, "player1_wins": 3, "player2_wins": 1, "draws": 2}

open("board.png", "wb").write(client.image(41, perspective="white"))
```
