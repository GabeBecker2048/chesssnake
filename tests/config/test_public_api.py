"""The public surface beyond the engine, pinned: what 1.0.0 will promise to keep.

The engine API is pinned in ``tests/unit/test_public_engine_api.py``. This pins
everything else a user can depend on:

- the Python API: ``chesssnake.__all__``, ``Game``'s methods and attributes, the
  factory and ``connect`` signatures, every ``ApiClient`` method signature, the
  payload dataclasses' fields, the live-update stream, and the error class names
  (which are the wire's ``error_type``);
- the REST API: every route with its query parameters and body fields, and the
  websocket route;
- configuration and the command line: every setting and its environment variable,
  and every subcommand with its arguments, options and choices.

The expected surface is ``public_api.json`` beside this file. When this test fails,
the API changed: decide whether that is intended before touching the JSON. If it
is, regenerate the file and review its diff like code:

    uv run python -m tests.config.test_public_api --write
"""

import argparse
import dataclasses
import inspect
import json
import sys
import tempfile
from pathlib import Path

import pytest

EXPECTED = Path(__file__).with_name("public_api.json")


def _public(names):
    return sorted(n for n in names if not n.startswith("_"))


def python_surface() -> dict:
    import chesssnake
    from chesssnake import ApiClient, Game, connect, dto
    from chesssnake.db import errors as db_errors
    from chesssnake.engine import errors as engine_errors
    from chesssnake.remote import realtime

    game = Game.local(white_name="w", black_name="b")
    game.move("e4")
    return {
        "chesssnake.__all__": sorted(chesssnake.__all__),
        "Game members": _public(dir(Game)),
        "Game instance attributes": _public(vars(game)),
        "signatures": {
            "connect": str(inspect.signature(connect)),
            **{f"Game.{n}": str(inspect.signature(getattr(Game, n))) for n in ("local", "remote", "from_state")},
        },
        "ApiClient": {
            name: str(inspect.signature(member))
            for name, member in sorted(vars(ApiClient).items())
            if not name.startswith("_") and callable(member)
        },
        "payloads": {
            name: [f.name for f in dataclasses.fields(getattr(dto, name))]
            for name in ("Challenge", "GameState", "LoginResult", "MoveResult", "TokenInfo", "User")
        },
        "EventStream": _public(vars(realtime.EventStream)),
        "error types": {
            "chess (400)": sorted(
                n
                for n, o in vars(engine_errors).items()
                if isinstance(o, type) and issubclass(o, engine_errors.ChessError)
            ),
            "game": sorted(
                n for n, o in vars(db_errors).items() if isinstance(o, type) and issubclass(o, db_errors.GameError)
            ),
        },
    }


def _body_fields(route) -> list[str]:
    fields = []
    for param in route.dependant.body_params:
        annotation = param.field_info.annotation
        model_fields = getattr(annotation, "model_fields", None)
        fields.extend(sorted(model_fields) if model_fields else [param.name])
    return fields


def rest_surface() -> dict:
    from fastapi.routing import APIRoute, APIWebSocketRoute, iter_route_contexts
    from starlette.routing import Mount

    from chesssnake.api.server import create_app
    from chesssnake.config import resolve

    # an empty environment and working directory, so no local config file leaks in
    with tempfile.TemporaryDirectory() as empty:
        settings = resolve(
            environ={"CHESSSNAKE__DATABASE__URL": "sqlite://", "CHESSSNAKE__WEBSOCKET__ENABLED": "true"}, cwd=empty
        )
    app = create_app(settings)
    routes = {}
    for context in iter_route_contexts(app.routes):
        route = getattr(context, "route", context)
        path = getattr(context, "path", None) or route.path
        if isinstance(route, APIWebSocketRoute):
            routes[f"WS {path}"] = {}
        elif isinstance(route, APIRoute):
            for method in sorted(route.methods - {"HEAD"}):
                entry = {}
                query = sorted(p.name for p in route.dependant.query_params)
                body = _body_fields(route)
                if query:
                    entry["query"] = query
                if body:
                    entry["body"] = body
                routes[f"{method} {path}"] = entry
        elif isinstance(route, Mount):  # the web UI's static files
            routes[f"MOUNT {path}"] = {}
        else:  # a plain Starlette route: FastAPI's /docs, /redoc and /openapi.json
            for method in sorted((route.methods or {"GET"}) - {"HEAD"}):
                routes[f"{method} {path}"] = {}
    return dict(sorted(routes.items()))


def _option(action) -> str:
    text = ", ".join(action.option_strings)
    if action.choices:
        text += " {" + ",".join(str(c) for c in action.choices) + "}"
    return text


def _commands(parser) -> dict:
    out = {}
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, sub in action.choices.items():
            entry = {
                "arguments": [
                    a.dest + (" {" + ",".join(map(str, a.choices)) + "}" if a.choices else "")
                    for a in sub._actions
                    if not a.option_strings and not isinstance(a, argparse._SubParsersAction)
                ],
                "options": sorted(_option(a) for a in sub._actions if a.option_strings and a.dest != "help"),
            }
            nested = _commands(sub)
            if nested:
                entry["subcommands"] = nested
            out[name] = entry
    return out


def config_and_cli_surface() -> dict:
    from chesssnake import cli, config

    settings = {}
    for section, field in config.Settings.model_fields.items():
        for key in field.annotation.model_fields:
            settings[f"{section}.{key}"] = config.env_name(section, key)
    return {"settings": settings, "commands": _commands(cli.build_parser())}


def surface() -> dict:
    return {"python": python_surface(), "rest": rest_surface(), "config and cli": config_and_cli_surface()}


def _render(data) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


@pytest.mark.parametrize("part", ["python", "rest", "config and cli"])
def test_public_api_is_unchanged(part):
    expected = json.loads(EXPECTED.read_text())[part]
    actual = json.loads(_render(surface()[part]))  # the same JSON round trip as the file
    assert actual == expected, (
        f"the public {part} API changed. If that is intended, regenerate {EXPECTED.name} "
        f"(uv run python -m tests.config.test_public_api --write) and review its diff."
    )


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        sys.exit("usage: python -m tests.config.test_public_api --write")
    EXPECTED.write_text(_render(surface()))
    print(f"wrote {EXPECTED}")
