"""
Tests for the ``chesssnake`` command-line interface.

These drive :func:`chesssnake.cli.main` in-process. Only the subcommands that
resolve and print configuration are covered; ``api-endpoint`` is not started
(that would block on uvicorn), but the layer it would hand to the server is
tested directly through ``_overrides``.
"""

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
    monkeypatch.setenv("CHESSSNAKE__API__API_KEY", "sup3rsecret")
    assert "sup3rsecret" in show(capsys, "--show-secrets")


def test_config_show_prints_advisories(capsys, monkeypatch):
    monkeypatch.setenv("CHESSSNAKE__API__API_KEY", "k")
    assert "require_auth" in show(capsys)


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
    monkeypatch.setenv("CHESSSNAKE__API__REQUIRE_AUTH", "1")
    with pytest.raises(SystemExit) as exc:
        main(["config", "show"])
    assert exc.value.code == 1
    assert "require_auth" in capsys.readouterr().err


def test_api_endpoint_exits_on_invalid_config(monkeypatch):
    """Auth misconfiguration must stop the server rather than serving unauthenticated."""
    monkeypatch.setenv("CHESSSNAKE__API__REQUIRE_AUTH", "1")
    with pytest.raises(SystemExit) as exc:
        main(["api-endpoint"])
    assert config.env_name("api", "api_key") in str(exc.value)


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


def user_cmd(capsys, database, *args):
    main(["user", *args, "--database-url", database])
    return json.loads(capsys.readouterr().out)


def test_user_create_and_show(capsys, database):
    capsys.readouterr()
    alice = user_cmd(capsys, database, "create", "Alice", "--admin")
    assert alice["role"] == "admin" and isinstance(alice["id"], int)
    bob = user_cmd(capsys, database, "create", "bob")
    assert bob["role"] == "user" and bob["id"] > alice["id"]
    assert user_cmd(capsys, database, "show", "alice") == alice
    assert user_cmd(capsys, database, "show", str(bob["id"]))["username"] == "bob"


def test_user_set_role_rename_and_link(capsys, database):
    capsys.readouterr()
    user_cmd(capsys, database, "create", "carol")
    assert user_cmd(capsys, database, "set-role", "carol", "admin")["role"] == "admin"
    assert user_cmd(capsys, database, "rename", "carol", "Caroline")["username"] == "Caroline"
    linked = user_cmd(capsys, database, "link", "caroline", "discord", "123456789012345678")
    assert linked["identities"] == [{"provider": "discord", "external_id": "123456789012345678"}]


def test_user_errors_exit_with_the_message(capsys, database):
    main(["user", "create", "dave", "--database-url", database])
    with pytest.raises(SystemExit, match="already taken"):
        main(["user", "create", "DAVE", "--database-url", database])
    with pytest.raises(SystemExit, match="No user"):
        main(["user", "show", "nobody", "--database-url", database])
    with pytest.raises(SystemExit, match="not only digits"):
        main(["user", "create", "1234", "--database-url", database])


def test_init_db_drop_starts_over(capsys, database):
    main(["user", "create", "erin", "--database-url", database])
    main(["init-db", "--drop", "--database-url", database])
    assert "Dropped" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="No user"):
        main(["user", "show", "erin", "--database-url", database])


# --- play flags --------------------------------------------------------------


def test_remote_play_needs_both_players(monkeypatch):
    pytest.importorskip("requests")
    with pytest.raises(SystemExit, match="--white and --black"):
        main(["play", "--api-url", "http://localhost:1", "--white", "alice"])


def test_names_are_for_local_games_only():
    with pytest.raises(SystemExit, match="only for --local"):
        main(["play", "--api-url", "http://localhost:1", "--white", "a1", "--black", "b1", "--white-name", "Al"])


def test_local_me_is_a_side_not_a_username():
    with pytest.raises(SystemExit, match="--me is 0"):
        main(["play", "--local", "--me", "alice"])


def test_a_player_is_an_id_or_a_valid_username(capsys):
    with pytest.raises(SystemExit):
        main(["play", "--local", "--white", "not valid"])
    assert "neither a user id nor a username" in capsys.readouterr().err
