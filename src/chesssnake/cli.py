"""
Command-line entry point for chesssnake.

Subcommands:
  chesssnake play           Play a game at the terminal (local, or on an api-endpoint).
  chesssnake api-endpoint   Run the REST API server (FastAPI + uvicorn).
  chesssnake init-db        Initialize the database schema, then exit.
  chesssnake user           Create, inspect and manage user accounts in the database.
  chesssnake config init    Write a commented default config file.
  chesssnake config show    Print the effective configuration and where it came from.

Settings are resolved by :mod:`chesssnake.config` from four layers — command-line
flags, ``CHESSSNAKE__*`` environment variables, a TOML config file, and built-in
defaults, in that order of precedence.
"""

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

# Mirrors remote.game.API_URL_ENV. Hardcoded rather than imported because
# argparse needs it while the parser is being built, and importing
# chesssnake.remote at module scope would pull the engine (and Pillow) into
# every `chesssnake config show`. test_play_cli asserts the two stay equal.
_API_URL_ENV = "CHESSSNAKE__CLIENT__API_URL"
_API_KEY_ENV = "CHESSSNAKE__CLIENT__API_KEY"

# Maps a parsed argparse attribute to the (section, key) it overrides. Flags that
# are not settings (--config, --create-database) are handled separately.
_FLAG_SETTINGS = {
    "host": ("api", "host"),
    "port": ("api", "port"),
    "api_key": ("api", "api_key"),
    "require_auth": ("api", "require_auth"),
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
    uvicorn.run(create_app(settings), host=settings.api.host, port=settings.api.port)


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

    try:
        with _database(settings):
            if args.action == "create":
                user = ops.user_create(args.username, ROLES["admin"] if args.admin else ROLES["user"])
            elif args.action == "show":
                user = lookup(args.user)
            elif args.action == "set-role":
                user = ops.user_set_role(lookup(args.user)["id"], ROLES[args.role])
            elif args.action == "rename":
                user = ops.user_rename(lookup(args.user)["id"], args.username)
            else:  # link
                user = ops.identity_link(lookup(args.user)["id"], args.provider, args.external_id)
    except errors.GameError as e:
        sys.exit(str(e))
    print(json.dumps(User.from_row(user).to_dict(), indent=2))


def _run_play(args):
    """
    Play a game at the terminal.

    Deliberately does **not** touch :mod:`chesssnake.config`: a local game needs
    nothing beyond the core install, and a remote one needs only a URL, which
    :meth:`Game.remote` already resolves from ``CHESSSNAKE__CLIENT__API_URL``.
    Importing config here would make ``play`` require pydantic for no reason.
    """
    from .play import run_session
    from .remote.game import API_URL_ENV, Game

    if args.local:
        if any(isinstance(who, str) for who in (args.white, args.black, args.me)):
            sys.exit(
                "A local game has no accounts: --me is 0 (white) or 1 (black), and names come from --white-name/--black-name"
            )
        game = Game.local(white_name=args.white_name, black_name=args.black_name)
        player_id = args.me
    else:
        if args.white_name or args.black_name:
            sys.exit(
                "--white-name and --black-name are only for --local games.\n"
                "On an api-endpoint the board shows each player's username."
            )
        if args.white is None or args.black is None:
            sys.exit("A remote game needs both players: --white and --black, each a user id or a username.")
        if not (args.api_url or os.getenv(API_URL_ENV)):
            sys.exit(
                "A remote game needs an api-endpoint URL.\n"
                f"Pass --api-url, set {API_URL_ENV}, or play offline with: chesssnake play --local"
            )
        try:
            import requests  # noqa: F401
        except ImportError as e:
            sys.exit(f"Remote games require requests ({e}).\nInstall it with: pip install 'chesssnake[client]'")
        try:
            game = Game.remote(
                args.white,
                args.black,
                args.group,
                player_id=args.me,
                api_url=args.api_url,
                api_key=args.api_key,
            )
        except Exception as e:
            # Reaching the endpoint is setup, not gameplay: fail now with the
            # URL in the message rather than dropping into a prompt that cannot work.
            sys.exit(f"Could not open the game: {e}")
        # --me may have been a username; the game resolved it to the id.
        player_id = game.player_id

    if args.refresh < 0:
        sys.exit("--refresh takes a number of seconds, or 0 to disable; it cannot be negative")

    color = not args.no_color and sys.stdout.isatty()
    sys.exit(
        run_session(
            game,
            player_id=player_id,
            stdin=sys.stdin,
            stdout=sys.stdout,
            color=color,
            figurines=not args.ascii,
            perspective=args.perspective,
            refresh_seconds=args.refresh,
        )
    )


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
    parser.add_argument("--api-key", dest="api_key", help="key clients must send as X-API-Key")
    parser.add_argument(
        "--require-auth",
        dest="require_auth",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="require a valid X-API-Key on every /v1 route",
    )
    parser.add_argument("--database-url", dest="database_url", help="database connection string")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="chesssnake", description="chesssnake command-line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Shared by every subcommand. Declared on a parent rather than the top-level
    # parser so they can be written after the subcommand, where users expect them.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="PATH", help="path to a chesssnake.toml config file")
    common.add_argument(
        "-o",
        "--set",
        action="append",
        metavar="SECTION.KEY=VALUE",
        help="set any configuration value, e.g. -o database.pool_max_size=20 (repeatable)",
    )

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

    user = subparsers.add_parser("user", help="manage user accounts directly in the database")
    user_actions = user.add_subparsers(dest="action", required=True)
    user_common = argparse.ArgumentParser(add_help=False, parents=[common])
    user_common.add_argument("--database-url", dest="database_url", help="database connection string")
    create = user_actions.add_parser("create", help="create a user (the id is assigned)", parents=[user_common])
    create.add_argument("username")
    create.add_argument("--admin", action="store_true", help="make the user an administrator")
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
    user.set_defaults(func=_run_user)

    # No `parents=[common]`: play resolves nothing through chesssnake.config, so
    # --config and -o would be accepted and then silently ignored.
    play = subparsers.add_parser("play", help="play a game at the terminal")
    play.add_argument("--local", action="store_true", help="play offline, in memory, with no api-endpoint")
    play.add_argument("--api-url", dest="api_url", help=f"api-endpoint base URL (env: {_API_URL_ENV})")
    play.add_argument(
        "--api-key",
        dest="api_key",
        help=f"key sent as X-API-Key, if the endpoint requires one (env: {_API_KEY_ENV})",
    )
    play.add_argument("--group", type=int, default=0, help="group id (default 0)")
    play.add_argument("--white", type=_player, help="white player: a user id or username (required unless --local)")
    play.add_argument("--black", type=_player, help="black player: a user id or username (required unless --local)")
    play.add_argument(
        "--me",
        type=_player,
        help="you (a user id or username; 0 or 1 with --local); turn order is then enforced and the board faces your side",
    )
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
        help="while waiting at the prompt, re-read the server this often (default 10; 0 disables)",
    )
    play.add_argument("--ascii", action="store_true", help="draw pieces as letters instead of figurines")
    play.add_argument("--no-color", dest="no_color", action="store_true", help="never emit ANSI colour")
    play.set_defaults(func=_run_play)

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

    args = parser.parse_args(argv)
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
