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
