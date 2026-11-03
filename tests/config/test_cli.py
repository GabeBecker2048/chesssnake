"""
Tests for the ``chesssnake`` command-line interface.

These drive :func:`chesssnake.cli.main` in-process. Only the subcommands that
resolve and print configuration are covered; ``api-endpoint`` is not started
(that would block on uvicorn), but the layer it would hand to the server is
tested directly through ``_overrides``.
"""

import io
import json
import os

import pytest

from chesssnake import config
from chesssnake.cli import main


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Run each test in an empty directory with no chesssnake variables set."""
    for name in list(os.environ):
        if name.startswith("CHESSSNAKE"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def show(capsys, *args):
    main(["config", "show", *args])
    return capsys.readouterr().out


def test_config_show_lists_every_setting(capsys):
    out = show(capsys)
    for section, key, _ in config.iter_schema():
        assert key in out
        assert f"[{section}]" in out


def test_config_show_reports_defaults(capsys):
    assert "(default)" in show(capsys)


def test_config_show_reports_env_source(capsys, monkeypatch):
    monkeypatch.setenv("CHESSSNAKE__API__PORT", "9001")
    out = show(capsys)
    assert "9001" in out
    assert "(env: CHESSSNAKE__API__PORT)" in out


def test_config_show_reports_cli_source(capsys):
    out = show(capsys, "--port", "9002")
    assert "9002" in out
    assert "(cli: --port)" in out


def test_cli_flag_beats_environment(capsys, monkeypatch):
    monkeypatch.setenv("CHESSSNAKE__API__PORT", "9001")
    out = show(capsys, "--port", "9002")
    assert "9002" in out and "(cli: --port)" in out


def test_config_show_json(capsys, monkeypatch):
    monkeypatch.setenv("CHESSSNAKE__API__PORT", "9001")
    payload = json.loads(show(capsys, "--format", "json"))
    assert payload["settings"]["api"]["port"] == {"value": "9001", "source": "env: CHESSSNAKE__API__PORT"}
    assert payload["settings"]["api"]["host"]["source"] == "default"


def test_config_show_redacts_by_default(capsys, monkeypatch):
    monkeypatch.setenv("CHESSSNAKE__API__API_KEY", "sup3rsecret")
    assert "sup3rsecret" not in show(capsys)


def test_config_show_can_reveal_secrets(capsys, monkeypatch):
    monkeypatch.setenv("CHESSSNAKE__CLIENT__TOKEN", "sup3rsecret")
    assert "sup3rsecret" not in show(capsys)
    assert "sup3rsecret" in show(capsys, "--show-secrets")


def test_registration_flag(capsys):
    out = show(capsys, "--registration", "open")
    assert "(cli: --registration)" in out


def test_set_flag_sets_any_key(capsys):
    out = show(capsys, "-o", "database.pool_max_size=20")
    assert "20" in out
    assert "(cli: --set database.pool_max_size)" in out


def test_named_flag_beats_set_flag(capsys):
    out = show(capsys, "-o", "api.port=1111", "--port", "2222")
    assert "2222" in out and "(cli: --port)" in out


def test_malformed_set_flag_is_rejected():
    with pytest.raises(SystemExit, match="section.key=value"):
        main(["config", "show", "-o", "nonsense"])


def test_config_flag_reads_the_named_file(capsys, tmp_path):
    path = tmp_path / "custom.toml"
    path.write_text("[api]\nport = 4321\n")
    out = show(capsys, "--config", str(path))
    assert "4321" in out
    assert f"(file: {path})" in out


def test_config_show_reports_invalid_config_and_exits_nonzero(capsys, monkeypatch):
    monkeypatch.setenv("CHESSSNAKE__API__REGISTRATION", "anyone")
    with pytest.raises(SystemExit) as exc:
        main(["config", "show"])
    assert exc.value.code == 1
    assert "registration" in capsys.readouterr().err


def test_api_endpoint_exits_on_invalid_config(monkeypatch):
    """A misconfiguration stops the server rather than serving with a guessed value."""
    monkeypatch.setenv("CHESSSNAKE__API__REGISTRATION", "anyone")
    with pytest.raises(SystemExit) as exc:
        main(["api-endpoint"])
    assert "registration" in str(exc.value)


def test_the_retired_auth_flags_are_gone():
    for flag in ("--api-key", "--require-auth"):
        with pytest.raises(SystemExit):
            main(["api-endpoint", flag, "x"])


def test_config_init_writes_to_cwd(capsys, isolated_env):
    main(["config", "init"])
    written = isolated_env / config.CONFIG_FILENAME
    assert written.is_file()
    assert str(written) in capsys.readouterr().out


def test_config_init_writes_to_chesssnake_home(capsys, monkeypatch, tmp_path):
    home = tmp_path / "cshome"
    monkeypatch.setenv(config.HOME_ENV, str(home))
    main(["config", "init"])
    assert (home / config.CONFIG_FILENAME).is_file()


def test_config_init_output_is_immediately_usable(capsys, isolated_env):
    """The file `config init` writes must be found and loaded by the next command."""
    main(["config", "init"])
    capsys.readouterr()
    out = show(capsys)
    assert f"(file: {isolated_env / config.CONFIG_FILENAME})" in out


def test_config_init_refuses_to_overwrite(capsys, isolated_env):
    main(["config", "init"])
    with pytest.raises(SystemExit, match="already exists"):
        main(["config", "init"])


def test_config_init_force_overwrites(capsys, isolated_env):
    main(["config", "init"])
    written = isolated_env / config.CONFIG_FILENAME
    written.write_text("[api]\nport = 1\n")
    main(["config", "init", "--force"])
    assert written.read_text() == config.default_config_text()


def test_config_init_warns_when_cwd_shadows_chesssnake_home(capsys, monkeypatch, isolated_env):
    """./chesssnake.toml is searched before $CHESSSNAKE_HOME, so it would win."""
    (isolated_env / config.CONFIG_FILENAME).write_text("[api]\nport = 1\n")
    home = isolated_env / "cshome"
    monkeypatch.setenv(config.HOME_ENV, str(home))
    main(["config", "init"])
    assert "takes precedence" in capsys.readouterr().err


def test_missing_subcommand_is_an_error():
    with pytest.raises(SystemExit):
        main([])


# --- user accounts and init-db ---------------------------------------------
#
# These run against a throwaway SQLite file. They need SQLAlchemy (the `api`
# extra) but no server, so they live here rather than in tests/integration.


@pytest.fixture
def database(isolated_env):
    pytest.importorskip("sqlalchemy")
    from chesssnake.db import engine

    url = f"sqlite:///{isolated_env / 'cli.db'}"
    engine.dispose_engine()
    main(["init-db", "--database-url", url])
    return url


def user_cmd(capsys, database, *args, password=None, monkeypatch=None):
    capsys.readouterr()  # drop anything printed before, e.g. by the database fixture
    if password is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
        args = (*args, "--password-stdin")
    main(["user", *args, "--database-url", database])
    return json.loads(capsys.readouterr().out)


def test_user_create_and_show(capsys, database, monkeypatch):
    capsys.readouterr()
    alice = user_cmd(capsys, database, "create", "Alice", "--admin", password="alice-password", monkeypatch=monkeypatch)
    assert alice["role"] == "admin" and alice["has_password"] is True and isinstance(alice["id"], int)
    bot = user_cmd(capsys, database, "create", "bot", "--no-password")
    assert bot["role"] == "user" and bot["has_password"] is False and bot["id"] > alice["id"]
    assert user_cmd(capsys, database, "show", "alice") == alice
    assert user_cmd(capsys, database, "show", str(bot["id"]))["username"] == "bot"


def test_user_create_without_a_terminal_needs_stdin_or_no_password(database, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(SystemExit, match="--password-stdin"):
        main(["user", "create", "carol", "--database-url", database])


def test_user_set_role_rename_link_and_disable(capsys, database, monkeypatch):
    capsys.readouterr()
    user_cmd(capsys, database, "create", "boss", "--admin", "--no-password")
    user_cmd(capsys, database, "create", "carol", "--no-password")
    assert user_cmd(capsys, database, "set-role", "carol", "admin")["role"] == "admin"
    assert user_cmd(capsys, database, "rename", "carol", "Caroline")["username"] == "Caroline"
    linked = user_cmd(capsys, database, "link", "caroline", "discord", "123456789012345678")
    assert linked["identities"] == [{"provider": "discord", "external_id": "123456789012345678"}]
    assert user_cmd(capsys, database, "disable", "caroline")["disabled_at"] is not None
    assert user_cmd(capsys, database, "enable", "caroline")["disabled_at"] is None
    updated = user_cmd(capsys, database, "set-password", "caroline", password="a-new-password", monkeypatch=monkeypatch)
    assert updated["has_password"] is True


def test_user_token_prints_the_secret_alone(capsys, database):
    pytest.importorskip("argon2")
    user_cmd(capsys, database, "create", "bot", "--admin", "--no-password")
    main(["user", "token", "bot", "--name", "discord-bot", "--database-url", database])
    out, err = capsys.readouterr()
    assert out.strip().startswith("css_") and len(out.strip().splitlines()) == 1
    assert "discord-bot" in err and "not shown again" in err


def test_user_errors_exit_with_the_message(capsys, database, monkeypatch):
    user_cmd(capsys, database, "create", "dave", "--no-password")
    with pytest.raises(SystemExit, match="already taken"):
        main(["user", "create", "DAVE", "--no-password", "--database-url", database])
    with pytest.raises(SystemExit, match="No user"):
        main(["user", "show", "nobody", "--database-url", database])
    with pytest.raises(SystemExit, match="not only digits"):
        main(["user", "create", "1234", "--no-password", "--database-url", database])
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    with pytest.raises(SystemExit, match="8 to 256"):
        main(["user", "create", "erin", "--password-stdin", "--database-url", database])


def test_init_db_drop_starts_over(capsys, database):
    user_cmd(capsys, database, "create", "erin", "--no-password")
    main(["init-db", "--drop", "--database-url", database])
    assert "Dropped" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="No user"):
        main(["user", "show", "erin", "--database-url", database])


def test_init_db_refuses_a_database_from_an_older_chesssnake(capsys, isolated_env):
    """create_all never alters a table, so an old-shaped one must be called out, not half-used."""
    pytest.importorskip("sqlalchemy")
    import sqlite3

    path = isolated_env / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE challenges (group_id BIGINT, challenger BIGINT, challenged BIGINT)")
    with pytest.raises(SystemExit, match="init-db --drop"):
        main(["init-db", "--database-url", f"sqlite:///{path}"])
    main(["init-db", "--drop", "--database-url", f"sqlite:///{path}"])
    assert "initialized" in capsys.readouterr().out


# --- client commands -----------------------------------------------------------


def test_play_needs_a_game_or_an_opponent(monkeypatch):
    pytest.importorskip("requests")
    with pytest.raises(SystemExit, match="--game ID, or --vs USER"):
        main(["play", "--api-url", "http://localhost:1"])


def test_names_and_me_are_for_local_games_only():
    for extra in (["--white-name", "Al"], ["--me", "0"]):
        with pytest.raises(SystemExit, match="only for --local"):
            main(["play", "--api-url", "http://localhost:1", "--game", "1", *extra])


def test_local_me_is_a_side():
    with pytest.raises(SystemExit, match="--me is 0"):
        main(["play", "--local", "--me", "7"])


def test_a_player_is_an_id_or_a_valid_username(capsys):
    with pytest.raises(SystemExit):
        main(["challenge", "not valid", "--api-url", "http://localhost:1"])
    assert "neither a user id nor a username" in capsys.readouterr().err


def test_client_commands_without_a_login_say_how(monkeypatch, isolated_env):
    pytest.importorskip("requests")
    monkeypatch.setenv("CHESSSNAKE_HOME", str(isolated_env))
    for command in (["whoami"], ["games"], ["challenges"], ["challenge", "bob"], ["accept", "1"]):
        with pytest.raises(SystemExit, match="chesssnake login"):
            main([*command, "--api-url", "http://localhost:1"])


def test_logout_without_a_login(capsys, monkeypatch, isolated_env):
    monkeypatch.setenv("CHESSSNAKE_HOME", str(isolated_env))
    main(["logout", "--api-url", "http://localhost:1"])
    assert "Not logged in" in capsys.readouterr().out


# --- the credentials file --------------------------------------------------------


def test_credentials_never_land_in_the_working_directory(isolated_env, monkeypatch, tmp_path):
    from chesssnake.remote import credentials

    monkeypatch.delenv("CHESSSNAKE_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    path = credentials.save("https://chess.example/", "css_secret", "alice")
    assert path == tmp_path / "xdg" / "chesssnake" / "credentials.json"
    assert not (isolated_env / "credentials.json").exists()
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert credentials.credentials_path().parent.name == "chesssnake"
    assert credentials.credentials_path().parent.parent.name == ".config"


def test_credentials_are_private_and_keyed_by_endpoint(monkeypatch, tmp_path):
    import os
    import stat

    from chesssnake.remote import credentials

    monkeypatch.setenv("CHESSSNAKE_HOME", str(tmp_path / "home"))
    path = credentials.save("HTTPS://Chess.Example/", "css_one", "alice")
    credentials.save("http://other.example", "css_two", "bob")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    assert credentials.load("https://chess.example") == {"token": "css_one", "username": "alice"}
    assert credentials.load("http://other.example/")["token"] == "css_two"
    assert credentials.forget("https://chess.example") is True
    assert credentials.load("https://chess.example") is None
    assert credentials.load("http://other.example")["token"] == "css_two"
    assert not list(path.parent.glob(".credentials-*")), "no temporary files left behind"
