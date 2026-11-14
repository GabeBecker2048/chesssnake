---
title: Upgrading and backups
---

## Upgrading

| Install | Update with |
|---|---|
| Docker | `docker compose pull && docker compose up -d` |
| pip | `pip install -U chesssnake`, then restart the server |

Before you do, read the new version's entry in the
[changelog](https://github.com/GabeBecker2048/chesssnake/blob/main/CHANGELOG.md).
Until 1.0.0, a version may rename a setting or change the database.

> To stay off surprise upgrades, pin the image to a minor version
> (`:0.15`) or an exact one (`:0.15.3`) instead of `:latest`.
{: .tip }

### When a version changes the database

chesssnake has no database migrations before 1.0.0. The server will not start
on a database from an older version that no longer fits, and says which of
these applies:

| The server says | Do this | Keeps your data |
|---|---|---|
| The database is **missing tables** | `chesssnake init-db` (or have `database.init_schema` on, as the Docker examples do) | yes |
| The database's **schema has changed** | `chesssnake init-db --drop` | **no: every account and game is deleted** |

Before a `--drop`, save any games you want to keep as PGN (**Download PGN** on
a game's page, or `GET /v1/games/{id}/pgn`). They cannot be loaded back in,
but any chess program can open them. Afterwards, make the admin account again.

In Docker:

```sh
docker compose down
docker compose run --rm chesssnake init-db --drop
docker compose up -d
docker compose exec chesssnake chesssnake user create yourname --admin
```

From 1.0.0 on, upgrades within a major version will keep your data.

### When a version renames a setting

An unknown setting in the config file stops the server at start-up with the
name of the offending key, and an unknown `CHESSSNAKE__...` environment
variable prints a warning. Fix the name and start again;
`chesssnake config show` lists what is in effect.

## Backups

**SQLite:** the database is the files under `./data`. Stop the server, copy
the folder, start it again:

```sh
docker compose stop
cp -a data data-backup-$(date +%F)
docker compose start
```

To back up without stopping, use SQLite's own tool, which takes a consistent
copy of a database in use:

```sh
sqlite3 data/chesssnake.db ".backup 'backup.db'"
```

Do not copy the file of a running server by hand: recent moves may be missing
from it.

**PostgreSQL:** use `pg_dump` as for any other database:

```sh
docker compose exec postgres pg_dump -U chesssnake chesssnake > backup.sql
```

To restore, stop the server, put the files (or load the dump) back, and start
the same chesssnake version the backup was taken from.
