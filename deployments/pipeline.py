"""Orchestrates the deployment stages into a single pipeline run."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from core.integrity import integrity_hash

from .framework_detector import detect_framework
from . import stages


def _readiness_checks(stage_results: list[dict[str, Any]], request: dict[str, Any]) -> list[dict[str, Any]]:
    by_stage = {s["stage"]: s for s in stage_results}

    def passed(stage: str) -> bool:
        return by_stage.get(stage, {}).get("status") in {"succeeded", "skipped"}

    checks = [
        {"name": "app-deployed", "passed": by_stage.get("deploy-app", {}).get("status") == "succeeded", "detail": "Application deploy stage succeeded"},
        {"name": "database-ready", "passed": passed("provision-database"), "detail": "Database provisioning completed"},
        {"name": "env-configured", "passed": passed("configure-env-vars"), "detail": "Environment and secrets configured"},
        {"name": "dns-ready", "passed": passed("create-dns-records"), "detail": "DNS records resolved"},
        {"name": "tls-active", "passed": passed("enable-ssl"), "detail": "TLS / SSL enabled"},
    ]
    return checks


def _resolve_live_url(stage_results: list[dict[str, Any]], request: dict[str, Any]) -> str:
    if request.get("domain"):
        return f"https://{request['domain']}"
    deploy = next((s for s in stage_results if s["stage"] == "deploy-app"), None)
    host = (deploy or {}).get("data", {}).get("hostname") or f"{request['appName']}.example.com"
    return f"https://{host}"


def run_pipeline(request: dict[str, Any]) -> dict[str, Any]:
    framework = detect_framework(request.get("files", []), request.get("packageJson"))

    create_env = stages.stage_create_environment(request)
    database = stages.stage_provision_database(request, framework)
    env_vars = stages.stage_configure_env_vars(request)
    deploy = stages.stage_deploy_app(request, framework)
    domain = stages.stage_setup_domain(request)
    dns = stages.stage_create_dns_records(request)
    ssl = stages.stage_enable_ssl(request, dns)
    stripe = stages.stage_configure_stripe(request)
    monitoring = stages.stage_setup_monitoring(request)
    backups = stages.stage_setup_backups(request)

    stage_results = [create_env, database, env_vars, deploy, domain, dns, ssl, stripe, monitoring, backups]
    readiness = _readiness_checks(stage_results, request)
    succeeded = all(s["status"] != "failed" for s in stage_results) and all(c["passed"] for c in readiness)

    result = {
        "deploymentId": str(uuid.uuid4()),
        "appName": request["appName"],
        "framework": framework.to_dict(),
        "stages": stage_results,
        "readiness": readiness,
        "liveUrl": _resolve_live_url(stage_results, request),
        "succeeded": succeeded,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "finishedAt": datetime.now(timezone.utc).isoformat(),
    }
    result["integrityHash"] = integrity_hash(result)
    return result
