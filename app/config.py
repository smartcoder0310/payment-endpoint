"""Application configuration, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """The application was started without the configuration it needs."""


@dataclass(frozen=True)
class Config:
    database_url: str
    sql_echo: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ConfigError(
                "DATABASE_URL is not set. See .env.example for the expected value."
            )
        return cls(
            database_url=database_url,
            sql_echo=_env_flag("SQL_ECHO"),
        )


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
