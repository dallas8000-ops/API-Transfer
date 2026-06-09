"""Classify environment variable keys as public config versus secrets."""
from __future__ import annotations

import re

SECRET_KEY_PATTERN = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|private[_-]?key|access[_-]?key|credential|auth|database|dsn|connection)",
    re.IGNORECASE,
)


def is_sensitive_env_key(key: str) -> bool:
    return bool(SECRET_KEY_PATTERN.search(key))


def partition_env_vars(variables: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    environment: dict[str, str] = {}
    secrets: dict[str, str] = {}
    for key, value in variables.items():
        if is_sensitive_env_key(key):
            secrets[key] = value
        else:
            environment[key] = value
    return environment, secrets
