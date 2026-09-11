"""Configuration loaded from openHop's plugin data directory."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when plugin configuration is invalid."""


@dataclass(frozen=True)
class Settings:
    meshcore_host: str
    meshcore_port: int
    database_path: Path
    max_reply_bytes: int
    max_command_bytes: int
    duplicate_ttl_seconds: int
    frotz_path: str
    story_path: Path | None
    random_seed: int
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        data_dir, config = _load_plugin_config()
        data_dir.mkdir(parents=True, exist_ok=True)

        settings = cls(
            meshcore_host=_get_str("MESHCORE_HOST", "127.0.0.1", config),
            meshcore_port=_get_int("MESHCORE_PORT", 5002, config),
            database_path=data_dir / "sessions.sqlite3",
            max_reply_bytes=_get_int("MAX_REPLY_BYTES", 145, config),
            max_command_bytes=_get_int("MAX_COMMAND_BYTES", 160, config),
            duplicate_ttl_seconds=_get_int("DUPLICATE_TTL_SECONDS", 600, config),
            frotz_path=_get_str("FROTZ_PATH", "/usr/games/dfrotz", config),
            story_path=_get_optional_path("STORY_PATH", config),
            random_seed=_get_int("RANDOM_SEED", 117, config),
            log_level=_get_str("LOG_LEVEL", "INFO", config).upper(),
        )
        _validate(settings)
        return settings


def _load_plugin_config() -> tuple[Path, dict[str, Any]]:
    raw_data_dir = os.getenv("OPENHOP_PLUGIN_DATA", "").strip()
    data_dir = Path(raw_data_dir).expanduser() if raw_data_dir else Path("./data")
    config_path = data_dir / "config.json"
    if not config_path.exists():
        return data_dir, {}
    try:
        value = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Unable to read config.json: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError("config.json must contain a JSON object")
    return data_dir, value


def _raw(name: str, default: Any, config: dict[str, Any]) -> Any:
    env_value = os.getenv(name)
    if env_value is not None and env_value.strip() != "":
        return env_value
    return config.get(name.lower(), default)


def _get_str(name: str, default: str, config: dict[str, Any]) -> str:
    value = _raw(name, default, config)
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be a string")
    return value.strip()


def _get_int(name: str, default: int, config: dict[str, Any]) -> int:
    value = _raw(name, default, config)
    if isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _get_optional_path(name: str, config: dict[str, Any]) -> Path | None:
    value = _raw(name, "", config)
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be a string")
    return Path(value).expanduser() if value.strip() else None


def _validate(settings: Settings) -> None:
    if not settings.meshcore_host:
        raise ConfigError("MESHCORE_HOST must not be empty")
    if not 1 <= settings.meshcore_port <= 65535:
        raise ConfigError("MESHCORE_PORT must be between 1 and 65535")
    if not 40 <= settings.max_reply_bytes <= 180:
        raise ConfigError("MAX_REPLY_BYTES must be between 40 and 180")
    if not 1 <= settings.max_command_bytes <= 1024:
        raise ConfigError("MAX_COMMAND_BYTES must be between 1 and 1024")
    if settings.duplicate_ttl_seconds < 60:
        raise ConfigError("DUPLICATE_TTL_SECONDS must be at least 60")
    if not settings.frotz_path:
        raise ConfigError("FROTZ_PATH must not be empty")
    if not 1 <= settings.random_seed <= 32767:
        raise ConfigError("RANDOM_SEED must be between 1 and 32767")
