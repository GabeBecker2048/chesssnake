"""
Unit tests for the configuration system.

These exercise the schema, the four-layer precedence, file discovery, provenance,
and redaction. No database or server is involved; the environment is injected as
a plain dict rather than mutated, so tests never leak into one another.
"""

import pytest

from chesssnake import config
from chesssnake.config import ConfigError, Override, Settings, env_name, resolve

# The full set of derived names. Asserting a literal snapshot is what makes the
# "env names are mechanical" premise a checked invariant rather than a claim:
# renaming a field or section cannot silently change a deployment's env var.
EXPECTED_ENV_NAMES = {
    ("api", "host"): "CHESSSNAKE__API__HOST",
    ("api", "port"): "CHESSSNAKE__API__PORT",
    ("api", "require_auth"): "CHESSSNAKE__API__REQUIRE_AUTH",
    ("api", "api_key"): "CHESSSNAKE__API__API_KEY",
    ("database", "url"): "CHESSSNAKE__DATABASE__URL",
    ("database", "pool_min_size"): "CHESSSNAKE__DATABASE__POOL_MIN_SIZE",
    ("database", "pool_max_size"): "CHESSSNAKE__DATABASE__POOL_MAX_SIZE",
    ("database", "init_schema"): "CHESSSNAKE__DATABASE__INIT_SCHEMA",
    ("client", "api_url"): "CHESSSNAKE__CLIENT__API_URL",
    ("client", "api_key"): "CHESSSNAKE__CLIENT__API_KEY",
}


def write(tmp_path, text, name="chesssnake.toml"):
    path = tmp_path / name
    path.write_text(text)
    return path


# --- Schema ----------------------------------------------------------------


def test_env_names_are_derived_from_the_schema():
    derived = {(section, key): env_name(section, key) for section, key, _ in config.iter_schema()}
    assert derived == EXPECTED_ENV_NAMES


def test_every_setting_documents_itself():
    for section, key, _ in config.iter_schema():
        assert config.describe(section, key), f"{section}.{key} has no description"


def test_defaults():
    settings = resolve(environ={}, cwd="/nonexistent")
    assert settings.api.host == "127.0.0.1"
    assert settings.api.port == 8000
    assert settings.api.require_auth is False
    assert settings.database.url is None
    assert settings.database.pool_min_size == 1
    assert settings.database.pool_max_size == 10
    assert settings.source("api", "port") == "default"


# --- Precedence ------------------------------------------------------------


def test_env_overrides_file(tmp_path):
    path = write(tmp_path, "[api]\nport = 7777\n")
    settings = resolve(config_path=path, environ={"CHESSSNAKE__API__PORT": "8888"}, cwd=tmp_path)
    assert settings.api.port == 8888
    assert settings.source("api", "port") == "env: CHESSSNAKE__API__PORT"


def test_cli_overrides_env(tmp_path):
    settings = resolve(
        [Override("api", "port", 9999, "cli", "--port")],
        environ={"CHESSSNAKE__API__PORT": "8888"},
        cwd=tmp_path,
    )
    assert settings.api.port == 9999
    assert settings.source("api", "port") == "cli: --port"


def test_file_overrides_default(tmp_path):
    path = write(tmp_path, "[api]\nport = 7777\n")
    settings = resolve(config_path=path, environ={}, cwd=tmp_path)
    assert settings.api.port == 7777
    assert settings.source("api", "port") == f"file: {path}"


def test_layers_are_independent_per_key(tmp_path):
    """A higher layer setting one key must not shadow another key's lower layer."""
    path = write(tmp_path, "[api]\nport = 7777\nhost = '10.0.0.1'\n")
    settings = resolve(config_path=path, environ={"CHESSSNAKE__API__PORT": "8888"}, cwd=tmp_path)
    assert (settings.api.port, settings.api.host) == (8888, "10.0.0.1")
    assert settings.source("api", "host") == f"file: {path}"


# --- Type coercion ---------------------------------------------------------


@pytest.mark.parametrize("raw", ["1", "true", "True", "yes", "on"])
def test_truthy_env_strings(raw, tmp_path):
    settings = resolve(environ={"CHESSSNAKE__DATABASE__INIT_SCHEMA": raw}, cwd=tmp_path)
    assert settings.database.init_schema is True


@pytest.mark.parametrize("raw", ["0", "false", "False", "no", "off"])
def test_falsey_env_strings(raw, tmp_path):
    settings = resolve(environ={"CHESSSNAKE__DATABASE__INIT_SCHEMA": raw}, cwd=tmp_path)
    assert settings.database.init_schema is False


def test_bad_type_names_the_offending_layer(tmp_path):
    with pytest.raises(ConfigError) as exc:
        resolve(environ={"CHESSSNAKE__API__PORT": "not-a-number"}, cwd=tmp_path)
    assert "CHESSSNAKE__API__PORT" in str(exc.value)


# --- Discovery -------------------------------------------------------------


def test_explicit_path_beats_env_and_cwd(tmp_path):
    write(tmp_path, "[api]\nport = 1111\n")
    chosen = write(tmp_path, "[api]\nport = 2222\n", name="other.toml")
    other = write(tmp_path, "[api]\nport = 3333\n", name="env.toml")
    settings = resolve(config_path=chosen, environ={config.CONFIG_PATH_ENV: str(other)}, cwd=tmp_path)
    assert settings.api.port == 2222


def test_config_env_beats_cwd(tmp_path):
    write(tmp_path, "[api]\nport = 1111\n")
    other = write(tmp_path, "[api]\nport = 3333\n", name="env.toml")
    settings = resolve(environ={config.CONFIG_PATH_ENV: str(other)}, cwd=tmp_path)
    assert settings.api.port == 3333


def test_cwd_file_is_discovered(tmp_path):
    write(tmp_path, "[api]\nport = 1111\n")
    assert resolve(environ={}, cwd=tmp_path).api.port == 1111


def test_chesssnake_home_is_searched(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    write(home, "[api]\nport = 4444\n")
    empty = tmp_path / "elsewhere"
    empty.mkdir()
    settings = resolve(environ={config.HOME_ENV: str(home)}, cwd=empty)
    assert settings.api.port == 4444


def test_missing_explicit_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        resolve(config_path=tmp_path / "nope.toml", environ={}, cwd=tmp_path)


def test_missing_discovered_file_is_fine(tmp_path):
    assert resolve(environ={}, cwd=tmp_path).api.port == 8000


def test_malformed_toml_is_reported(tmp_path):
    path = write(tmp_path, "[api\nport = 1\n")
    with pytest.raises(ConfigError, match="Could not parse"):
        resolve(config_path=path, environ={}, cwd=tmp_path)


# --- Rejecting mistakes ----------------------------------------------------


def test_unknown_file_key_is_rejected(tmp_path):
    path = write(tmp_path, "[api]\nprot = 1\n")
    with pytest.raises(ConfigError) as exc:
        resolve(config_path=path, environ={}, cwd=tmp_path)
    assert "prot" in str(exc.value)


def test_unknown_section_is_rejected(tmp_path):
    path = write(tmp_path, "[nope]\nx = 1\n")
    with pytest.raises(ConfigError):
        resolve(config_path=path, environ={}, cwd=tmp_path)


def test_client_section_cannot_come_from_a_file(tmp_path):
    """The client never reads files, so accepting the key would make `config show` lie."""
    path = write(tmp_path, "[client]\napi_url = 'http://x'\n")
    with pytest.raises(ConfigError, match="only the environment"):
        resolve(config_path=path, environ={}, cwd=tmp_path)


def test_unknown_env_var_warns(tmp_path):
    with pytest.warns(UserWarning, match="CHESSSNAKE__API__PORTT"):
        resolve(environ={"CHESSSNAKE__API__PORTT": "1"}, cwd=tmp_path)


def test_pool_bounds_are_checked(tmp_path):
    with pytest.raises(ConfigError, match="pool_min_size"):
        resolve(environ={"CHESSSNAKE__DATABASE__POOL_MIN_SIZE": "50"}, cwd=tmp_path)


# --- Auth ------------------------------------------------------------------


def test_require_auth_without_a_key_fails_loudly(tmp_path):
    with pytest.raises(ConfigError) as exc:
        resolve(environ={"CHESSSNAKE__API__REQUIRE_AUTH": "1"}, cwd=tmp_path)
    assert env_name("api", "api_key") in str(exc.value)


def test_require_auth_with_a_key_is_accepted(tmp_path):
    settings = resolve(environ={"CHESSSNAKE__API__REQUIRE_AUTH": "1", "CHESSSNAKE__API__API_KEY": "k"}, cwd=tmp_path)
    assert settings.api.require_auth is True
    assert settings.advisories() == []


def test_key_without_require_auth_is_advised_against(tmp_path):
    """Upgrading from the old 'key set means auth on' behavior must not silently open the server."""
    settings = resolve(environ={"CHESSSNAKE__API__API_KEY": "k"}, cwd=tmp_path)
    assert any("require_auth" in note for note in settings.advisories())


# --- Redaction -------------------------------------------------------------


def test_secrets_are_redacted_by_default(tmp_path):
    settings = resolve(
        environ={
            "CHESSSNAKE__API__API_KEY": "sup3rsecret",
            "CHESSSNAKE__DATABASE__URL": "postgresql://bob:hunter2@db:5432/chess",
        },
        cwd=tmp_path,
    )
    out = config.format_settings(settings)
    assert "sup3rsecret" not in out
    assert "hunter2" not in out
    # The non-secret parts of a DSN are the useful parts; keep them visible.
    assert "db:5432/chess" in out


def test_show_secrets_reveals_them(tmp_path):
    settings = resolve(environ={"CHESSSNAKE__API__API_KEY": "sup3rsecret"}, cwd=tmp_path)
    assert "sup3rsecret" in config.format_settings(settings, show_secrets=True)


@pytest.mark.parametrize(
    "dsn,secret",
    [
        ("postgresql://u:pw@h:5432/db", "pw"),
        ("dbname='d' user='u' password='pw' host='h'", "pw"),
        ("postgresql://u:pw@h/db?sslmode=require", "pw"),
    ],
)
def test_redact_dsn_forms(dsn, secret):
    assert secret not in config.redact_dsn(dsn)


def test_redact_dsn_leaves_passwordless_urls_alone():
    dsn = "postgresql://postgres:@/postgres?host=/tmp/sock"
    assert config.redact_dsn(dsn) == dsn


def test_format_reports_sources(tmp_path):
    settings = resolve(environ={"CHESSSNAKE__API__PORT": "9001"}, cwd=tmp_path)
    assert "(env: CHESSSNAKE__API__PORT)" in config.format_settings(settings)


# --- The packaged default config file --------------------------------------


def test_packaged_default_is_valid(tmp_path):
    """A shipped default that doesn't load would break `config init` for everyone."""
    path = tmp_path / config.CONFIG_FILENAME
    path.write_text(config.default_config_text())
    settings = resolve(environ={}, cwd=tmp_path)
    assert settings.source("api", "port") == f"file: {path}"


def test_packaged_default_matches_the_built_in_defaults(tmp_path):
    """Every uncommented value in the file must equal the schema default."""
    (tmp_path / config.CONFIG_FILENAME).write_text(config.default_config_text())
    from_file = resolve(environ={}, cwd=tmp_path)
    built_in = Settings()
    for section, key, _ in config.iter_schema():
        assert getattr(getattr(from_file, section), key) == getattr(getattr(built_in, section), key), (
            f"{section}.{key} in the packaged config disagrees with the schema default"
        )


def test_packaged_default_documents_every_setting():
    """Adding a setting without documenting it in the shipped file fails here."""
    text = config.default_config_text()
    for section, key, _ in config.iter_schema():
        # Env-only settings are documented by their variable name rather than a
        # TOML key, since writing them in the file is an error.
        documented = key in text or env_name(section, key) in text
        assert documented, f"{section}.{key} is undocumented in the packaged config file"


def test_packaged_default_leaves_credentials_unset(tmp_path):
    """Shipping a default password or key would be worse than shipping nothing."""
    (tmp_path / config.CONFIG_FILENAME).write_text(config.default_config_text())
    settings = resolve(environ={}, cwd=tmp_path)
    assert settings.api.api_key is None
    assert settings.database.url is None


def test_write_default_config_targets_cwd_without_chesssnake_home(tmp_path):
    path = config.write_default_config(environ={}, cwd=tmp_path)
    assert path == tmp_path / config.CONFIG_FILENAME
    assert path.read_text() == config.default_config_text()


def test_write_default_config_prefers_chesssnake_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    path = config.write_default_config(environ={config.HOME_ENV: str(home)}, cwd=elsewhere)
    assert path == home / config.CONFIG_FILENAME


def test_write_default_config_creates_missing_directories(tmp_path):
    home = tmp_path / "deep" / "nested"
    path = config.write_default_config(environ={config.HOME_ENV: str(home)}, cwd=tmp_path)
    assert path.is_file()


def test_write_default_config_refuses_to_overwrite(tmp_path):
    config.write_default_config(environ={}, cwd=tmp_path)
    with pytest.raises(ConfigError, match="already exists"):
        config.write_default_config(environ={}, cwd=tmp_path)


def test_write_default_config_force_overwrites(tmp_path):
    path = config.write_default_config(environ={}, cwd=tmp_path)
    path.write_text("[api]\nport = 1\n")
    config.write_default_config(force=True, environ={}, cwd=tmp_path)
    assert path.read_text() == config.default_config_text()


# --- Cross-module invariants -----------------------------------------------


def test_client_env_constants_match_the_schema():
    """remote/game.py hardcodes these names to avoid importing pydantic."""
    from chesssnake.remote import game

    assert game.API_URL_ENV == env_name("client", "api_url")
    assert game.API_KEY_ENV == env_name("client", "api_key")


def test_sql_auth_error_names_the_current_env_var():
    """db/ deliberately does not import config, so CI enforces the message stays in sync."""
    from chesssnake.db import errors

    assert env_name("database", "url") in str(errors.SQLAuthError())


def test_settings_is_constructible_without_any_layers():
    """create_app(Settings()) must work for tests and embedding."""
    assert Settings().api.port == 8000
