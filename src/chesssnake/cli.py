"""
Command-line entry point for chesssnake.

Playing, against an api-endpoint (log in once; the token is remembered):
  chesssnake login          Log in and store a token for that endpoint.
  chesssnake logout         Revoke and forget it.
  chesssnake whoami         Who you are logged in as.
  chesssnake games          Your games in progress.
  chesssnake challenge      Challenge another user to a game.
  chesssnake challenges     Your pending challenges, both ways.
  chesssnake accept         Accept a challenge (this creates the game).
  chesssnake decline        Decline a challenge, or withdraw one you sent.
  chesssnake play           Play a game at the terminal (local, or on an api-endpoint).

Running a server:
  chesssnake api-endpoint   Run the REST API server (FastAPI + uvicorn).
  chesssnake init-db        Initialize the database schema, then exit.
  chesssnake user           Manage accounts straight in the database (how the first admin is made).
  chesssnake config init    Write a commented default config file.
  chesssnake config show    Print the effective configuration and where it came from.

Server settings are resolved by :mod:`chesssnake.config` from four layers —
command-line flags, ``CHESSSNAKE__*`` environment variables, a TOML config file,
and built-in defaults, in that order of precedence. The client commands never
import it: they need only the ``client`` install.
"""

import argparse
import getpass
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

# Mirror remote.game.API_URL_ENV / TOKEN_ENV. Hardcoded rather than imported
# because argparse needs them while the parser is being built, and importing
# chesssnake.remote at module scope would pull the engine (and Pillow) into every
# `chesssnake config show`. tests/unit/test_play.py asserts the copies stay equal.
_API_URL_ENV = "CHESSSNAKE__CLIENT__API_URL"
_TOKEN_ENV = "CHESSSNAKE__CLIENT__TOKEN"

# Maps a parsed argparse attribute to the (section, key) it overrides. Flags that
# are not settings (--config, --create-database) are handled separately.
_FLAG_SETTINGS = {
    "host": ("api", "host"),
    "port": ("api", "port"),
    "registration": ("api", "registration"),
    "database_url": ("database", "url"),
    "init_db": ("database", "init_schema"),
}


def _config():
    """
    Import the configuration module, or exit with an actionable message.

    Configuration validation uses pydantic, which ships in the ``api`` extra
    rather than the core dependencies, so that purely local games stay
    dependency-free.
    """
    try:
        from . import config
    except ImportError as e:
        sys.exit(f"chesssnake configuration requires pydantic ({e}).\nInstall it with: pip install 'chesssnake[api]'")
    return config


def _overrides(args):
    """Build the command-line layer from parsed arguments, highest precedence last."""
    config = _config()
    overrides = []

    # Generic --set first, so an explicit named flag always wins over it.
    for item in getattr(args, "set", None) or []:
        path, _, value = item.partition("=")
        section, _, key = path.strip().partition(".")
        if not key or not value:
            sys.exit(f"Invalid --set {item!r}; expected the form section.key=value")
        overrides.append(config.Override(section, key, value, "cli", f"--set {path.strip()}"))

    for attr, (section, key) in _FLAG_SETTINGS.items():
        value = getattr(args, attr, None)
        if value is not None:
            flag = "--" + attr.replace("_", "-")
            overrides.append(config.Override(section, key, value, "cli", flag))

    return overrides


def _resolve(args):
    """Resolve settings for a subcommand, exiting cleanly on a configuration error."""
    config = _config()
    try:
        return config.resolve(_overrides(args), config_path=args.config)
    except config.ConfigError as e:
        sys.exit(str(e))


def _run_api_endpoint(args):
    settings = _resolve(args)
    try:
        import uvicorn
    except ImportError:
        sys.exit("The api-endpoint requires FastAPI and uvicorn. Install them with: pip install chesssnake[api]")

    from .api.server import create_app

    # The app object is passed directly rather than as an import string, which is
    # what lets command-line flags reach the server at all. Note this rules out
    # uvicorn's --reload/--workers; those re-import in a fresh process, where only
    # the environment and config file survive.
    ws = settings.websocket
    uvicorn.run(
        create_app(settings),
        host=settings.api.host,
        port=settings.api.port,
        # Websocket transport, from [websocket]. uvicorn treats a ping interval of
        # None as "never"; ws_max_queue is not passed because uvicorn's websocket
        # implementation ignores it.
        ws_ping_interval=ws.ping_interval_seconds or None,
        ws_ping_timeout=ws.ping_timeout_seconds,
        ws_max_size=ws.max_message_bytes,
        ws_per_message_deflate=ws.compression,
        # Bounds shutdown with sockets open, so `docker stop` is not left to SIGKILL.
        timeout_graceful_shutdown=ws.shutdown_timeout_seconds,
    )


@contextmanager
def _database(settings):
    """
    Open the process-wide engine for a one-shot command, and always close it.

    :raises chesssnake.db.errors.GameError: If the engine cannot be created.
    """
    from .db import engine as db_engine

    engine = db_engine.initialize_engine(
        settings.database.url,
        pool_min_size=settings.database.pool_min_size,
        pool_max_size=settings.database.pool_max_size,
        sqlite_busy_timeout=settings.database.sqlite_busy_timeout,
    )
    try:
        yield engine
    finally:
        db_engine.dispose_engine()


def _run_init_db(args):
    settings = _resolve(args)
    from .db import engine as db_engine
    from .db import errors, schema

    try:
        if args.create_database:
            parsed = db_engine.parse_url(settings.database.url)
            # For SQLite this only ensures the parent directory exists; the file
            # itself is created on first connection.
            print(db_engine.backend_module(parsed.get_backend_name()).create_database(parsed))
        with _database(settings) as engine:
            if args.drop:
                # Pre-1.0 there are no migrations: a schema change is applied by
                # dropping everything and creating it again.
                schema.drop_all(engine)
                print("Dropped every chesssnake table.")
            stale = schema.stale_tables(engine)
            if stale:
                sys.exit(
                    f"These tables were created by an older chesssnake: {', '.join(stale)}.\n"
                    "Recreate the database with `chesssnake init-db --drop` (this deletes everything in it)."
                )
            schema.create_all(engine)
            print("Database schema initialized successfully.")
    except errors.GameError as e:
        sys.exit(str(e))


def _player(value):
    """
    An argparse type for a player: a user id (digits) or a username.

    Usernames cannot be all digits, which is what makes this unambiguous.
    """
    if value.isdigit():
        return int(value)
    from .db.errors import USERNAME_RE, USERNAME_RULE

    if not USERNAME_RE.match(value):
        raise argparse.ArgumentTypeError(f"{value!r} is neither a user id nor a username ({USERNAME_RULE})")
    return value


def _read_password(args, *, confirm, prompt="Password: "):
    """
    A password from stdin (``--password-stdin``) or an interactive prompt.

    Never from a command-line argument: those end up in shell history and in
    ``ps`` output for every user on the machine.
    """
    if getattr(args, "password_stdin", False):
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            sys.exit("--password-stdin was given but stdin had no password")
        return password
    if not sys.stdin.isatty():
        sys.exit("No terminal to prompt for a password on; pass it on stdin with --password-stdin")
    password = getpass.getpass(prompt)
    if confirm and getpass.getpass("Again: ") != password:
        sys.exit("The passwords did not match")
    return password


def _run_user(args):
    """``chesssnake user ...``: account administration straight against the database."""
    settings = _resolve(args)
    from .db import errors
    from .db import operations as ops
    from .dto import ROLES, User

    def lookup(who):
        user = ops.user_get(who) if isinstance(who, int) else ops.user_get_by_name(who)
        if user is None:
            raise errors.UserNotFoundError(f"No user {who!r}")
        return user

    def hashed(confirm=True):
        from .api.auth import hash_password, validate_password

        return hash_password(validate_password(_read_password(args, confirm=confirm)))

    try:
        with _database(settings):
            if args.action == "create":
                password_hash = None if args.no_password else hashed()
                user = ops.user_create(args.username, ROLES["admin"] if args.admin else ROLES["user"], password_hash)
            elif args.action == "show":
                user = lookup(args.user)
            elif args.action == "set-role":
                user = ops.user_set_role(lookup(args.user)["id"], ROLES[args.role])
            elif args.action == "rename":
                user = ops.user_rename(lookup(args.user)["id"], args.username)
            elif args.action == "link":
                user = ops.identity_link(lookup(args.user)["id"], args.provider, args.external_id)
            elif args.action == "set-password":
                user = lookup(args.user)
                # Like an admin reset over the API: every token the user had goes.
                ops.user_set_password(user["id"], hashed(), revoke="all")
                user = lookup(user["id"])
            elif args.action in ("disable", "enable"):
                user = ops.user_set_disabled(lookup(args.user)["id"], args.action == "disable")
            else:  # token
                user = lookup(args.user)
                raw, token = ops.token_create(
                    user["id"], ops.TOKEN_API, name=args.name, lifetime_days=args.expires_days
                )
                # The secret alone on stdout, so it can be captured cleanly; the
                # context goes to stderr.
                print(raw)
                expiry = token["expires_at"].isoformat() if token["expires_at"] else "never"
                print(
                    f"api token {token['id']} ({args.name!r}) for {user['username']}, expires {expiry}. "
                    "It is not shown again.",
                    file=sys.stderr,
                )
                return
    except errors.GameError as e:
        sys.exit(str(e))
    print(json.dumps(User.from_row(user).to_dict(), indent=2))


# --- client commands ---------------------------------------------------------
#
# None of these import chesssnake.config: they need only the `client` install.


def _endpoint(args):
    url = getattr(args, "api_url", None) or os.getenv(_API_URL_ENV)
    if not url:
        sys.exit(f"Which api-endpoint? Pass --api-url or set {_API_URL_ENV}.")
    return url


def _require_requests():
    try:
        import requests  # noqa: F401
    except ImportError as e:
        sys.exit(
            f"Talking to an api-endpoint requires requests ({e}).\nInstall it with: pip install 'chesssnake[client]'"
        )


def _connect(args):
    """An authenticated client for the endpoint, or exit saying how to log in."""
    _require_requests()
    from .db.errors import AuthError
    from .remote.game import connect

    url = _endpoint(args)
    try:
        return connect(url, token=getattr(args, "token", None))
    except AuthError:
        sys.exit(f"Not logged in to {url}. Run `chesssnake login --api-url {url}`, or set {_TOKEN_ENV}.")


@contextmanager
def _client_errors(*, logging_in=False):
    """Turn a refused request into one line and a non-zero exit, not a traceback."""
    from .db.errors import AuthError, GameError
    from .engine.errors import ChessError

    try:
        yield
    except AuthError as e:
        sys.exit(str(e) if logging_in else f"{e}\nLog in again with `chesssnake login`.")
    except (GameError, ChessError) as e:
        sys.exit(f"{type(e).__name__}: {e}")
    except OSError as e:  # requests' ConnectionError is an OSError
        sys.exit(f"Could not reach the api-endpoint: {e}")


def _insecure(url):
    parts = urlsplit(url)
    return parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1")


def _run_login(args):
    _require_requests()
    from .remote import credentials
    from .remote.client import ApiClient

    url = _endpoint(args)
    if _insecure(url):
        print(f"warning: {url} is plain http; your password crosses the network unencrypted", file=sys.stderr)
    username = args.username or input("Username: ").strip()
    password = _read_password(args, confirm=False)
    with _client_errors(logging_in=True):
        result = ApiClient(url).login(username, password)
    path = credentials.save(url, result.token, result.user.username if result.user else username)
    expiry = result.token_info.expires_at or "never"
    print(f"Logged in to {url} as {result.user.username if result.user else username} (until {expiry}).")
    print(f"Token saved to {path}")


def _run_logout(args):
    from .remote import credentials

    url = _endpoint(args)
    stored = credentials.load(url)
    if stored is None:
        print(f"Not logged in to {url}.")
        return
    _require_requests()
    from .db.errors import AuthError
    from .remote.client import ApiClient

    try:
        ApiClient(url, token=stored["token"]).logout()
    except AuthError:
        pass  # already expired or revoked: forgetting it is all that is left
    except OSError as e:
        print(f"warning: could not reach {url} to revoke the token ({e}); forgetting it anyway", file=sys.stderr)
    credentials.forget(url)
    print(f"Logged out of {url}.")


def _run_whoami(args):
    client = _connect(args)
    with _client_errors():
        me = client.me()
    print(f"{me.username} (id {me.id}, {me.role}) on {client.base_url}")


def _run_games(args):
    client = _connect(args)
    with _client_errors():
        me = client.me()
        games = client.current_games(group_id=args.group)
    if not games:
        print("No games in progress. Start one with `chesssnake challenge USER`.")
        return
    for game in games:
        mine = "white" if game.white_id == me.id else "black"
        opponent = game.black_name if mine == "white" else game.white_name
        to_move = "white" if game.fen.split()[1] == "w" else "black"
        turn = "your move" if to_move == mine else "their move"
        print(f"game {game.id}: you ({mine}) vs {opponent}, group {game.group_id}, {turn}")


def _run_challenge(args):
    client = _connect(args)
    with _client_errors():
        challenge = client.challenge(args.opponent, args.group, args.color)
    print(
        f"challenge {challenge.id} sent to {challenge.challenged_name} (you play {challenge.color}). "
        "When they accept it the game starts; `chesssnake games` lists it."
    )


def _run_challenges(args):
    client = _connect(args)
    with _client_errors():
        me = client.me()
        challenges = client.challenges("all")
    if not challenges:
        print("No pending challenges.")
        return
    for c in challenges:
        if c.challenged_id == me.id:
            print(
                f"challenge {c.id}: from {c.challenger_name} (they play {c.color}), group {c.group_id}"
                f"  -> chesssnake accept {c.id}"
            )
        else:
            print(f"challenge {c.id}: to {c.challenged_name} (you play {c.color}), group {c.group_id}, waiting")


def _run_accept(args):
    client = _connect(args)
    with _client_errors():
        game = client.accept_challenge(args.challenge)
    print(f"game {game.id} started: {game.white_name} (white) vs {game.black_name} (black).")
    print(f"Play it with: chesssnake play --game {game.id}")


def _run_decline(args):
    client = _connect(args)
    with _client_errors():
        client.decline_challenge(args.challenge)
    print(f"challenge {args.challenge} removed.")


def _run_play(args):
    """
    Play a game at the terminal.

    Deliberately does **not** touch :mod:`chesssnake.config`: a local game needs
    nothing beyond the core install, and a remote one needs only the endpoint and
    the token ``chesssnake login`` stored.
    """
    from .play import run_session
    from .remote.game import Game

    if args.refresh < 0:
        sys.exit("--refresh takes a number of seconds, or 0 to disable; it cannot be negative")

    if args.local:
        if args.game is not None or args.vs is not None:
            sys.exit("--game and --vs are for games on an api-endpoint, not --local ones")
        if args.me is not None and args.me not in (0, 1):
            sys.exit("With --local, --me is 0 (white) or 1 (black)")
        game = Game.local(white_name=args.white_name, black_name=args.black_name)
        player_id = args.me
        events = None
    else:
        if args.white_name or args.black_name or args.me is not None:
            sys.exit(
                "--me, --white-name and --black-name are only for --local games. On an api-endpoint you play as "
                "the user you logged in as, and the board shows each player's username."
            )
        if (args.game is None) == (args.vs is None):
            sys.exit("Which game? Pass --game ID, or --vs USER for your game in progress against them.")
        client = _connect(args)
        with _client_errors():
            me = client.me()
            if args.game is not None:
                game_id = args.game
            else:
                active = client.games_between(me.id, args.vs, args.group, status="active")
                if not active:
                    sys.exit(
                        f"No game in progress against {args.vs} in group {args.group}. "
                        f"Start one with `chesssnake challenge {args.vs}`."
                    )
                game_id = active[-1].id
            game = Game.remote(game_id, client=client)
        # You act as yourself. An administrator watching someone else's game acts
        # as whichever side is to move instead, sending that player's id.
        playing = me.id in (game.wid, game.bid)
        player_id = None if (me.is_admin and not playing) else me.id
        events = None if args.no_live else _live_updates(client, game.id, args.refresh)

    color = not args.no_color and sys.stdout.isatty()
    try:
        status = run_session(
            game,
            player_id=player_id,
            stdin=sys.stdin,
            stdout=sys.stdout,
            color=color,
            figurines=not args.ascii,
            perspective=args.perspective,
            refresh_seconds=args.refresh,
            events=events,
        )
    finally:
        # Every way out (quit, EOF, Ctrl+C's 130, a logged-out 1) closes the socket.
        if events is not None:
            events.close()
    sys.exit(status)


def _live_updates(client, game_id, refresh):
    """
    A live stream for this game, or ``None`` (with a note) to poll instead.

    Live updates are opt-in on the server, so not having them is normal, not an
    error: say why, and say what happens instead.
    """
    from .db.errors import AuthError
    from .remote.realtime import RealtimeUnavailable

    try:
        return client.events(games=[game_id])
    except RealtimeUnavailable as e:
        polling = f"polling every {refresh:g} s" if refresh > 0 else "not refreshing (--refresh 0)"
        print(f"note: no live updates: {e}; {polling}", file=sys.stderr)
        return None
    except AuthError as e:
        sys.exit(f"{e}\nLog in again with `chesssnake login`.")


def _run_config_show(args):
    config = _config()
    try:
        settings = config.resolve(_overrides(args), config_path=args.config)
    except config.ConfigError as e:
        # A config inspector that refuses to print when the config is broken is
        # useless exactly when it is needed, so report the problem and still exit
        # non-zero rather than saying nothing.
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(config.format_settings(settings, show_secrets=args.show_secrets, as_json=args.format == "json"))


def _run_config_init(args):
    config = _config()
    try:
        path = config.write_default_config(force=args.force)
    except config.ConfigError as e:
        sys.exit(str(e))

    print(f"Wrote the default configuration to {path}")
    # The working directory is searched before $CHESSSNAKE_HOME, so a stray file
    # there would quietly win over the one just written.
    shadow = Path.cwd() / config.CONFIG_FILENAME
    if path != shadow and shadow.is_file():
        print(f"note: {shadow} exists and takes precedence over it.", file=sys.stderr)


def _add_setting_flags(parser):
    parser.add_argument("--host", help="address the api-endpoint binds to")
    parser.add_argument("--port", type=int, help="port the api-endpoint binds to")
    parser.add_argument(
        "--registration", choices=("closed", "open"), help="whether anyone may create an account (default closed)"
    )
    parser.add_argument("--database-url", dest="database_url", help="database connection string")


def build_parser() -> argparse.ArgumentParser:
    """
    The whole command line: every subcommand, argument and option.

    Separate from :func:`main` so the command-line surface can be inspected
    without running anything: ``tests/config/test_public_api.py`` pins it, since
    commands and flags end up in scripts and compose files.
    """
    parser = argparse.ArgumentParser(prog="chesssnake", description="chesssnake command-line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Shared by every server subcommand. Declared on a parent rather than the
    # top-level parser so they can be written after the subcommand, where users
    # expect them.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="PATH", help="path to a chesssnake.toml config file")
    common.add_argument(
        "-o",
        "--set",
        action="append",
        metavar="SECTION.KEY=VALUE",
        help="set any configuration value, e.g. -o database.pool_max_size=20 (repeatable)",
    )

    # Shared by every client subcommand. No --config: they never read one.
    endpoint = argparse.ArgumentParser(add_help=False)
    endpoint.add_argument("--api-url", dest="api_url", help=f"api-endpoint base URL (env: {_API_URL_ENV})")
    endpoint.add_argument(
        "--token",
        help=f"a token to use instead of the stored login (env: {_TOKEN_ENV}); visible in `ps`, so prefer the env",
    )

    # --- client ---

    login = subparsers.add_parser("login", help="log in to an api-endpoint and remember the token", parents=[endpoint])
    login.add_argument("username", nargs="?", help="your username (prompted for if omitted)")
    login.add_argument("--password-stdin", action="store_true", help="read the password from stdin, not a prompt")
    login.set_defaults(func=_run_login)

    logout = subparsers.add_parser("logout", help="revoke and forget the stored token", parents=[endpoint])
    logout.set_defaults(func=_run_logout)

    whoami = subparsers.add_parser("whoami", help="who you are logged in as", parents=[endpoint])
    whoami.set_defaults(func=_run_whoami)

    games = subparsers.add_parser("games", help="your games in progress", parents=[endpoint])
    games.add_argument("--group", type=int, help="only this group")
    games.set_defaults(func=_run_games)

    challenge = subparsers.add_parser("challenge", help="challenge another user to a game", parents=[endpoint])
    challenge.add_argument("opponent", type=_player, help="their username or user id")
    challenge.add_argument("--group", type=int, default=0, help="group id (default 0)")
    challenge.add_argument(
        "--color", choices=("white", "black", "random"), default="random", help="the colour you want (default random)"
    )
    challenge.set_defaults(func=_run_challenge)

    challenges = subparsers.add_parser("challenges", help="your pending challenges", parents=[endpoint])
    challenges.set_defaults(func=_run_challenges)

    accept = subparsers.add_parser("accept", help="accept a challenge, which starts the game", parents=[endpoint])
    accept.add_argument("challenge", type=int, help="the challenge id (see `chesssnake challenges`)")
    accept.set_defaults(func=_run_accept)

    decline = subparsers.add_parser("decline", help="decline a challenge, or withdraw one you sent", parents=[endpoint])
    decline.add_argument("challenge", type=int, help="the challenge id")
    decline.set_defaults(func=_run_decline)

    # No `parents=[common]`: play resolves nothing through chesssnake.config, so
    # --config and -o would be accepted and then silently ignored.
    play = subparsers.add_parser("play", help="play a game at the terminal", parents=[endpoint])
    play.add_argument("--local", action="store_true", help="play offline, in memory, with no api-endpoint")
    play.add_argument("--game", type=int, help="the id of the game to play (see `chesssnake games`)")
    play.add_argument("--vs", type=_player, help="play your game in progress against this user")
    play.add_argument("--group", type=int, default=0, help="the group, with --vs (default 0)")
    play.add_argument("--me", type=int, help="with --local: 0 to play white only, 1 for black")
    play.add_argument("--white-name", dest="white_name", default="", help="display name for white (--local only)")
    play.add_argument("--black-name", dest="black_name", default="", help="display name for black (--local only)")
    play.add_argument(
        "--perspective",
        choices=("white", "black"),
        help="which side faces you (default: your own side, else white)",
    )
    play.add_argument(
        "--refresh",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="without live updates, re-read the server this often while waiting (default 10; 0 disables)",
    )
    play.add_argument(
        "--no-live",
        dest="no_live",
        action="store_true",
        help="do not use the server's live updates; poll every --refresh seconds instead",
    )
    play.add_argument("--ascii", action="store_true", help="draw pieces as letters instead of figurines")
    play.add_argument("--no-color", dest="no_color", action="store_true", help="never emit ANSI colour")
    play.set_defaults(func=_run_play)

    # --- server ---

    api = subparsers.add_parser("api-endpoint", help="run the REST API server", parents=[common])
    _add_setting_flags(api)
    api.add_argument(
        "--init-db",
        dest="init_db",
        action="store_true",
        default=None,
        help="initialize the database schema on startup",
    )
    api.set_defaults(func=_run_api_endpoint)

    init_db = subparsers.add_parser("init-db", help="initialize the database schema, then exit", parents=[common])
    init_db.add_argument("--database-url", dest="database_url", help="database connection string")
    init_db.add_argument(
        "--create-database",
        action="store_true",
        help="create the database first if it does not exist (PostgreSQL: requires permission; SQLite: creates the directory)",
    )
    init_db.add_argument(
        "--drop",
        action="store_true",
        help="drop every chesssnake table first, deleting all users and games (how a schema change is applied before 1.0)",
    )
    init_db.set_defaults(func=_run_init_db)

    user = subparsers.add_parser("user", help="manage accounts directly in the database")
    user_actions = user.add_subparsers(dest="action", required=True)
    user_common = argparse.ArgumentParser(add_help=False, parents=[common])
    user_common.add_argument("--database-url", dest="database_url", help="database connection string")
    password_input = argparse.ArgumentParser(add_help=False)
    password_input.add_argument(
        "--password-stdin", action="store_true", help="read the password from stdin instead of prompting"
    )

    create = user_actions.add_parser(
        "create", help="create a user (the id is assigned)", parents=[user_common, password_input]
    )
    create.add_argument("username")
    create.add_argument("--admin", action="store_true", help="make the user an administrator")
    create.add_argument(
        "--no-password",
        action="store_true",
        help="no password: the account cannot log in, only use api tokens (e.g. a bot)",
    )
    show_user = user_actions.add_parser("show", help="print a user and their linked ids", parents=[user_common])
    show_user.add_argument("user", type=_player, metavar="ID_OR_USERNAME")
    set_role = user_actions.add_parser("set-role", help="make a user an admin, or not", parents=[user_common])
    set_role.add_argument("user", type=_player, metavar="ID_OR_USERNAME")
    set_role.add_argument("role", choices=("user", "admin"))
    rename = user_actions.add_parser("rename", help="change a user's username", parents=[user_common])
    rename.add_argument("user", type=_player, metavar="ID_OR_USERNAME")
    rename.add_argument("username")
    link = user_actions.add_parser(
        "link", help="link an id from another system (e.g. discord) to a user", parents=[user_common]
    )
    link.add_argument("user", type=_player, metavar="ID_OR_USERNAME")
    link.add_argument("provider", help="the other system's name, e.g. discord")
    link.add_argument("external_id", help="the user's id in that system")
    set_password = user_actions.add_parser(
        "set-password", help="set a user's password (revokes all their tokens)", parents=[user_common, password_input]
    )
    set_password.add_argument("user", type=_player, metavar="ID_OR_USERNAME")
    for action, blurb in (("disable", "disable a user and revoke their tokens"), ("enable", "re-enable a user")):
        toggle = user_actions.add_parser(action, help=blurb, parents=[user_common])
        toggle.add_argument("user", type=_player, metavar="ID_OR_USERNAME")
    token = user_actions.add_parser(
        "token", help="create an api token for a user and print it once (e.g. for a bot)", parents=[user_common]
    )
    token.add_argument("user", type=_player, metavar="ID_OR_USERNAME")
    token.add_argument("--name", required=True, help="what the token is for, e.g. discord-bot")
    token.add_argument("--expires-days", dest="expires_days", type=int, help="days until it expires (default never)")
    user.set_defaults(func=_run_user)

    config_parser = subparsers.add_parser("config", help="inspect configuration")
    config_actions = config_parser.add_subparsers(dest="action", required=True)
    show = config_actions.add_parser(
        "show", help="print the effective configuration and each value's source", parents=[common]
    )
    _add_setting_flags(show)
    show.add_argument("--show-secrets", action="store_true", help="print credentials instead of redacting them")
    show.add_argument("--format", choices=("table", "json"), default="table", help="output format")
    show.set_defaults(func=_run_config_show)

    # No `parents=[common]`: --config names a file to *read*, which is meaningless
    # here, and the destination is determined by $CHESSSNAKE_HOME by design.
    init = config_actions.add_parser(
        "init",
        help="write a commented default config file to $CHESSSNAKE_HOME, or the working directory",
    )
    init.add_argument("--force", action="store_true", help="overwrite an existing config file")
    init.set_defaults(func=_run_config_init)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        # Every subcommand, not only `play`: Ctrl+C is a way of leaving, and a
        # traceback is never the right answer to it. 130 is the SIGINT
        # convention. `play` handles it inside the session so it can exit
        # tidily; this catches anywhere else, such as init-db mid-connection.
        sys.exit(130)


if __name__ == "__main__":
    main()
