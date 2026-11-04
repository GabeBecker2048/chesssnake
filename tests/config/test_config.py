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
    ("api", "registration"): "CHESSSNAKE__API__REGISTRATION",
    ("api", "session_lifetime_days"): "CHESSSNAKE__API__SESSION_LIFETIME_DAYS",
    ("database", "url"): "CHESSSNAKE__DATABASE__URL",
    ("web", "enabled"): "CHESSSNAKE__WEB__ENABLED",
    ("database", "pool_min_size"): "CHESSSNAKE__DATABASE__POOL_MIN_SIZE",
    ("database", "pool_max_size"): "CHESSSNAKE__DATABASE__POOL_MAX_SIZE",
    ("database", "init_schema"): "CHESSSNAKE__DATABASE__INIT_SCHEMA",
    ("database", "sqlite_busy_timeout"): "CHESSSNAKE__DATABASE__SQLITE_BUSY_TIMEOUT",
    **{
        ("websocket", key): f"CHESSSNAKE__WEBSOCKET__{key.upper()}"
        for key in (
            "enabled",
            "max_connections",
            "max_pending_auth",
            "max_connections_per_user",
            "max_subscriptions",
            "auth_timeout_seconds",
            "reauth_interval_seconds",
            "send_queue_size",
            "ping_interval_seconds",
            "ping_timeout_seconds",
            "max_message_bytes",
            "compression",
            "worker_threads",
            "shutdown_timeout_seconds",
            "allowed_origins",
        )
    },
    ("client", "api_url"): "CHESSSNAKE__CLIENT__API_URL",
    ("client", "token"): "CHESSSNAKE__CLIENT__TOKEN",
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
    assert settings.api.registration == "closed"
    assert settings.api.session_lifetime_days == 30
    assert settings.database.url is None
    assert settings.database.pool_min_size == 1
    assert settings.database.pool_max_size == 10
    assert settings.source("api", "port") == "default"
    # Websockets are opt-in: a server that never heard of them behaves as 0.12 did.
    assert settings.websocket.enabled is False
    assert settings.websocket.allowed_origins == ["*"]
    assert settings.websocket.compression is False
    # The web UI, unlike websockets, is on unless turned off.
    assert settings.web.enabled is True


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


def test_registration_is_closed_unless_opened(tmp_path):
    assert resolve(environ={}, cwd=tmp_path).api.registration == "closed"
    settings = resolve(environ={"CHESSSNAKE__API__REGISTRATION": "open"}, cwd=tmp_path)
    assert settings.api.registration == "open"
    with pytest.raises(ConfigError, match="registration"):
        resolve(environ={"CHESSSNAKE__API__REGISTRATION": "anyone"}, cwd=tmp_path)


def test_session_lifetime_is_bounded(tmp_path):
    for bad in ("0", "3651"):
        with pytest.raises(ConfigError, match="session_lifetime_days"):
            resolve(environ={"CHESSSNAKE__API__SESSION_LIFETIME_DAYS": bad}, cwd=tmp_path)


def test_the_retired_api_key_settings_are_refused_in_a_file(tmp_path):
    """0.11's shared key is gone; a config file still naming it fails loudly instead of being ignored."""
    write(tmp_path, '[api]\nrequire_auth = true\napi_key = "k"\n')
    with pytest.raises(ConfigError, match="require_auth"):
        resolve(environ={}, cwd=tmp_path)


def test_there_are_no_advisories_by_default(tmp_path):
    assert resolve(environ={}, cwd=tmp_path).advisories() == []


# --- Redaction -------------------------------------------------------------


def test_secrets_are_redacted_by_default(tmp_path):
    settings = resolve(
        environ={
            "CHESSSNAKE__CLIENT__TOKEN": "sup3rsecret",
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
    settings = resolve(environ={"CHESSSNAKE__CLIENT__TOKEN": "sup3rsecret"}, cwd=tmp_path)
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
    import re

    # Split into [section] bodies, so a key is only documented where it belongs:
    # matching the bare word would pass for `port` because the text mentions it.
    bodies = dict(re.findall(r"^\[(\w+)\]\n(.*?)(?=^\[\w+\]|\Z)", text, re.M | re.S))
    for section, key, _ in config.iter_schema():
        if section == "client":
            # Env-only settings are documented by their variable name rather than a
            # TOML key, since writing them in the file is an error.
            assert env_name(section, key) in text, f"{section}.{key} is undocumented in the packaged config file"
            continue
        line = re.compile(rf"^#? ?{key} = ", re.M)
        assert line.search(bodies.get(section, "")), f"[{section}] {key} is undocumented in the packaged config file"


def test_packaged_default_leaves_credentials_unset(tmp_path):
    """Shipping a default password or key would be worse than shipping nothing."""
    (tmp_path / config.CONFIG_FILENAME).write_text(config.default_config_text())
    settings = resolve(environ={}, cwd=tmp_path)
    assert settings.client.token is None
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
    assert game.TOKEN_ENV == env_name("client", "token")


def test_the_credentials_file_honours_the_same_home_variable():
    """remote/credentials.py hardcodes CHESSSNAKE_HOME for the same reason."""
    from chesssnake.remote import credentials

    assert credentials.HOME_ENV == config.HOME_ENV


def test_sql_auth_error_names_the_current_env_var():
    """db/ deliberately does not import config, so CI enforces the message stays in sync."""
    from chesssnake.db import errors

    assert env_name("database", "url") in str(errors.SQLAuthError())


def test_settings_is_constructible_without_any_layers():
    """create_app(Settings()) must work for tests and embedding."""
    assert Settings().api.port == 8000


# --- [websocket] --------------------------------------------------------------


def test_allowed_origins_from_the_environment_are_comma_separated():
    settings = resolve(
        environ={"CHESSSNAKE__WEBSOCKET__ALLOWED_ORIGINS": " https://Chess.Example/ ,http://localhost:5173"},
        cwd="/nonexistent",
    )
    assert settings.websocket.allowed_origins == ["https://chess.example", "http://localhost:5173"]


def test_allowed_origins_from_a_file_are_a_list(tmp_path):
    path = write(tmp_path, '[websocket]\nallowed_origins = ["https://chess.example"]\n')
    settings = resolve(config_path=path, environ={}, cwd=tmp_path)
    assert settings.websocket.allowed_origins == ["https://chess.example"]


@pytest.mark.parametrize("value", ["*,https://chess.example", ",", ""])
def test_allowed_origins_rejects_a_wildcard_mixed_in_or_nothing(value):
    with pytest.raises(ConfigError, match="allowed_origins"):
        resolve(environ={"CHESSSNAKE__WEBSOCKET__ALLOWED_ORIGINS": value}, cwd="/nonexistent")


def test_origin_allowed():
    from chesssnake.config import WebsocketSettings

    anyone = WebsocketSettings()
    assert anyone.origin_allowed("https://anything.example") and anyone.origin_allowed(None)
    listed = WebsocketSettings(allowed_origins=["https://chess.example"])
    assert listed.origin_allowed("https://CHESS.example/")
    assert not listed.origin_allowed("https://chess.example.evil")
    assert listed.origin_allowed(None), "no Origin: not a browser, and the token is the gate"


@pytest.mark.parametrize(
    "env",
    [
        {"MAX_CONNECTIONS": "5", "MAX_CONNECTIONS_PER_USER": "6"},
        {"MAX_CONNECTIONS": "5", "MAX_PENDING_AUTH": "6"},
        {"PING_TIMEOUT_SECONDS": "0"},
        {"AUTH_TIMEOUT_SECONDS": "0"},
        {"MAX_MESSAGE_BYTES": "100"},
    ],
    ids=["per-user-over-total", "pending-over-total", "ping-timeout-zero", "auth-timeout-zero", "tiny-messages"],
)
def test_websocket_limits_that_cannot_work_are_refused(env):
    environ = {f"CHESSSNAKE__WEBSOCKET__{k}": v for k, v in env.items()}
    with pytest.raises(ConfigError):
        resolve(environ=environ, cwd="/nonexistent")


def test_config_show_prints_origins_comma_joined():
    settings = resolve(
        environ={"CHESSSNAKE__WEBSOCKET__ALLOWED_ORIGINS": "https://a.example,https://b.example"},
        cwd="/nonexistent",
    )
    shown = config.format_settings(settings)
    assert "allowed_origins" in shown and "https://a.example,https://b.example" in shown
