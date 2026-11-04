# Configuration

Every chesssnake setting is declared once, in `src/chesssnake/config.py`. Defaults,
types, help text, and environment variable names all derive from that one
declaration, so there is no mapping table to drift out of sync.

## Precedence

Settings are resolved from four layers. Later layers win:

| Priority | Layer | Example |
|---|---|---|
| 1 (highest) | Command-line flag | `chesssnake api-endpoint --port 9000` |
| 2 | Environment variable | `CHESSSNAKE__API__PORT=9000` |
| 3 | TOML config file | `[api]` / `port = 9000` |
| 4 (lowest) | Built-in default | `8000` |

To see the effective value of everything **and where each one came from**:

```commandline
chesssnake config show
```

```
[api]
  host           127.0.0.1  (default)
  port           9001       (env: CHESSSNAKE__API__PORT)
  registration   open       (file: /etc/chesssnake/chesssnake.toml)
  session_lifetime_days  30  (default)
```

Credentials are redacted; pass `--show-secrets` to print them. `--format json`
emits the same information for scripts.

## Environment variable names

A key `k` in section `s` is always read from `CHESSSNAKE__{S}__{K}`, uppercased,
with a **double** underscore between the prefix, section, and key:

```
[api] port            ->  CHESSSNAKE__API__PORT
[database] pool_max_size  ->  CHESSSNAKE__DATABASE__POOL_MAX_SIZE
```

Underscores inside a key name are preserved, so the mapping round-trips
unambiguously. A `CHESSSNAKE__*` variable that does not name a real setting is
reported as a warning rather than silently ignored.

## Settings

| Section | Key | Type | Default | Description |
|---|---|---|---|---|
| `api` | `host` | string | `127.0.0.1` | Address the api-endpoint binds to. |
| `api` | `port` | integer | `8000` | Port the api-endpoint binds to. |
| `api` | `registration` | `closed` or `open` | `closed` | Who can create an account: only administrators, or anyone through `POST /v1/auth/register`. |
| `api` | `session_lifetime_days` | integer (days) | `30` | How long a login lasts, 1 to 3650. |
| `database` | `url` | string | unset | Connection **URL**; the scheme selects the backend. |
| `database` | `pool_min_size` | integer | `1` | Minimum pooled connections. |
| `database` | `pool_max_size` | integer | `10` | Maximum pooled connections. |
| `database` | `init_schema` | boolean | `false` | Create any missing tables when the server starts. Existing tables are never altered; recreate them with `chesssnake init-db --drop` after a release that changes the schema. |
| `database` | `sqlite_busy_timeout` | integer (ms) | `5000` | How long a blocked SQLite writer waits. Ignored on PostgreSQL. |
| `websocket` | `enabled` | boolean | `false` | Serve real-time updates at `/v1/ws`. See [Websockets](#websocket). |
| `websocket` | `max_connections` | integer | `1000` | Open websockets in total, counted from accept. |
| `websocket` | `max_pending_auth` | integer | `100` | Websockets connected but not yet logged in. At most `max_connections`. |
| `websocket` | `max_connections_per_user` | integer | `10` | Open websockets per user. At most `max_connections`. |
| `websocket` | `max_subscriptions` | integer | `64` | Games one websocket may follow. |
| `websocket` | `auth_timeout_seconds` | number | `10` | Time a new websocket has to send its token. |
| `websocket` | `reauth_interval_seconds` | number | `60` | How often an open websocket's token is checked again (+/-10%). |
| `websocket` | `send_queue_size` | integer | `256` | Messages buffered per websocket before it is closed (`1013`). |
| `websocket` | `ping_interval_seconds` | number | `20` | Protocol pings that keep proxies from idling a socket out; `0` disables. |
| `websocket` | `ping_timeout_seconds` | number | `20` | Close a socket whose ping goes unanswered this long. At least 1. |
| `websocket` | `max_message_bytes` | integer | `65536` | Largest message accepted from a client. At least 1024. |
| `websocket` | `compression` | boolean | `false` | permessage-deflate. Costs memory per socket; messages are small. |
| `websocket` | `worker_threads` | integer | `4` | Threads for websocket database work, apart from the REST routes' threads. |
| `websocket` | `shutdown_timeout_seconds` | number | `5` | How long open connections get on shutdown. |
| `websocket` | `allowed_origins` | list of strings | `["*"]` | Browser origins allowed to connect. Comma-separated in the environment. |
| `web` | `enabled` | boolean | `true` | Serve the [web UI](web-ui.md) at `/`. See [Web UI](#web-ui). |
| `client` | `api_url` | string | unset | Base URL a remote `Game` connects to. **Environment only.** |
| `client` | `token` | string | unset | Bearer token the Python client and `chesssnake play` send, instead of the one `chesssnake login` stored. Secret. **Environment only.** |

Booleans accept `1`/`true`/`yes`/`on` and `0`/`false`/`no`/`off` from the
environment; the config file uses real TOML booleans.

## Choosing a backend

The `database.url` scheme selects the backend. There is no separate "which
database" setting to drift out of sync with the connection details.

**SQLite**, one file with no database server to run:

```toml
[database]
url = "sqlite:///chesssnake.db"          # relative to the working directory
# url = "sqlite:////var/lib/chesssnake/chess.db"   # absolute (note four slashes)
```

Count the slashes: three means a relative path, four means absolute. A relative
path resolves against the process's working directory, so a service started from
a different directory silently opens a different database. Prefer the absolute
form for anything long-lived.

SQLite is configured for concurrent use: WAL journaling so readers don't block the
writer, a `busy_timeout`, and an immediate write lock for read-modify-write
operations. That makes it correct for **one api-endpoint process serving many
clients**. It is not suitable for several worker processes writing at once, and it
must not live on a network filesystem, where its locking is unreliable.

An **in-memory** database (`sqlite://`, or `sqlite:///:memory:`) is refused by the
api-endpoint. It cannot be shared safely between the threads that serve requests, and
it is discarded when the process exits. Use a file path.

### Pool sizing

Requests are served by a pool of worker threads, so several can be in the database at
once. `pool_max_size` (default 10) caps how many connections they share; beyond that,
a request waits for one to be returned. `pool_min_size` (default 1) is how many stay
open between requests, and the rest are opened and closed on demand, so a busy server
with the default repeatedly reopens connections. That costs little on SQLite and a
TCP connect plus authentication on PostgreSQL, so a deployment under steady load is
worth setting `pool_min_size` closer to the concurrency it actually sees.

Neither knob is the usual ceiling. CPU-bound work like board rendering is limited by
Python's global interpreter lock, measured here at roughly a 3x speedup rather than a
linear one, and concurrent *writes* to one SQLite database serialize on its single
write lock by design. Going beyond that means several worker processes, which means
PostgreSQL.

**PostgreSQL**, which needs a server and the `postgres` extra:

```commandline
pip install 'chesssnake[api,postgres]'
```

```toml
[database]
url = "postgresql://user:password@localhost:5432/chesssnake"
```

Use it for multiple workers, or when the database lives on another host.

Only URL-form connection strings are accepted. libpq keyword strings
(`dbname='chess' user='u'`) worked before 0.9.0 and no longer do; the startup
error shows the URL to use instead.

## Authentication

Every `/v1` route except logging in and registering needs a login; there is no
setting to turn that off. Accounts have a username and an Argon2id-hashed
password, and log in for a bearer token. The settings decide who can make an
account and how long a login lasts:

```toml
[api]
registration = "closed"        # "open": anyone can register
session_lifetime_days = 30
```

The first administrator is made on the server's machine, straight in the database:

```commandline
chesssnake user create yourname --admin
```

The shared key of 0.11 and earlier (`api.require_auth`, `api.api_key`) is gone. A
config file that still sets either is rejected at startup, and the environment
variables warn as unknown, so a stale setting is noticed rather than ignored. How
logins, tokens and roles work is in the [REST reference](rest-api.md#authentication).

## Websocket

Real-time updates are opt-in. Turning them on adds one route, `/v1/ws`, on the
same host and port as everything else:

```toml
[websocket]
enabled = true
allowed_origins = ["https://chess.example"]   # where your web frontend is served from
```

With them off (the default) the upgrade is refused with HTTP 403 and clients
poll, so a REST-only deployment does not need to think about this section.

- **Origins.** Browsers send an `Origin` header; `allowed_origins` lists the ones
  that may connect. Anything else (`chesssnake play`, a bot) sends none and is
  always allowed, because the token is what really guards a socket. Entries are
  compared without case or a trailing slash, `"*"` allows any and cannot be mixed
  with other entries, and in the environment the list is comma-separated:
  `CHESSSNAKE__WEBSOCKET__ALLOWED_ORIGINS=https://a.example,https://b.example`.
- **Limits.** `max_connections`, `max_pending_auth` and `max_connections_per_user`
  bound how many sockets can be open, with connections that have not logged in
  yet capped separately so they cannot hold every slot. An idle socket costs
  about 56 KiB.
- **Transport.** `ping_interval_seconds`, `ping_timeout_seconds`,
  `max_message_bytes`, `compression` and `shutdown_timeout_seconds` are passed to
  uvicorn by `chesssnake api-endpoint`. Under your own ASGI server
  ([below](#deploying-under-your-own-asgi-server)) pass the equivalent uvicorn
  flags yourself; the app still enforces `max_message_bytes` on its own.
- **One process.** Updates reach the sockets of the process that saved the
  change, so run a single api-endpoint process when websockets are on.

The protocol is in [Real-time updates](realtime-websockets.md).

## Web UI

The browser frontend is served at `/` unless turned off:

```toml
[web]
enabled = false
```

or `CHESSSNAKE__WEB__ENABLED=0`. It is only a client of `/v1`, so it needs no
settings of its own. Turn on [`[websocket]`](#websocket) as well and its boards
update the moment a move is made; without it the page polls every few seconds.
Since the page is served from the same origin as the websocket, the default
`allowed_origins = ["*"]` works, and so does a list naming the site's own
address. See [the web UI](web-ui.md).

## The config file

Discovery order, first match wins:

1. `--config PATH`
2. `CHESSSNAKE_CONFIG`
3. `./chesssnake.toml`
4. `$CHESSSNAKE_HOME/chesssnake.toml`
5. `~/.config/chesssnake/chesssnake.toml`

Finding no file is fine, because the defaults stand alone. A file named explicitly by
(1) or (2) that does not exist *is* an error, since you asked for that file
specifically.

`CHESSSNAKE_CONFIG` and `CHESSSNAKE_HOME` use a **single** underscore, because
they are read before the schema is applied and are therefore not settings
themselves.

Unknown keys are rejected:

```
Invalid configuration:
  api.prot: Extra inputs are not permitted (set by file: ./chesssnake.toml)
```

### Creating one

```commandline
chesssnake config init
```

This writes a fully commented `chesssnake.toml` describing every setting, its
accepted values, and its default, to:

- `$CHESSSNAKE_HOME/chesssnake.toml` when `CHESSSNAKE_HOME` is set, creating the
  directory if needed;
- otherwise `./chesssnake.toml` in the working directory.

Both are locations the search above covers, so the file takes effect immediately.
Every value it contains is the built-in default, so the file changes nothing until
you edit it, and deleting a line just falls back to the same value. `database.url`,
which has no default, ships commented out.

It refuses to overwrite an existing file; pass `--force` to replace one. If you
write to `$CHESSSNAKE_HOME` while a `./chesssnake.toml` also exists, it warns,
the working directory is searched first and would win.

## Setting anything from the command line

Named flags exist for the common settings (`--host`, `--port`, `--registration`,
`--database-url`). Any other setting can be overridden with
`-o`/`--set`, which needs no bespoke flag:

```commandline
chesssnake api-endpoint -o database.pool_max_size=20
```

A named flag beats `-o` for the same key.

## Notes for library users

The `[client]` section is **environment-only**. A remote `Game` reads
`CHESSSNAKE__CLIENT__API_URL` and `CHESSSNAKE__CLIENT__TOKEN` directly and never
looks for a config file: a library that read `./chesssnake.toml` out of the
caller's working directory would be surprising, and it would put pydantic on the
dependency-free local-game path. Putting `[client]` in a config file is an error
rather than a value that would be silently ignored.

For the same reason, `chesssnake config show` needs the `api` extra
(`pip install 'chesssnake[api]'`), which is where pydantic lives, including when
all you want to inspect is the `[client]` section.

## Deploying under your own ASGI server

```commandline
uvicorn chesssnake.api.server:create_app --factory --host 0.0.0.0 --port 8000
```

`chesssnake.api.server:app` also works. Command-line flags obviously cannot reach
the server this way, and the same is true of `uvicorn --reload`/`--workers`, which
re-import in a fresh process. Use the environment or a config file for those
deployments. `CHESSSNAKE_CONFIG` is how you point at a specific file.

With websockets on, give uvicorn the transport settings that `chesssnake
api-endpoint` would have passed, e.g. `--ws-ping-interval 20 --ws-ping-timeout 20
--ws-max-size 65536 --timeout-graceful-shutdown 5`, and do not use `--workers`
(see [Websocket](#websocket)).
