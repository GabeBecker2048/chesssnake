"""
Command-line entry point for chesssnake.

Subcommands:
  chesssnake api-endpoint   Run the REST API server (FastAPI + uvicorn).
  chesssnake init-db        Initialize the database schema, then exit.

Database credentials are read from the CHESSDB_* environment variables
(see chesssnake.db.sql).
"""

import argparse
import os
import sys


def _run_api_endpoint(args):
    if args.init_db:
        os.environ["CHESSSNAKE_INIT_DB"] = "1"
    try:
        import uvicorn
    except ImportError:
        sys.exit("The api-endpoint requires FastAPI and uvicorn. Install them with: pip install chesssnake[api]")
    uvicorn.run("chesssnake.api.server:app", host=args.host, port=args.port)


def _run_init_db(_args):
    from .db.sql import initialize_connection_pool, psql_db_schema_init

    initialize_connection_pool()
    psql_db_schema_init()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="chesssnake", description="chesssnake command-line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    api = subparsers.add_parser("api-endpoint", help="run the REST API server")
    api.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    api.add_argument("--port", type=int, default=8000, help="bind port (default: 8000)")
    api.add_argument("--init-db", action="store_true", help="initialize the database schema on startup")
    api.set_defaults(func=_run_api_endpoint)

    init_db = subparsers.add_parser("init-db", help="initialize the database schema, then exit")
    init_db.set_defaults(func=_run_init_db)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
