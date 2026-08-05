"""
Centralized configuration for the chesssnake api-endpoint and database layer.

Every setting is declared exactly once, as a field on one of the section models
below (:class:`ApiSettings`, :class:`DatabaseSettings`, :class:`ClientSettings`).
That declaration is the single source of truth: defaults, types, help text, and
the environment-variable name are all derived from it, so adding a setting means
adding one field and nothing else.

**Environment variable names are mechanical.** A key ``k`` in section ``s`` is
always read from ``CHESSSNAKE__{S}__{K}`` (uppercased) — ``[api] port`` is
``CHESSSNAKE__API__PORT``. There is no mapping table to keep in sync; see
:func:`env_name`.

**Values are resolved from four layers**, each overriding the ones before it:

1. built-in defaults (the field defaults below),
2. the TOML config file (see :func:`find_config_file`),
3. environment variables,
4. explicit command-line overrides.

:func:`resolve` performs that merge and records, for every key, which layer the
effective value came from. That provenance is what ``chesssnake config show``
prints, and it is the fastest way to answer "why is this value what it is?".

Two bootstrap variables are deliberately *not* schema-derived, because they are
consulted before the schema is applied: ``CHESSSNAKE_CONFIG`` (an explicit config
file path) and ``CHESSSNAKE_HOME`` (a directory searched for ``chesssnake.toml``).
Note they use a single underscore, so they never collide with the ``CHESSSNAKE__``
setting prefix.

This module requires pydantic and is part of the ``api`` extra; it is never
imported on the local-game path, which stays dependency-free.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
import warnings
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .assets import asset_path

#: Prefix and separator for schema-derived environment variables.
ENV_PREFIX = "CHESSSNAKE"
ENV_SEPARATOR = "__"

#: Bootstrap variables, read before the schema is applied (single underscore).
CONFIG_PATH_ENV = "CHESSSNAKE_CONFIG"
HOME_ENV = "CHESSSNAKE_HOME"

#: Name of the config file, both when searching for one and when writing one.
#: The packaged default lives at ``chesssnake/data/chesssnake.toml``.
CONFIG_FILENAME = "chesssnake.toml"

#: Placeholder substituted for secret values unless secrets are explicitly shown.
REDACTED = "********"


class ConfigError(Exception):
    """Configuration could not be loaded or is invalid."""


def _secret(default: Any, description: str, **extra: Any) -> Any:
    """Declare a field whose value must be redacted in human-readable output."""
    return Field(default=default, description=description, json_schema_extra={"secret": True, **extra})


def _marker(section: str, key: str, name: str) -> Any:
    extra = _section_model(section).model_fields[key].json_schema_extra
    return extra.get(name) if isinstance(extra, dict) else None


def redact_dsn(dsn: str) -> str:
    """
    Blank out the password in a connection string, keeping the rest legible.

    Showing the host, port, and database name is the whole point of printing a
    DSN back to someone, so only the password is replaced. Handles both the URL
    and the keyword forms without importing psycopg2 — this module must stay
    usable wherever the config is inspected.

    :param dsn: A database connection string.
    :return: The same string with any password replaced.
    """
    url = urlsplit(dsn)
    if url.scheme and url.netloc and url.password:
        userinfo = f"{url.username or ''}:{REDACTED}@"
        host = url.netloc.rsplit("@", 1)[-1]
        return urlunsplit(url._replace(netloc=userinfo + host))
    return re.sub(r"(password\s*=\s*)('[^']*'|\"[^\"]*\"|\S+)", rf"\1{REDACTED}", dsn)


class _Section(BaseModel):
    # Reject unknown keys so a typo in the TOML file fails at startup instead of
    # being silently ignored -- the worst failure mode of stringly-typed config.
    model_config = ConfigDict(extra="forbid")


class ApiSettings(_Section):
    """Settings for the api-endpoint server."""

    host: str = Field(default="127.0.0.1", description="Address the api-endpoint binds to.")
    port: int = Field(default=8000, ge=1, le=65535, description="Port the api-endpoint binds to.")
    require_auth: bool = Field(
        default=False,
        description="Require a matching X-API-Key header on all /v1 routes. When true, api_key must be set.",
    )
    api_key: str | None = _secret(None, "The key clients must send as X-API-Key. Only used when require_auth is true.")


class DatabaseSettings(_Section):
    """Settings for the persistence layer."""

    url: str | None = Field(
        default=None,
        description="Database DSN, e.g. postgresql://user:password@localhost:5432/chess. The scheme selects the backend.",
        json_schema_extra={"dsn": True},
    )
    pool_min_size: int = Field(default=1, ge=1, description="Minimum number of pooled database connections.")
    pool_max_size: int = Field(default=10, ge=1, description="Maximum number of pooled database connections.")
    init_schema: bool = Field(default=False, description="Create the database schema when the api-endpoint starts.")
    sqlite_busy_timeout: int = Field(
        default=5000,
        ge=0,
        description="Milliseconds a blocked SQLite writer waits for the lock. Ignored on PostgreSQL.",
    )

    @model_validator(mode="after")
    def _check_pool_bounds(self) -> DatabaseSettings:
        if self.pool_min_size > self.pool_max_size:
            raise ValueError(f"pool_min_size ({self.pool_min_size}) cannot exceed pool_max_size ({self.pool_max_size})")
        return self


class ClientSettings(_Section):
    """
    Fallbacks for remote :class:`chesssnake.Game` clients.

    These keys exist here so their environment-variable names are derived from the
    same schema as everything else and show up in ``chesssnake config show``. The
    client itself reads only the environment, never the config file -- a library
    that read ``./chesssnake.toml`` out of the caller's working directory would be
    surprising, and importing this module would put pydantic on the local-game path.
    """

    api_url: str | None = Field(
        default=None,
        description="Base URL of the api-endpoint to connect to.",
        json_schema_extra={"env_only": True},
    )
    api_key: str | None = _secret(None, "API key sent as X-API-Key when talking to the api-endpoint.", env_only=True)


class Settings(BaseModel):
    """The fully resolved configuration."""

    model_config = ConfigDict(extra="forbid")

    # pydantic deep-copies model defaults per instance, so these are not shared.
    api: ApiSettings = ApiSettings()
    database: DatabaseSettings = DatabaseSettings()
    client: ClientSettings = ClientSettings()

    @model_validator(mode="after")
    def _check_auth_is_usable(self) -> Settings:
        """Fail loudly rather than coming up unauthenticated by accident."""
        if self.api.require_auth and not self.api.api_key:
            raise ValueError(
                "api.require_auth is enabled but no api.api_key is set, so no request could ever "
                "authenticate. Set a key with --api-key, "
                f"{env_name('api', 'api_key')}, or `api_key` under [api] in the config file."
            )
        return self

    def advisories(self) -> list[str]:
        """
        Return non-fatal warnings about the effective configuration.

        These are printed by ``chesssnake config show`` and logged by the server at
        startup. They are deliberately not Python warnings, which are easy to
        filter out of exactly the production logs where they matter most.
        """
        notes = []
        if self.api.api_key and not self.api.require_auth:
            notes.append(
                f"{env_name('api', 'api_key')} is set but api.require_auth is false, so the key is "
                "ignored and every /v1 route accepts unauthenticated requests. Set api.require_auth "
                "to enforce it."
            )
        return notes


# --- Schema introspection --------------------------------------------------


def section_names() -> tuple[str, ...]:
    """Return the configured section names, in declaration order."""
    return tuple(Settings.model_fields)


def _section_model(section: str) -> type[_Section]:
    return Settings.model_fields[section].annotation  # type: ignore[return-value]


def iter_schema() -> Iterator[tuple[str, str, Any]]:
    """Yield ``(section, key, field_info)`` for every declared setting."""
    for section in section_names():
        for key, field in _section_model(section).model_fields.items():
            yield section, key, field


def env_name(section: str, key: str) -> str:
    """
    Return the environment variable that sets ``key`` in ``section``.

    ``env_name("api", "port")`` is ``"CHESSSNAKE__API__PORT"``. Key names keep
    their internal single underscores, so ``pool_min_size`` becomes
    ``CHESSSNAKE__DATABASE__POOL_MIN_SIZE`` and round-trips unambiguously.

    :param section: Section name, e.g. ``"api"``.
    :param key: Field name within the section, e.g. ``"port"``.
    :return: The derived environment variable name.
    """
    return ENV_SEPARATOR.join((ENV_PREFIX, section.upper(), key.upper()))


def is_secret(section: str, key: str) -> bool:
    """Return whether a setting holds a credential and must be redacted."""
    extra = _section_model(section).model_fields[key].json_schema_extra
    return bool(isinstance(extra, dict) and extra.get("secret"))


def describe(section: str, key: str) -> str:
    """Return the help text declared for a setting."""
    return _section_model(section).model_fields[key].description or ""


# --- Layers ----------------------------------------------------------------


@dataclass(frozen=True)
class Override:
    """One value contributed by one layer, with enough detail to explain itself."""

    section: str
    key: str
    value: Any
    layer: str
    origin: str = ""

    def describe_source(self) -> str:
        return f"{self.layer}: {self.origin}" if self.origin else self.layer


def find_config_file(
    explicit: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> Path | None:
    """
    Locate the TOML config file, or return ``None`` when there isn't one.

    An explicit path (from ``--config``) wins, then ``CHESSSNAKE_CONFIG``; both are
    errors if they name a missing file, since the user asked for that file
    specifically. Otherwise the first existing of ``./chesssnake.toml``,
    ``$CHESSSNAKE_HOME/chesssnake.toml``, and
    ``~/.config/chesssnake/chesssnake.toml`` is used. Finding nothing is fine --
    the defaults stand on their own.

    :param explicit: Path given on the command line, if any.
    :param environ: Environment to read (defaults to :data:`os.environ`).
    :param cwd: Directory to treat as the working directory.
    :raises ConfigError: If an explicitly requested file does not exist.
    """
    environ = os.environ if environ is None else environ
    base = Path(cwd) if cwd is not None else Path.cwd()

    for candidate, source in ((explicit, "--config"), (environ.get(CONFIG_PATH_ENV), CONFIG_PATH_ENV)):
        if candidate:
            path = Path(candidate).expanduser()
            if not path.is_file():
                raise ConfigError(f"Config file not found: {path} (requested by {source})")
            return path

    search = [base / CONFIG_FILENAME]
    if home := environ.get(HOME_ENV):
        search.append(Path(home).expanduser() / CONFIG_FILENAME)
    # Only when the environment actually defines HOME, so an injected environment
    # (as the tests use) cannot reach the developer's real user config.
    if user_home := environ.get("HOME"):
        search.append(Path(user_home) / ".config" / "chesssnake" / CONFIG_FILENAME)

    return next((path for path in search if path.is_file()), None)


def default_config_path(
    environ: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> Path:
    """
    Return where ``chesssnake config init`` writes a new config file.

    ``$CHESSSNAKE_HOME`` when it is set, otherwise the working directory. Both
    are locations :func:`find_config_file` searches, so the written file is
    picked up without any further configuration.

    :param environ: Environment to read (defaults to :data:`os.environ`).
    :param cwd: Directory to treat as the working directory.
    :return: The path a new config file should be written to.
    """
    environ = os.environ if environ is None else environ
    if home := environ.get(HOME_ENV):
        base = Path(home).expanduser()
    else:
        base = Path(cwd) if cwd is not None else Path.cwd()
    return base / CONFIG_FILENAME


def default_config_text() -> str:
    """Return the packaged, commented default configuration file as text."""
    return Path(asset_path(CONFIG_FILENAME)).read_text(encoding="utf-8")


def write_default_config(
    *,
    force: bool = False,
    environ: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> Path:
    """
    Write the packaged default config to :func:`default_config_path`.

    :param force: Overwrite an existing file instead of refusing.
    :param environ: Environment to read (defaults to :data:`os.environ`).
    :param cwd: Directory to treat as the working directory.
    :return: The path written.
    :raises ConfigError: If the file exists and ``force`` is false, or it cannot
        be written.
    """
    path = default_config_path(environ, cwd)
    if path.exists() and not force:
        raise ConfigError(f"{path} already exists. Pass --force to overwrite it.")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(default_config_text(), encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Could not write {path}: {e}") from e
    return path


def _file_overrides(path: Path | None) -> list[Override]:
    """Read the config file into overrides, or return nothing when there is no file."""
    if path is None:
        return []
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Could not parse config file {path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"Could not read config file {path}: {e}") from e

    env_only = {section for section, key, _ in iter_schema() if _marker(section, key, "env_only")}

    overrides = []
    for section, items in data.items():
        if not isinstance(items, dict):
            raise ConfigError(
                f"Invalid config file {path}: top-level key '{section}' must be a table "
                f"(one of: {', '.join(section_names())})"
            )
        if section in env_only:
            # Reporting a file value for a key nothing reads would make `config
            # show` lie, which is worse than not supporting the key at all.
            example = next(iter(items), next(k for s, k, _ in iter_schema() if s == section))
            raise ConfigError(
                f"Invalid config file {path}: [{section}] cannot be set in a config file. The client "
                f"library reads only the environment (e.g. {env_name(section, example)}), "
                "so a value here would be silently ignored."
            )
        for key, value in items.items():
            overrides.append(Override(section, key, value, "file", str(path)))
    return overrides


def _env_overrides(environ: Mapping[str, str] | None = None) -> list[Override]:
    """
    Read ``CHESSSNAKE__SECTION__KEY`` variables into overrides.

    Unknown names are warned about rather than rejected: the environment is a
    shared namespace, so a stray variable is not necessarily this program's bug,
    but a typo'd one would otherwise vanish without a trace.
    """
    environ = os.environ if environ is None else environ
    known = {(section, key) for section, key, _ in iter_schema()}
    prefix = ENV_PREFIX + ENV_SEPARATOR

    overrides = []
    for name in sorted(environ):
        if not name.startswith(prefix):
            continue
        parts = name.split(ENV_SEPARATOR)
        if len(parts) != 3 or not parts[2]:
            warnings.warn(f"Ignoring malformed setting variable {name!r}; expected {prefix}SECTION__KEY.", stacklevel=2)
            continue
        section, key = parts[1].lower(), parts[2].lower()
        if (section, key) not in known:
            warnings.warn(f"Ignoring unknown setting variable {name!r}.", stacklevel=2)
            continue
        overrides.append(Override(section, key, environ[name], "env", name))
    return overrides


# --- Resolution ------------------------------------------------------------


class ResolvedSettings(Settings):
    """:class:`Settings` plus a record of where each value came from."""

    model_config = ConfigDict(extra="forbid")

    def source(self, section: str, key: str) -> str:
        """Return a human-readable description of the layer that set a value."""
        override = self._sources.get((section, key))
        return override.describe_source() if override else "default"

    # Kept off the model proper so `extra="forbid"` still guards real settings.
    _sources: dict[tuple[str, str], Override] = {}


def resolve(
    overrides: Sequence[Override] = (),
    *,
    config_path: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> ResolvedSettings:
    """
    Merge all four configuration layers and validate the result.

    Later layers win: defaults, then the config file, then the environment, then
    the ``overrides`` passed in (which is how command-line flags take precedence).

    :param overrides: Command-line overrides, highest precedence.
    :param config_path: Explicit config file path (from ``--config``).
    :param environ: Environment to read (defaults to :data:`os.environ`).
    :param cwd: Directory to treat as the working directory when searching.
    :return: The validated settings, carrying per-key provenance.
    :raises ConfigError: If a file is missing/malformed or the result is invalid.
    """
    path = find_config_file(config_path, environ, cwd)
    layers = [*_file_overrides(path), *_env_overrides(environ), *overrides]

    values: dict[str, dict[str, Any]] = {}
    sources: dict[tuple[str, str], Override] = {}
    for override in layers:
        values.setdefault(override.section, {})[override.key] = override.value
        sources[(override.section, override.key)] = override

    try:
        settings = ResolvedSettings.model_validate(values)
    except ValidationError as e:
        raise ConfigError(_explain(e, sources, path)) from e

    settings._sources = sources
    return settings


def _explain(error: ValidationError, sources: dict[tuple[str, str], Override], path: Path | None) -> str:
    """Turn a pydantic error into a message naming the layer that supplied the bad value."""
    lines = ["Invalid configuration:"]
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"])
        origin = ""
        if len(detail["loc"]) == 2:
            override = sources.get((str(detail["loc"][0]), str(detail["loc"][1])))
            if override:
                origin = f" (set by {override.describe_source()})"
        # A model-level validator has an empty location; its message is already
        # self-describing, so don't prefix it with a placeholder.
        lines.append(f"  {location}: {detail['msg']}{origin}" if location else f"  {detail['msg']}")
    if path is not None:
        lines.append(f"Config file: {path}")
    return "\n".join(lines)


def format_settings(settings: ResolvedSettings, *, show_secrets: bool = False, as_json: bool = False) -> str:
    """
    Render the effective configuration with the source of every value.

    :param settings: Resolved settings to render.
    :param show_secrets: Print credentials verbatim instead of redacting them.
    :param as_json: Emit machine-readable JSON instead of an aligned table.
    :return: The formatted, printable report.
    """
    rows = [
        (
            section,
            key,
            _render(section, key, getattr(getattr(settings, section), key), show_secrets),
            settings.source(section, key),
        )
        for section, key, _ in iter_schema()
    ]

    if as_json:
        payload: dict[str, Any] = {"settings": {}, "advisories": settings.advisories()}
        for section, key, shown, source in rows:
            payload["settings"].setdefault(section, {})[key] = {"value": shown, "source": source}
        return json.dumps(payload, indent=2)

    key_width = max(len(key) for _, key, _, _ in rows)
    value_width = max(len(shown) for _, _, shown, _ in rows)

    out = []
    for section in section_names():
        out.append(f"[{section}]")
        out.extend(
            f"  {key:<{key_width}}  {shown:<{value_width}}  ({source})"
            for s, key, shown, source in rows
            if s == section
        )
        out.append("")
    for note in settings.advisories():
        out.append(f"warning: {note}")
    return "\n".join(out).rstrip()


def _render(section: str, key: str, value: Any, show_secrets: bool) -> str:
    """Format one value for display, redacting credentials unless asked not to."""
    if value is None:
        return "<unset>"
    if show_secrets:
        return str(value)
    if is_secret(section, key):
        return REDACTED
    if _marker(section, key, "dsn"):
        # Keep the host and database visible; only the password is sensitive.
        return redact_dsn(str(value))
    return str(value)
