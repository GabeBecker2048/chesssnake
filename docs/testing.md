---
title: Testing
---

`chesssnake.testing` runs a real chesssnake server inside your tests: the same
server, rules and errors as production, on a throwaway database, with no
network and no setup. Use it to test a bot or any program built on the
[Python client](python-client.html).

It needs the server installed alongside the client:

```sh
pip install 'chesssnake[api,client]'
```

## With pytest

Turn on the plugin in your `conftest.py`:

```python
pytest_plugins = ["chesssnake.testing.pytest_plugin"]
```

and use its fixtures:

```python
def test_a_bot_move(chesssnake_server, chesssnake_admin):
    alice = chesssnake_server.user("alice")
    bob = chesssnake_server.user("bob")
    game = chesssnake_admin.create_game(alice, bob)
    result = chesssnake_admin.as_user(alice).move(game, "e4")
    assert result.state.last_move["san"] == "e4"
```

| Fixture | What it is |
|---|---|
| `chesssnake_server` | The server. One per test session, emptied before each test. |
| `chesssnake_admin` | An `ApiClient` logged in as the server's administrator. |
| `chesssnake_async_admin` | The same, as an `AsyncApiClient`. |

## Without pytest

```python
from chesssnake.testing import TestServer

with TestServer() as server:
    admin = server.client()                        # the administrator
    alice = server.user("alice", password="alice-password")
    as_alice = server.client(alice)                # logged in as alice
    bot = server.client(asynchronous=True)         # an AsyncApiClient
```

| | |
|---|---|
| `server.user(name, password=None, admin=False)` | Make an account and return its `User`. Without a password it can only use tokens, and is made at once. |
| `server.client(user=None, asynchronous=False)` | A client logged in as `user`, or as the administrator. |
| `server.token(user=None)` | An api token for `user`, or the administrator's. |
| `server.admin` | The administrator's `User`. |
| `server.reset()` | Empty every table and make a fresh administrator. |

## Live updates

The in-process server has no real network, so websockets need
`TestServer(live=True)`, which also serves it on a free local port
(`server.url`). Clients from `server.client()` then talk HTTP to it:

```python
with TestServer(live=True) as server:
    alice, bob = server.user("alice"), server.user("bob")
    bot = server.client(asynchronous=True)
    async with bot.events() as stream:
        await stream.follow(all=True)
        ...
```

> The server's database connection is shared by the whole process, so run one
> `TestServer` at a time.
{: .warn }
