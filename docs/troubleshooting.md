---
title: Troubleshooting
---

Start with what the server itself says:

```sh
docker compose logs chesssnake       # or the terminal the server runs in
chesssnake config show               # every setting in effect, and where it came from
curl http://localhost:8000/health    # {"status":"ok"} when it is up
```

## The server will not start

| It says | Fix |
|---|---|
| `No database connection string is configured` | Set `database.url`. See [Database](database.html). |
| `This database is missing tables` | Run `chesssnake init-db`, or set `database.init_schema = true`. Nothing is lost. |
| `This database was created by an older chesssnake and its schema has changed` | See [When a version changes the database](upgrading.html#when-a-version-changes-the-database). |
| `Invalid configuration: ... Extra inputs are not permitted` | A misspelt or renamed key in the config file. The message names it. |
| `Ignoring unknown setting variable` | The same, for an environment variable. Names are `CHESSSNAKE__SECTION__KEY`, with double underscores. |
| A permission error on `/data` (Docker) | `./data` must belong to the `user:` in the compose file. Run `mkdir data` before the first start, or `chown` it. |
| `psycopg2 is no longer supported` | Install `chesssnake[api,postgres]` and use a plain `postgresql://` URL. |
| An in-memory SQLite database is refused | Use a file: `sqlite:///chesssnake.db`. |
| `requires pydantic` or `requires FastAPI` | The server needs `pip install 'chesssnake[api]'`. |

## I cannot log in

- **`invalid username or password`** is the answer to every failed login,
  whichever part was wrong. An account made with `--no-password` cannot log in
  with a password at all.
- **"Accounts are made by an administrator"** on the login page means
  registration is closed. See [Accounts](accounts.html#letting-people-register).
- **Forgot the admin password?** On the server's machine:
  `chesssnake user set-password yourname`.
- **Logged out unexpectedly?** Logins last 30 days, and end when your password
  is changed or reset.

## Moves do not show up until a few seconds later

Live updates are off or not getting through. The dot beside your name in the
web UI says which:

- **Grey:** they have been turned off on the server. They are on by default:
  see [Live updates](live-updates.html#turning-them-off).
- **Amber:** they are on, and the connection fails. Almost always a reverse
  proxy that does not pass websockets:
  see [Behind a reverse proxy](live-updates.html#behind-a-reverse-proxy).

## The terminal client

| It says | Fix |
|---|---|
| `Which api-endpoint?` | Pass `--api-url URL`, or set `CHESSSNAKE__CLIENT__API_URL`. |
| `Not logged in to ...` | Run `chesssnake login`. |
| `Could not reach the api-endpoint` | Check the address, and that the server is up (`/health`). |
| `requires requests` | `pip install 'chesssnake[client]'` |
| `note: no live updates` | Not an error: they are off on the server or not getting through a proxy, and `play` checks on a timer instead. |
| Boxes instead of chess pieces | Your terminal font lacks them. Use `--ascii`. |

## Challenges and games

- **"There is already a game in progress between you"**: two players can have
  one game at a time (per group, for bots that use groups). Finish or resign it
  first.
- **A challenge is already pending**: accept theirs, or withdraw yours, on the
  Play page.
- **A game is stuck because someone left**: an administrator can delete it
  from **Admin**, **Games**.

## The server answers 503

It is busy: every database connection is in use, or too many logins are being
checked at once. A retry a moment later works. If it happens often, raise
`database.pool_max_size`.

## Still stuck?

[Open an issue](https://github.com/GabeBecker2048/chesssnake/issues) with the
version (`/v1/info` shows it), what you did, and what the log says.
