---
title: Install
---

There are two things to install, and you may only need one:

- **The server**, which keeps accounts and games and serves the web UI. Run it
  in [Docker](#the-server-in-docker) or [with pip](#the-server-with-pip).
- **The Python package**, to play in a terminal or write code against a server
  or with no server at all. See [The Python package](#the-python-package).

## The server in Docker

Save this as `docker-compose.yml` in a new folder:

```yaml
services:
  chesssnake:
    image: ghcr.io/gabebecker2048/chesssnake:latest   # or :0.15 to stay on 0.15.x
    restart: unless-stopped
    user: "1000:1000"              # who owns ./data (`id -u`:`id -g`)
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    environment:
      # Four slashes: an absolute path inside the container.
      CHESSSNAKE__DATABASE__URL: sqlite:////data/chesssnake.db
      CHESSSNAKE__DATABASE__INIT_SCHEMA: "1"
      # Let anyone make their own account:
      # CHESSSNAKE__API__REGISTRATION: "open"
    # Hardening: the server only writes to /data.
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 512m
```

Then, in that folder:

```sh
mkdir data           # so it is yours, not root's
docker compose up -d
docker compose exec chesssnake chesssnake user create yourname --admin
```

The last command makes the first account and asks for its password. Open
`http://<host>:8000/` and log in.

- That is the whole server. The database is one SQLite file under `./data`. To
  use PostgreSQL instead, see [Database](database.html).
- `user:` must match the owner of `./data` (`id -u` and `id -g`).
- Every setting can be given under `environment:`. See
  [Configuration](configuration.html).
- Run any [command](cli.html) inside the container with
  `docker compose exec chesssnake chesssnake <command>`.
- Before putting it on the internet, read [Hosting publicly](hosting-publicly.html).

### Image tags

Images are published to `ghcr.io/gabebecker2048/chesssnake` for amd64 and arm64.

| Tag | What you get |
|---|---|
| `latest` | the newest release |
| `0.15` | the newest 0.15.x |
| `0.15.3` | exactly that release |

## The server with pip

Requires Python 3.12 or newer.

```sh
pip install 'chesssnake[api]'
export CHESSSNAKE__DATABASE__URL='sqlite:///chesssnake.db'
chesssnake init-db                              # create the tables
chesssnake user create yourname --admin         # the first account; asks for a password
chesssnake api-endpoint --host 0.0.0.0
```

Open `http://<host>:8000/` and log in.

- The database URL can also live in a config file: `chesssnake config init`
  writes a `chesssnake.toml` with every setting explained. See
  [Configuration](configuration.html).
- Without `--host 0.0.0.0` the server only accepts connections from the same
  machine.
- To keep it running, use whatever runs your other services: a systemd unit, a
  `tmux` session, or the Docker image.

## The Python package

Requires Python 3.12 or newer.

```sh
pip install chesssnake                  # local games and board images
pip install 'chesssnake[client]'        # also play on a server
pip install 'chesssnake[api]'           # also run a server (SQLite)
pip install 'chesssnake[api,postgres]'  # also run a server on PostgreSQL
```

The plain install is enough to play offline, straight away:

```sh
chesssnake play --local
```

See [In the terminal](terminal.html) and [Python library](python.html).

## Check it works

```sh
curl http://localhost:8000/health        # {"status":"ok"}
```

Then follow [Your first game](first-game.html).

## Updating

| Install | Update with |
|---|---|
| Docker | `docker compose pull && docker compose up -d` |
| pip | `pip install -U chesssnake` |

Read [Upgrading and backups](upgrading.html) first: before 1.0.0 some releases
need the database recreated.
