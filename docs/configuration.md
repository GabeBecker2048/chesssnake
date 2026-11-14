---
title: Configuration
---

Every setting has a working default except the database URL. Each can be set
in a config file, as an environment variable, or on the command line.

## Where settings come from

When a setting is given in more than one place, the higher one wins:

| | Place | Example |
|---|---|---|
| 1 | Command line | `chesssnake api-endpoint --port 9000` |
| 2 | Environment variable | `CHESSSNAKE__API__PORT=9000` |
| 3 | Config file | `[api]` then `port = 9000` |
| 4 | Built-in default | `8000` |

To see what is in effect, and where each value came from:

```sh
chesssnake config show
```

```
[api]
  host                      127.0.0.1  (default)
  port                      9001       (env: CHESSSNAKE__API__PORT)
  registration              open       (file: /etc/chesssnake/chesssnake.toml)
```

Passwords in it are hidden unless you add `--show-secrets`.

### Environment variables

A setting `key` in section `[section]` is always
`CHESSSNAKE__SECTION__KEY`: upper case, with **two** underscores before the
section and before the key.

```
[api] port                 ->  CHESSSNAKE__API__PORT
[database] pool_max_size   ->  CHESSSNAKE__DATABASE__POOL_MAX_SIZE
```

On/off settings take `1`, `true`, `yes`, `on` or `0`, `false`, `no`, `off`.
Lists are separated by commas.

### The config file

```sh
chesssnake config init
```

writes a `chesssnake.toml` with every setting, its default and an explanation,
into the current folder (or `$CHESSSNAKE_HOME` if that is set). `--force`
replaces an existing one.

The server uses the first file it finds:

1. the path given to `--config`
2. the path in the `CHESSSNAKE_CONFIG` environment variable
3. `./chesssnake.toml`, in the folder the server starts from
4. `$CHESSSNAKE_HOME/chesssnake.toml`
5. `~/.config/chesssnake/chesssnake.toml`

Having no file is fine. A misspelt key in the file stops the server at
start-up and names the key.

### The command line

`--host`, `--port`, `--registration` and `--database-url` have flags of their
own. Any setting can be given with `-o`:

```sh
chesssnake api-endpoint -o database.pool_max_size=20 -o api.registration=open
```

## Server
{: #api}

`[api]`

| Key | Default | |
|---|---|---|
| `host` | `127.0.0.1` | The address the server listens on. `127.0.0.1` accepts only the same machine; `0.0.0.0` accepts anyone. The Docker image uses `0.0.0.0`. |
| `port` | `8000` | The port it listens on. |
| `registration` | `closed` | `closed`: only administrators make accounts. `open`: anyone can sign up. See [Accounts](accounts.html#letting-people-register). |
| `session_lifetime_days` | `30` | How long a login lasts, 1 to 3650 days. |
| `docs` | `true` | Serve the interactive API docs at `/docs` and `/redoc`. They need no login and hold no data, but describe every route. |

## Database

`[database]`. See [Database](database.html).

| Key | Default | |
|---|---|---|
| `url` | none | Where the database is. `sqlite:///file.db` or `postgresql://user:password@host:5432/name`. **Required.** |
| `init_schema` | `false` | Create any missing tables when the server starts. Never changes tables that exist. |
| `pool_min_size` | `1` | Database connections kept open when idle. |
| `pool_max_size` | `10` | Database connections at most. |
| `sqlite_busy_timeout_ms` | `5000` | SQLite only: how long a write waits for another to finish, in milliseconds. |

## Live updates
{: #websocket}

`[websocket]`. See [Live updates](live-updates.html). They are on by default,
and most servers need none of these.

| Key | Default | |
|---|---|---|
| `enabled` | `true` | Serve live updates. `false` turns them off, and clients check on a timer instead. |
| `allowed_origins` | `["*"]` | Which web pages may connect, by address, such as `["https://chess.example"]`. `*` allows any. Only matters for browsers; the built-in web UI always works with the default. |
| `max_connections` | `1000` | Open connections in total. |
| `max_connections_per_user` | `10` | Open connections per user. |
| `max_pending_auth` | `100` | Connections that have not logged in yet. |
| `max_subscriptions` | `64` | Games one connection may follow. |
| `auth_timeout_seconds` | `10` | How long a new connection has to log in. |
| `reauth_interval_seconds` | `60` | How often an open connection's login is checked again. |
| `ping_interval_seconds` | `20` | How often the server pings each connection, which keeps proxies from closing idle ones. `0` turns it off. |
| `ping_timeout_seconds` | `20` | Close a connection whose ping goes unanswered this long. |
| `max_message_bytes` | `65536` | The largest message a client may send. |
| `send_queue_size` | `256` | Messages that may wait to go out on one connection before it is closed. |
| `compression` | `false` | Compress messages. Costs memory per connection and saves little. |
| `worker_threads` | `4` | Threads that serve live connections. |
| `shutdown_timeout_seconds` | `5` | How long open connections get when the server stops. |

In the environment, `allowed_origins` is comma-separated:
`CHESSSNAKE__WEBSOCKET__ALLOWED_ORIGINS=https://a.example,https://b.example`.

## Web UI
{: #web}

`[web]`

| Key | Default | |
|---|---|---|
| `enabled` | `true` | Serve the [web UI](browser.html) at `/`. Turn off for a server only bots use. |

## Client

These are for the machine you play **from**: `chesssnake play`, the other
client commands, and the [Python client](python-client.html). They are read
from the environment only, never from a config file.

| Variable | |
|---|---|
| `CHESSSNAKE__CLIENT__API_URL` | The server's address, so you can leave out `--api-url`. |
| `CHESSSNAKE__CLIENT__TOKEN` | A token to use instead of the stored login. For scripts. |

## Other environment variables

| Variable | |
|---|---|
| `CHESSSNAKE_CONFIG` | The config file to use. |
| `CHESSSNAKE_HOME` | The folder for the config file and for stored logins, instead of `~/.config/chesssnake`. |

These two have a single underscore.

## Running under your own ASGI server

`chesssnake api-endpoint` is the usual way to run the server. To run the app
under uvicorn yourself:

```sh
uvicorn chesssnake.api.server:create_app --factory --host 0.0.0.0 --port 8000
```

Settings then come from the environment or a config file only. With live
updates on, do not use `--workers`, and pass the connection settings to
uvicorn yourself:
`--ws-ping-interval 20 --ws-ping-timeout 20 --ws-max-size 65536 --timeout-graceful-shutdown 5`.
