"""Server-side vault for secrets fetched during provider discovery.

Plaintext secret values are sealed immediately after a live discovery/review call
and are never returned to API clients. Downstream plan/deploy stages hydrate from
this store using a discoveryId reference.
"""
from __future__ import annotations

from typing import Any

from core.vault import SealedSecret, decrypt_secret, encrypt_secret

_DISCOVERY_VAULT: dict[str, dict[str, dict[str, str]]] = {}


def store_discovery_secrets(discovery_id: str, service_name: str, secrets: dict[str, str]) -> list[str]:
    sealed: dict[str, dict[str, str]] = {}
    for key, value in secrets.items():
        sealed[f"{service_name}::{key}"] = encrypt_secret(value).to_dict()
    _DISCOVERY_VAULT[discovery_id] = sealed
    return sorted(secrets.keys())


def get_discovery_sealed(discovery_id: str) -> dict[str, dict[str, str]]:
    return dict(_DISCOVERY_VAULT.get(discovery_id, {}))


def hydrate_service_secrets(discovery_id: str, service_name: str = "web") -> dict[str, str]:
    sealed = _DISCOVERY_VAULT.get(discovery_id, {})
    prefix = f"{service_name}::"
    hydrated: dict[str, str] = {}
    for ref, payload in sealed.items():
        if not ref.startswith(prefix):
            continue
        key = ref[len(prefix) :]
        hydrated[key] = decrypt_secret(SealedSecret.from_dict(payload))
    return hydrated


def clear_discovery(discovery_id: str) -> None:
    _DISCOVERY_VAULT.pop(discovery_id, None)
