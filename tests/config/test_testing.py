"""
``chesssnake.testing``: the test server bot authors use (0.15.4).

Run in a subprocess, the way a bot's own test suite would use it: the server's
database handle is per process, and this suite's integration tests hold one.
"""

import subprocess
import sys
import textwrap

USER_TESTS = """
import asyncio

import pytest

from chesssnake import Color
from chesssnake.db.errors import NotYourTurnError
from chesssnake.testing import TestServer

pytest_plugins = ["chesssnake.testing.pytest_plugin"]


def test_the_admin_fixture_plays(chesssnake_server, chesssnake_admin):
    alice, bob = chesssnake_server.user("alice"), chesssnake_server.user("bob")
    game = chesssnake_admin.create_game(alice, bob)
    chesssnake_admin.as_user(alice).move(game, "e4")
    with pytest.raises(NotYourTurnError):
        chesssnake_admin.as_user(alice).move(game.id, "d4")
    assert chesssnake_admin.get_game(game).to_move is Color.BLACK


def test_each_test_starts_empty(chesssnake_admin):
    assert chesssnake_admin.search_users() == [chesssnake_admin.me()]


def test_a_user_with_a_password_logs_in(chesssnake_server):
    chesssnake_server.user("carol", password="carol-password")
    client = chesssnake_server.client()
    client.token = None
    assert client.login("carol", "carol-password").user.username == "carol"


def test_the_async_admin(chesssnake_server, chesssnake_async_admin):
    alice = chesssnake_server.user("alice")

    async def go():
        me = await chesssnake_async_admin.me()
        assert me.is_admin
        return await chesssnake_async_admin.as_user(alice).current_games()

    assert asyncio.run(go()) == []


def test_live_server_websockets():
    with TestServer(live=True) as server:
        alice, bob = server.user("alice"), server.user("bob")

        async def go():
            bot = server.client(asynchronous=True)
            async with bot.events() as stream:
                await stream.follow(all=True)
                assert (await stream.__anext__())["type"] == "following"
                game = await bot.create_game(alice, bob, group_id=3)
                assert (await stream.__anext__())["type"] == "game_started"
                await bot.as_user(alice).move(game, "e4")
                event = await stream.__anext__()
                assert event["type"] == "game" and event["state"]["last_move"]["san"] == "e4"
            await bot.aclose()

        asyncio.run(go())
"""


def test_testserver_and_its_pytest_plugin(tmp_path):
    (tmp_path / "test_bot.py").write_text(textwrap.dedent(USER_TESTS))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "5 passed" in result.stdout
