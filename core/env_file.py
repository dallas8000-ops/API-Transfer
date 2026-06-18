"""Safe merge helpers for the project-root `.env` file (local dev only)."""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Any

from django.conf import settings

_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def dotenv_path() -> Path:
    return Path(settings.BASE_DIR) / ".env"


def can_auto_apply_dotenv() -> bool:
    """Allow writing `.env` from setup actions on local dev, not on hosted Railway."""
    return not getattr(settings, "ON_RAILWAY", False)


def _quote_env_value(value: str) -> str:
    if not value:
        return '""'
    if any(ch in value for ch in " #\"'\n\t"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def merge_dotenv_file(path: Path, updates: dict[str, str]) -> list[str]:
    """Upsert keys into `.env`, preserving unrelated lines and comments."""
    remaining = {key: str(value) for key, value in updates.items() if key and str(value).strip()}
    if not remaining:
        return []

    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            output.append(f"{key}={_quote_env_value(remaining[key])}")
            seen.add(key)
        else:
            output.append(line)

    for key in sorted(remaining):
        if key in seen:
            continue
        output.append(f"{key}={_quote_env_value(remaining[key])}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    return sorted(seen | set(remaining))


def reload_runtime_env(updates: dict[str, str]) -> None:
    """Reload merged values into os.environ and Django settings without restart."""
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path(), override=True)
    except ImportError:
        pass

    for key, value in updates.items():
        if not _ENV_KEY_PATTERN.match(key):
            continue
        os.environ[key] = str(value)
        if key == "VAULT_MASTER_KEY_BASE64":
            decoded = base64.b64decode(str(value))
            if len(decoded) == 32:
                setattr(settings, "VAULT_MASTER_KEY", decoded)
        elif hasattr(settings, key):
            setattr(settings, key, str(value))


def apply_env_updates(updates: dict[str, str]) -> dict[str, Any]:
    """Merge into `.env` and hot-reload this Django process."""
    if not can_auto_apply_dotenv():
        return {"applied": False, "reason": "Auto-apply is disabled on hosted Railway — set variables in the Railway dashboard."}

    path = dotenv_path()
    applied_keys = merge_dotenv_file(path, updates)
    reload_runtime_env({key: updates[key] for key in applied_keys})
    return {"applied": True, "path": str(path), "keys": applied_keys}
