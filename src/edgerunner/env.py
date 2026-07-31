from __future__ import annotations

import os


ENV_PREFIX = "env:"


def resolve_env_reference(value: str) -> str:
    if not value.startswith(ENV_PREFIX):
        return value

    env_name = value[len(ENV_PREFIX) :]
    try:
        return os.environ[env_name]
    except KeyError as exc:
        raise RuntimeError(f"Missing required environment variable: {env_name}") from exc
