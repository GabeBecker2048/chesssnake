"""
Command-line entry point for chesssnake.

Subcommands:
  chesssnake api-endpoint   Run the REST API server (FastAPI + uvicorn).
  chesssnake init-db        Initialize the database schema, then exit.
  chesssnake config init    Write a commented default config file.
  chesssnake config show    Print the effective configuration and where it came from.

Settings are resolved by :mod:`chesssnake.config` from four layers — command-line
flags, ``CHESSSNAKE__*`` environment variables, a TOML config file, and built-in
defaults, in that order of precedence.
"""

import argparse
import sys
from pathlib import Path

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


def _run_init_db(args):
    settings = _resolve(args)
    from .db.sql import initialize_connection_pool, psql_db_init, psql_db_schema_init

    if args.create_database:
        psql_db_init(settings.database.url, schema_init=False)
    initialize_connection_pool(
        settings.database.url,
        minconn=settings.database.pool_min_size,
        maxconn=settings.database.pool_max_size,
    )
    psql_db_schema_init(settings.database.url)


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
        help="create the database first, if it does not exist (requires permission)",
    )
    init_db.set_defaults(func=_run_init_db)

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
    args.func(args)


if __name__ == "__main__":
    main()
