"""Recursively redacts sensitive values before logging or returning responses."""
from __future__ import annotations

from typing import Any

SENSITIVE_KEYS = ("secret", "token", "password", "apikey", "authorization", "privatekey")
REDACTED = "[REDACTED]"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(needle in lowered for needle in SENSITIVE_KEYS)


def redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, child in value.items():
            if _is_sensitive(str(key)) and not isinstance(child, (dict, list)):
                result[key] = REDACTED
            else:
                result[key] = redact_sensitive_values(child)
        return result
    return value
