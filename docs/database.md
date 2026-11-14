---
title: Database
---

The server keeps accounts and games in SQLite or PostgreSQL. One setting,
`database.url`, chooses which.

| | SQLite | PostgreSQL |
|---|---|---|
| Needs | nothing: one file | a PostgreSQL server |
| Good for | one server for a community or a bot | several server processes, or a database on another host |
| Install | `chesssnake[api]` | `chesssnake[api,postgres]` |

Start with SQLite. Moving later means changing the URL (games are not copied
across for you).

## SQLite

```toml
[database]
url = "sqlite:///chesssnake.db"                      # relative to where the server starts
# url = "sqlite:////var/lib/chesssnake/chess.db"     # absolute: four slashes
```

Count the slashes: three is a relative path, four is absolute. A relative path
depends on the folder the server was started from, so use the absolute form for
anything long-lived.

> Run only one server process on a SQLite file, and do not put the file on a
> network share (NFS, SMB). An in-memory database (`sqlite://`) is refused.
{: .warn }

## PostgreSQL

```toml
[database]
url = "postgresql://user:password@localhost:5432/chesssnake"
```

With Docker, two containers:

```yaml
services:
  chesssnake:
    image: ghcr.io/gabebecker2048/chesssnake:latest
    restart: unless-stopped
    depends_on:
      postgres: { condition: service_healthy }
    ports:
      - "8000:8000"
    environment:
      CHESSSNAKE__DATABASE__URL: postgresql://chesssnake:${POSTGRES_PASSWORD:?set it in .env}@postgres:5432/chesssnake
      CHESSSNAKE__DATABASE__INIT_SCHEMA: "1"
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]

  postgres:
    image: postgres:17
    restart: unless-stopped
    environment:
      POSTGRES_DB: chesssnake
      POSTGRES_USER: chesssnake
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set it in .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U chesssnake -d chesssnake"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pgdata:
```

Put `POSTGRES_PASSWORD=...` in a `.env` file beside it.

Only URLs are accepted, not `dbname=... user=...` strings.

## Creating the tables

The tables must exist before the server will start. Any one of these creates
them, and none of them touches tables that are already there:

| How | |
|---|---|
| `chesssnake init-db` | create them, then exit |
| `chesssnake api-endpoint --init-db` | create them as the server starts |
| `database.init_schema = true` | the same, as a setting (what the Docker examples use) |

`chesssnake init-db --create-database` also creates the PostgreSQL database
itself, or the folder for a SQLite file, if it is missing.

## Connections

`database.pool_max_size` (default 10) is how many database connections the
server opens at most, and `pool_min_size` (default 1) how many it keeps open
when idle. The defaults suit a small server. On a busy PostgreSQL server, raise
`pool_min_size` towards the number of requests it handles at once.

All database settings are in [Configuration](configuration.html#database).
