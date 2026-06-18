"""Provider discovery adapters.

Produce a provider-neutral canonical spec from a source provider. Render, Railway,
Fly and Supabase attempt live discovery when credentials are configured; all
providers fall back to a deterministic stub snapshot so the planner can operate
offline. Secret values fetched from providers are sealed server-side and never
returned in API responses.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

_RAILWAY_SERVICE_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

import requests
from django.conf import settings

from core.secret_classification import partition_env_vars
from migrationengine.discovery_vault import store_discovery_secrets

SUPPORTED_PROVIDERS = ["render", "railway", "fly", "kong", "terraform", "supabase", "orena"]
ACCOUNT_REVIEW_PROVIDERS = ["render", "railway", "orena"]


def _stub_snapshot(provider: str, app_identifier: str) -> dict[str, Any]:
    return {
        "provider": provider,
        "appIdentifier": app_identifier,
        "live": False,
        "raw": {"live": False, "note": "stub snapshot (no credentials configured)"},
    }


def _public_secret_entries(secret_keys: list[str]) -> list[dict[str, Any]]:
    return [{"key": key, "sealed": True} for key in secret_keys]


def _attach_env_metadata(snapshot: dict[str, Any], environment: dict[str, str], secret_keys: list[str]) -> None:
    raw = snapshot.setdefault("raw", {})
    raw["environment"] = environment
    raw["environmentKeys"] = sorted(environment.keys())
    raw["secretKeys"] = secret_keys


def _fetch_render_env(service_id: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    from migrationengine.providers import ProviderApiError, get_render_env_vars

    try:
        variables = get_render_env_vars(service_id)
    except ProviderApiError:
        return {}, {}, []
    environment, secrets = partition_env_vars(variables)
    return environment, secrets, sorted(secrets.keys())


def _fetch_railway_env(service_id: str, project_id: str | None = None, environment_id: str | None = None) -> tuple[dict[str, str], dict[str, str], list[str]]:
    from migrationengine.providers import ProviderApiError, _railway_environment_id, get_railway_env_vars

    project_id = project_id or settings.RAILWAY_PROJECT_ID
    if not project_id:
        return {}, {}, []
    try:
        environment_id = environment_id or _railway_environment_id(project_id)
        variables = get_railway_env_vars(project_id, service_id, environment_id)
    except ProviderApiError:
        return {}, {}, []
    environment, secrets = partition_env_vars(variables)
    return environment, secrets, sorted(secrets.keys())


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


def _render_live_snapshot(app_identifier: str) -> dict[str, Any] | None:
    if not settings.RENDER_API_TOKEN:
        return None
    base = settings.RENDER_API_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.RENDER_API_TOKEN}"}
    try:
        response = requests.get(f"{base}/v1/services/{app_identifier}", headers=headers, timeout=15)
        if response.status_code != 200:
            return None
        service = response.json()
    except (requests.RequestException, ValueError):
        return None
    details = service.get("serviceDetails", {}) if isinstance(service, dict) else {}
    snapshot = {
        "provider": "render",
        "appIdentifier": app_identifier,
        "live": True,
        "raw": {
            "live": True,
            "name": service.get("name"),
            "branch": service.get("branch"),
            "repo": service.get("repo"),
            "repoUrl": service.get("repoUrl"),
            "sourceRepo": service.get("sourceRepo"),
            "gitRepo": service.get("gitRepo"),
            "region": details.get("region"),
            "runtime": details.get("runtime"),
            "buildCommand": details.get("buildCommand"),
            "startCommand": details.get("startCommand"),
            "rootDirectory": details.get("rootDir") or details.get("rootDirectory") or service.get("rootDirectory"),
            "url": details.get("url"),
        },
    }
    environment, secrets, secret_keys = _fetch_render_env(app_identifier)
    _attach_env_metadata(snapshot, environment, secret_keys)
    snapshot["raw"]["_secrets"] = secrets
    return snapshot


def _railway_live_snapshot(app_identifier: str) -> dict[str, Any] | None:
    if not settings.RAILWAY_API_TOKEN:
        return None
    from migrationengine.providers import ProviderApiError, _railway_environment_id, _railway_gql, get_railway_service_instance

    project_id = settings.RAILWAY_PROJECT_ID
    if not project_id:
        return None
    try:
        environment_id = _railway_environment_id(project_id)
        data = _railway_gql(
            """
            query($id: String!) {
              service(id: $id) {
                id
                name
                repoTriggers { edges { node { branch repository } } }
              }
            }
            """,
            {"id": app_identifier},
        )
    except ProviderApiError:
        return None
    service = data.get("service") or {}
    trigger = ((service.get("repoTriggers") or {}).get("edges") or [{}])[0].get("node", {})
    repo = str(trigger.get("repository") or trigger.get("repo") or "").strip()
    instance = get_railway_service_instance(app_identifier, environment_id)
    snapshot = {
        "provider": "railway",
        "appIdentifier": app_identifier,
        "live": True,
        "raw": {
            "live": True,
            "name": service.get("name"),
            "branch": trigger.get("branch"),
            "repo": repo or trigger.get("repo"),
            "projectId": project_id,
            "environmentId": environment_id,
            **instance,
        },
    }
    environment, secrets, secret_keys = _fetch_railway_env(app_identifier, project_id, environment_id)
    _attach_env_metadata(snapshot, environment, secret_keys)
    snapshot["raw"]["_secrets"] = secrets
    return snapshot


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


def review_account(provider: str) -> dict[str, Any]:
    if provider not in ACCOUNT_REVIEW_PROVIDERS:
        return {"provider": provider, "live": False, "apps": [], "message": f"Account review is not supported for {provider}."}

    if provider == "render":
        return _review_render_account()
    if provider == "orena":
        return _review_orena_account()
    return _review_railway_account()


def _review_render_account() -> dict[str, Any]:
    if not settings.RENDER_API_TOKEN:
        return {"provider": "render", "live": False, "apps": [], "message": "Configure RENDER_API_TOKEN to review the account."}
    from migrationengine.providers import ProviderApiError, list_render_services

    try:
        services = list_render_services()
    except ProviderApiError as exc:
        return {"provider": "render", "live": False, "apps": [], "message": str(exc)}

    apps: list[dict[str, Any]] = []
    for service in services:
        environment, _, secret_keys = _fetch_render_env(service["id"])
        apps.append(
            {
                "id": service["id"],
                "name": service["name"],
                "settings": {
                    "type": service.get("type"),
                    "region": service.get("region"),
                    "runtime": service.get("runtime"),
                    "branch": service.get("branch"),
                    "repo": service.get("repo"),
                    "buildCommand": service.get("buildCommand"),
                    "startCommand": service.get("startCommand"),
                    "url": service.get("url"),
                },
                "environmentKeys": sorted(environment.keys()),
                "secretKeys": secret_keys,
            }
        )
    return {"provider": "render", "live": True, "apps": apps, "message": f"Found {len(apps)} Render service(s). Secret values are never returned."}


def _review_railway_account() -> dict[str, Any]:
    if not settings.RAILWAY_API_TOKEN or not settings.RAILWAY_PROJECT_ID:
        return {
            "provider": "railway",
            "live": False,
            "apps": [],
            "message": "Configure RAILWAY_API_TOKEN and RAILWAY_PROJECT_ID to review the account.",
        }
    from migrationengine.providers import ProviderApiError, list_railway_services

    try:
        services = list_railway_services()
    except ProviderApiError as exc:
        return {"provider": "railway", "live": False, "apps": [], "message": str(exc)}

    apps: list[dict[str, Any]] = []
    from migrationengine.providers import get_railway_service_source

    for service in services:
        environment, _, secret_keys = _fetch_railway_env(
            service["id"], service.get("projectId"), service.get("environmentId")
        )
        source = get_railway_service_source(service["id"])
        apps.append(
            {
                "id": service["id"],
                "name": service["name"],
                "settings": {
                    "branch": source.get("branch") or service.get("branch"),
                    "repo": source.get("repo") or service.get("repo"),
                    "repoUrl": source.get("repoUrl") or service.get("repoUrl"),
                    "sourceRepo": source.get("sourceRepo") or service.get("sourceRepo"),
                    "gitRepo": source.get("gitRepo") or service.get("gitRepo"),
                    "buildCommand": service.get("buildCommand"),
                    "startCommand": service.get("startCommand"),
                    "rootDirectory": service.get("rootDirectory"),
                    "projectId": service.get("projectId"),
                    "environmentId": service.get("environmentId"),
                },
                "environmentKeys": sorted(environment.keys()),
                "secretKeys": secret_keys,
            }
        )
    return {"provider": "railway", "live": True, "apps": apps, "message": f"Found {len(apps)} Railway service(s). Secret values are never returned."}


def _fetch_orena_env(app_id: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    from migrationengine.providers import ProviderApiError, get_orena_env_vars

    try:
        variables = get_orena_env_vars(app_id)
    except ProviderApiError:
        return {}, {}, []
    environment, secrets = partition_env_vars(variables)
    return environment, secrets, sorted(secrets.keys())


def _review_orena_account() -> dict[str, Any]:
    if not settings.ORENA_API_TOKEN:
        return {
            "provider": "orena",
            "live": False,
            "apps": [],
            "message": "Configure ORENA_API_TOKEN to review the account.",
        }
    from migrationengine.providers import ProviderApiError, list_orena_apps

    try:
        services = list_orena_apps()
    except ProviderApiError as exc:
        return {"provider": "orena", "live": False, "apps": [], "message": str(exc)}

    apps: list[dict[str, Any]] = []
    for service in services:
        environment, _, secret_keys = _fetch_orena_env(service["id"])
        apps.append(
            {
                "id": service["id"],
                "name": service["name"],
                "settings": {
                    "region": service.get("region") or settings.ORENA_DEFAULT_REGION,
                    "branch": service.get("branch"),
                    "repo": service.get("repo"),
                    "repoUrl": service.get("repoUrl"),
                    "buildCommand": service.get("buildCommand"),
                    "startCommand": service.get("startCommand"),
                    "runtime": service.get("runtime"),
                    "url": service.get("url"),
                },
                "environmentKeys": sorted(environment.keys()),
                "secretKeys": secret_keys,
            }
        )
    return {
        "provider": "orena",
        "live": True,
        "apps": apps,
        "message": f"Found {len(apps)} Orena app(s) in {settings.ORENA_DEFAULT_REGION}. Secret values are never returned.",
    }


def _orena_live_snapshot(app_identifier: str) -> dict[str, Any] | None:
    if not settings.ORENA_API_TOKEN:
        return None
    from migrationengine.providers import ProviderApiError, get_orena_app

    try:
        app = get_orena_app(app_identifier)
    except ProviderApiError:
        return None
    if not app:
        return None
    environment, _, secret_keys = _fetch_orena_env(app.get("id") or app_identifier)
    return {
        "provider": "orena",
        "appIdentifier": app_identifier,
        "live": True,
        "raw": {
            "live": True,
            "name": app.get("name"),
            "branch": app.get("branch"),
            "repo": app.get("repo"),
            "repoUrl": app.get("repoUrl"),
            "region": app.get("region") or settings.ORENA_DEFAULT_REGION,
            "runtime": app.get("runtime"),
            "buildCommand": app.get("buildCommand"),
            "startCommand": app.get("startCommand"),
            "environment": environment,
            "secretKeys": secret_keys,
        },
    }


def _resolve_app_identifier(provider: str, app_identifier: str) -> str:
    identifier = (app_identifier or "").strip()
    if provider == "railway" and identifier and not _RAILWAY_SERVICE_ID_RE.match(identifier):
        if settings.RAILWAY_API_TOKEN and settings.RAILWAY_PROJECT_ID:
            from migrationengine.providers import get_railway_service_id_by_name

            resolved = get_railway_service_id_by_name(settings.RAILWAY_PROJECT_ID, identifier)
            if resolved:
                return resolved
    return identifier


def discover(provider: str, app_identifier: str) -> dict[str, Any]:
    app_identifier = _resolve_app_identifier(provider, app_identifier)
    if provider == "render":
        snapshot = _render_live_snapshot(app_identifier) or _stub_snapshot(provider, app_identifier)
    elif provider == "railway":
        snapshot = _railway_live_snapshot(app_identifier) or _stub_snapshot(provider, app_identifier)
    elif provider == "fly":
        snapshot = _fly_live_snapshot(app_identifier) or _stub_snapshot(provider, app_identifier)
    elif provider == "supabase":
        snapshot = _supabase_live_snapshot(app_identifier) or _stub_snapshot(provider, app_identifier)
    elif provider == "orena":
        snapshot = _orena_live_snapshot(app_identifier) or _stub_snapshot(provider, app_identifier)
    else:
        snapshot = _stub_snapshot(provider, app_identifier)

    discovery_id = str(uuid.uuid4())
    raw = snapshot.get("raw", {})
    secrets = raw.pop("_secrets", {})
    secret_keys = store_discovery_secrets(discovery_id, "web", secrets) if secrets else list(raw.get("secretKeys", []))

    spec = _to_canonical(snapshot, discovery_id=discovery_id, secret_keys=secret_keys)
    public_snapshot = _public_snapshot(snapshot)
    return {
        "discoveryId": discovery_id,
        "snapshot": public_snapshot,
        "spec": spec,
        "secretKeys": secret_keys,
    }


def discover_stub(provider: str, app_identifier: str) -> dict[str, Any]:
    """Deterministic discovery for demo links — never calls live provider APIs."""
    snapshot = _stub_snapshot(provider, app_identifier or "demo-app")
    discovery_id = str(uuid.uuid4())
    raw = snapshot.get("raw", {})
    secrets = raw.pop("_secrets", {})
    secret_keys = store_discovery_secrets(discovery_id, "web", secrets) if secrets else list(raw.get("secretKeys", []))
    spec = _to_canonical(snapshot, discovery_id=discovery_id, secret_keys=secret_keys)
    return {
        "discoveryId": discovery_id,
        "snapshot": _public_snapshot(snapshot),
        "spec": spec,
        "secretKeys": secret_keys,
    }


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    public = dict(snapshot)
    raw = dict(snapshot.get("raw", {}))
    raw.pop("_secrets", None)
    public["raw"] = raw
    return public


def _to_canonical(snapshot: dict[str, Any], discovery_id: str = "", secret_keys: list[str] | None = None) -> dict[str, Any]:
    provider = snapshot["provider"]
    app_identifier = snapshot["appIdentifier"]
    raw = snapshot.get("raw", {})

    if provider == "render":
        target_provider = "orena" if settings.DEFAULT_EAST_AFRICA_PROVIDER == "orena" else "railway"
    elif provider == "railway":
        target_provider = "orena" if settings.DEFAULT_EAST_AFRICA_PROVIDER == "orena" else "render"
    elif provider == "orena":
        target_provider = "orena"
    else:
        target_provider = provider

    if provider in {"render", "railway", "fly"} and target_provider == "orena":
        region = settings.DEFAULT_EAST_AFRICA_REGION
    else:
        region = raw.get("region") or (raw.get("regions") or ["us-east-1"])[0] if raw.get("regions") else "us-east-1"

    runtime = raw.get("runtime") or "node"
    start_command = raw.get("startCommand") or "node server.js"
    build_command = raw.get("buildCommand") or ""
    environment = dict(raw.get("environment") or {"NODE_ENV": "production"})
    keys = secret_keys if secret_keys is not None else list(raw.get("secretKeys", []))
    databases: list[dict[str, Any]] = []
    if provider == "supabase":
        runtime = "docker"
        databases = [{"name": "primary", "engine": "postgres", "version": raw.get("dbVersion") or "16"}]

    app_name = raw.get("name") or app_identifier

    service: dict[str, Any] = {
        "name": "web",
        "runtime": runtime,
        "startCommand": start_command,
        "region": region,
        "replicas": 1,
        "environment": environment,
        "secrets": _public_secret_entries(keys),
    }
    if build_command:
        service["buildCommand"] = build_command

    metadata: dict[str, Any] = {
        "requestedBy": "discovery",
        "requestedAt": datetime.now(timezone.utc).isoformat(),
        "environment": "stage",
    }
    if discovery_id:
        metadata["discoveryId"] = discovery_id

    repo = raw.get("repo")
    repo_url = f"https://github.com/{repo}" if repo and "/" in repo and "://" not in repo else repo

    return {
        "appName": app_name,
        "sourceProvider": provider,
        "targetProvider": target_provider,
        "repoUrl": repo_url or "",
        "branch": raw.get("branch") or "main",
        "services": [service],
        "domains": [{"host": f"{app_name}.example.com", "tlsRequired": True}],
        "databases": databases,
        "metadata": metadata,
    }
