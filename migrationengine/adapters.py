"""Provider discovery adapters.

Produce a provider-neutral canonical spec from a source provider. Fly and
Supabase attempt live discovery when credentials are configured; all providers
fall back to a deterministic stub snapshot so the planner can operate offline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests
from django.conf import settings

SUPPORTED_PROVIDERS = ["render", "railway", "fly", "kong", "terraform", "supabase"]


def _stub_snapshot(provider: str, app_identifier: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "appIdentifier": app_identifier,
        "live": False,
        "raw": {"live": False, "note": "stub snapshot (no credentials configured)"},
    }


def _fly_live_snapshot(app_identifier: str) -> dict[str, Any] | None:
    if not settings.FLY_API_TOKEN:
        return None
    base = settings.FLY_API_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.FLY_API_TOKEN}"}
    try:
        response = requests.get(f"{base}/v1/apps/{app_identifier}/machines", headers=headers, timeout=15)
        if response.status_code != 200:
            return None
        machines = response.json()
    except (requests.RequestException, ValueError):
        return None
    regions = sorted({m.get("region") for m in machines if isinstance(m, dict) and m.get("region")})
    return {
        "provider": "fly",
        "appIdentifier": app_identifier,
        "live": True,
        "raw": {"live": True, "machineCount": len(machines), "regions": regions},
    }


def _supabase_live_snapshot(app_identifier: str) -> dict[str, Any] | None:
    if not settings.SUPABASE_ACCESS_TOKEN:
        return None
    base = settings.SUPABASE_API_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.SUPABASE_ACCESS_TOKEN}"}
    try:
        response = requests.get(f"{base}/v1/projects/{app_identifier}", headers=headers, timeout=15)
        if response.status_code != 200:
            return None
        project = response.json()
    except (requests.RequestException, ValueError):
        return None
    return {
        "provider": "supabase",
        "appIdentifier": app_identifier,
        "live": True,
        "raw": {"live": True, "region": project.get("region"), "dbVersion": project.get("database", {}).get("version")},
    }


def discover(provider: str, app_identifier: str) -> dict[str, Any]:
    if provider == "fly":
        snapshot = _fly_live_snapshot(app_identifier) or _stub_snapshot(provider, app_identifier)
    elif provider == "supabase":
        snapshot = _supabase_live_snapshot(app_identifier) or _stub_snapshot(provider, app_identifier)
    else:
        snapshot = _stub_snapshot(provider, app_identifier)

    spec = _to_canonical(snapshot)
    return {"snapshot": snapshot, "spec": spec}


def _to_canonical(snapshot: dict[str, Any]) -> dict[str, Any]:
    provider = snapshot["provider"]
    app_identifier = snapshot["appIdentifier"]
    raw = snapshot.get("raw", {})

    region = raw.get("region") or (raw.get("regions") or ["us-east-1"])[0] if raw.get("regions") else "us-east-1"
    runtime = "node"
    databases: list[dict[str, Any]] = []
    if provider == "supabase":
        runtime = "docker"
        databases = [{"name": "primary", "engine": "postgres", "version": raw.get("dbVersion") or "16"}]

    return {
        "appName": app_identifier,
        "sourceProvider": provider,
        "targetProvider": provider,
        "services": [
            {
                "name": "web",
                "runtime": runtime,
                "startCommand": "node server.js",
                "region": region,
                "replicas": 1,
                "environment": {"NODE_ENV": "production"},
                "secrets": [],
            }
        ],
        "domains": [{"host": f"{app_identifier}.example.com", "tlsRequired": True}],
        "databases": databases,
        "metadata": {
            "requestedBy": "discovery",
            "requestedAt": datetime.now(timezone.utc).isoformat(),
            "environment": "stage",
        },
    }
