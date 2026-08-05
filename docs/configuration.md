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
  require_auth   True       (cli: --require-auth)
  api_key        ********   (file: /etc/chesssnake/chesssnake.toml)
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
| `api` | `require_auth` | boolean | `false` | Require a matching `X-API-Key` header on all `/v1` routes. |
| `api` | `api_key` | string | unset | The key clients must send as `X-API-Key`. Secret. |
| `database` | `url` | string | unset | Connection string; the scheme selects the backend. |
| `database` | `pool_min_size` | integer | `1` | Minimum pooled connections. |
| `database` | `pool_max_size` | integer | `10` | Maximum pooled connections. |
| `database` | `init_schema` | boolean | `false` | Create the schema when the server starts. |
| `client` | `api_url` | string | unset | Base URL a remote `Game` connects to. **Environment only.** |
| `client` | `api_key` | string | unset | Key a remote `Game` sends. Secret. **Environment only.** |

Booleans accept `1`/`true`/`yes`/`on` and `0`/`false`/`no`/`off` from the
environment; the config file uses real TOML booleans.

## Authentication

Authentication is **explicit**. `api.require_auth` controls whether a key is
required; setting `api.api_key` alone does nothing but earn a warning.

```toml
[api]
require_auth = true
```

Enabling `require_auth` without a key is a startup error, not a silent
downgrade — a deployment whose secret failed to inject fails loudly instead of
coming up wide open.

Supply the key through the environment rather than the file so it stays out of
version control:

```commandline
CHESSSNAKE__API__API_KEY='...' chesssnake api-endpoint --require-auth
```

## The config file

Discovery order, first match wins:

1. `--config PATH`
2. `CHESSSNAKE_CONFIG`
3. `./chesssnake.toml`
4. `$CHESSSNAKE_HOME/chesssnake.toml`
5. `~/.config/chesssnake/chesssnake.toml`

Finding no file is fine — the defaults stand alone. A file named explicitly by
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
you edit it — deleting a line just falls back to the same value. The two settings
with no default (`database.url` and `api.api_key`) ship commented out.

It refuses to overwrite an existing file; pass `--force` to replace one. If you
write to `$CHESSSNAKE_HOME` while a `./chesssnake.toml` also exists, it warns —
the working directory is searched first and would win.

## Setting anything from the command line

Named flags exist for the common settings (`--host`, `--port`, `--api-key`,
`--require-auth`, `--database-url`). Any other setting can be overridden with
`-o`/`--set`, which needs no bespoke flag:

```commandline
chesssnake api-endpoint -o database.pool_max_size=20
```

A named flag beats `-o` for the same key.

## Notes for library users

The `[client]` section is **environment-only**. A remote `Game` reads
`CHESSSNAKE__CLIENT__API_URL` and `CHESSSNAKE__CLIENT__API_KEY` directly and never
looks for a config file — a library that read `./chesssnake.toml` out of the
caller's working directory would be surprising, and it would put pydantic on the
dependency-free local-game path. Putting `[client]` in a config file is an error
rather than a value that would be silently ignored.

For the same reason, `chesssnake config show` needs the `api` extra
(`pip install 'chesssnake[api]'`), which is where pydantic lives — including when
all you want to inspect is the `[client]` section.

## Deploying under your own ASGI server

```commandline
uvicorn chesssnake.api.server:create_app --factory --host 0.0.0.0 --port 8000
```

`chesssnake.api.server:app` also works. Command-line flags obviously cannot reach
the server this way, and the same is true of `uvicorn --reload`/`--workers`, which
re-import in a fresh process. Use the environment or a config file for those
deployments — `CHESSSNAKE_CONFIG` is how you point at a specific file.
