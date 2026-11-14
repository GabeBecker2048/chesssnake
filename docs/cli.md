---
title: Command line
---

Everything is one program, `chesssnake`. Add `--help` to any command for its
options. With Docker, run server commands as
`docker compose exec chesssnake chesssnake <command>`.

## Playing

These talk to a server. Each takes `--api-url URL` (or set
`CHESSSNAKE__CLIENT__API_URL` once) and needs `pip install 'chesssnake[client]'`.
See [In the terminal](terminal.html).

| Command | |
|---|---|
| `chesssnake login [USERNAME]` | Log in and remember it. `--password-stdin` reads the password from a pipe. |
| `chesssnake logout` | End and forget the login. |
| `chesssnake whoami` | Who you are logged in as. |
| `chesssnake challenge USER` | Challenge someone. `--color white`, `black` or `random` (the default). |
| `chesssnake challenges` | Your pending challenges, with their ids. |
| `chesssnake accept ID` | Accept a challenge: the game starts. |
| `chesssnake decline ID` | Decline a challenge, or withdraw one you sent. |
| `chesssnake games` | Your games in progress, with their ids. |
| `chesssnake play` | Play a game. |

`challenge`, `games` and `play --vs` take `--group ID` for games in a
[group](bots.html#groups) other than `0`.

### chesssnake play

| Option | |
|---|---|
| `--local` | Play offline, with no server. Not saved. |
| `--game ID` | The game to play. |
| `--vs USER` | Play your game in progress against this user. |
| `--perspective white` or `black` | Which side faces you. Yours, by default. |
| `--refresh SECONDS` | Without live updates, how often to check the server (default 10; `0` never). |
| `--no-live` | Do not use live updates. |
| `--ascii` | Pieces as letters. |
| `--no-color` | No colour codes. |
| `--white-name NAME`, `--black-name NAME` | With `--local`: names to show. |
| `--me white` or `black` | With `--local`: play only that side. |

The stored login is in `~/.config/chesssnake/credentials.json`, readable only
by you. `--token` or `CHESSSNAKE__CLIENT__TOKEN` uses a token instead.

## Running a server

These need `pip install 'chesssnake[api]'`. Each takes `--config PATH` and
`-o section.key=value` (see [Configuration](configuration.html)).

| Command | |
|---|---|
| `chesssnake api-endpoint` | Run the server. `--host`, `--port`, `--registration closed` or `open`, `--database-url URL`, and `--init-db` to create missing tables first. |
| `chesssnake init-db` | Create the database tables, then exit. |
| `chesssnake init-db --create-database` | Also create the database itself if it is missing. |
| `chesssnake init-db --drop` | **Delete every account and game**, then create the tables fresh. See [Upgrading](upgrading.html#when-a-version-changes-the-database). |
| `chesssnake config show` | Every setting in effect and where it came from. `--format json`, `--show-secrets`. |
| `chesssnake config init` | Write a config file with every setting explained. `--force` to replace one. |

## Managing accounts

`chesssnake user` works straight on the database, on the server's machine. See
[Accounts](accounts.html#managing-accounts-from-the-command-line). `USER` is a
username or an id.

| Command | |
|---|---|
| `chesssnake user create USERNAME` | Make an account; asks for a password. `--admin`; `--no-password` for an account that only uses api tokens; `--password-stdin`. |
| `chesssnake user show USER` | Print an account and its linked ids. |
| `chesssnake user set-role USER admin` | Make someone an administrator (`user` to undo). |
| `chesssnake user rename USER NEW_NAME` | Change a username. |
| `chesssnake user set-password USER` | Set a password, and log the account out everywhere. |
| `chesssnake user disable USER` | Lock an account out. |
| `chesssnake user enable USER` | Let it back in. |
| `chesssnake user link USER PROVIDER ID` | Link an outside id, such as `discord 184405311681986560`. |
| `chesssnake user token USER --name NAME` | Make an api token and print it once. `--expires-days N`. |
