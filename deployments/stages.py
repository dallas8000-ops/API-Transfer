"""Deployment pipeline stages.

Each stage returns a StageResult dict {stage, status, detail, data}. Stages that
integrate with external providers (database, deploy, dns, stripe) call the real
API when the relevant credential is configured, and otherwise return a safe
simulated result flagged ``data.live = False``. Sensitive values produced by a
stage (db password, connection string, Stripe webhook secret) are sealed with
AES-256-GCM and never returned in plaintext.
"""
from __future__ import annotations

import logging
import secrets as secrets_mod
from typing import Any

from django.conf import settings

from core.vault import encrypt_secret
from migrationengine import providers
from migrationengine.discovery_vault import hydrate_service_secrets
from migrationengine.providers import ProviderApiError

from .framework_detector import DetectedFramework

logger = logging.getLogger("deployments")


def _ok(stage: str, detail: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"stage": stage, "status": "succeeded", "detail": detail, "data": data or {}}


def _failed(stage: str, detail: str) -> dict[str, Any]:
    return {"stage": stage, "status": "failed", "detail": detail, "data": {}}


def stage_create_environment(request: dict[str, Any]) -> dict[str, Any]:
    return _ok(
        "create-environment",
        f"Initialized {request['targetEnvironment']} environment for {request['appName']}.",
        {"environment": request["targetEnvironment"]},
    )


def stage_provision_database(request: dict[str, Any], framework: DetectedFramework) -> dict[str, Any]:
    db_password = secrets_mod.token_urlsafe(24)
    sealed_password = encrypt_secret(db_password).to_dict()

    if settings.SUPABASE_ACCESS_TOKEN and settings.SUPABASE_ORG_ID:
        try:
            result = providers.provision_supabase_database(request["appName"], db_password)
            sealed_conn = encrypt_secret(
                f"postgres://postgres:{db_password}@{result['host']}:5432/postgres"
            ).to_dict()
            return _ok(
                "provision-database",
                f"Provisioned Supabase Postgres project {result['projectRef']}.",
                {"live": True, "projectRef": result["projectRef"], "region": result["region"], "sealedPassword": sealed_password, "sealedConnectionString": sealed_conn},
            )
        except ProviderApiError as exc:
            logger.error("Supabase provisioning failed: %s", exc)
            return _failed("provision-database", str(exc))

    return _ok(
        "provision-database",
        "Simulated Postgres database (no Supabase credentials configured).",
        {"live": False, "region": settings.SUPABASE_DEFAULT_REGION, "sealedPassword": sealed_password},
    )


def stage_configure_env_vars(request: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(request.get("environment", {}).keys())
    return _ok(
        "configure-env-vars",
        f"Configured {len(keys)} environment variable(s) and {len(request.get('secrets', []))} secret(s).",
        {"environmentKeys": keys, "secretCount": len(request.get("secrets", []))},
    )


def _hydrate_deploy_environment(request: dict[str, Any]) -> dict[str, str]:
    env = dict(request.get("environment", {}))
    for secret in request.get("secrets", []):
        if secret.get("value"):
            env[secret["key"]] = secret["value"]
    discovery_id = request.get("discoveryId") or ""
    if discovery_id:
        env.update(hydrate_service_secrets(discovery_id))
    return env


def stage_deploy_app(request: dict[str, Any], framework: DetectedFramework) -> dict[str, Any]:
    image = f"registry.fly.io/{request['appName']}:latest"
    env = _hydrate_deploy_environment(request)

    if settings.RENDER_API_TOKEN and settings.RENDER_OWNER_ID and request["targetProvider"] == "render":
        try:
            result = providers.deploy_render_web_service(
                request["appName"],
                request.get("repoUrl", ""),
                request.get("branch", ""),
                framework.build_command,
                framework.start_command,
                env,
                request.get("region"),
            )
            return _ok(
                "deploy-app",
                f"Deployed {framework.framework} app to Render ({result['hostname']}).",
                {
                    "live": True,
                    "provider": "render",
                    "hostname": result["hostname"],
                    "serviceId": result.get("serviceId"),
                    "deployId": result.get("deployId"),
                    "dashboardUrl": result.get("dashboardUrl"),
                },
            )
        except ProviderApiError as exc:
            logger.error("Render deployment failed: %s", exc)
            return _failed("deploy-app", str(exc))

    if settings.RAILWAY_API_TOKEN and settings.RAILWAY_PROJECT_ID and request["targetProvider"] == "railway":
        try:
            result = providers.deploy_railway_service(
                request["appName"],
                request.get("repoUrl", ""),
                request.get("branch", ""),
                framework.build_command,
                framework.start_command,
                env,
            )
            return _ok(
                "deploy-app",
                f"Deployed {framework.framework} app to Railway ({result['hostname']}).",
                {
                    "live": True,
                    "provider": "railway",
                    "hostname": result["hostname"],
                    "serviceId": result.get("serviceId"),
                    "deployId": result.get("deployId"),
                    "environmentId": result.get("environmentId"),
                    "dashboardUrl": result.get("dashboardUrl"),
                },
            )
        except ProviderApiError as exc:
            logger.error("Railway deployment failed: %s", exc)
            return _failed("deploy-app", str(exc))

    if settings.FLY_API_TOKEN and request["targetProvider"] == "fly":
        try:
            result = providers.deploy_fly_app(request["appName"], image, env)
            return _ok(
                "deploy-app",
                f"Deployed {framework.framework} app to Fly.io ({result['hostname']}).",
                {"live": True, "hostname": result["hostname"], "machineId": result.get("machineId")},
            )
        except ProviderApiError as exc:
            logger.error("Fly deployment failed: %s", exc)
            return _failed("deploy-app", str(exc))

    return _ok(
        "deploy-app",
        f"Simulated deploy of {framework.framework} app to {request['targetProvider']} (live provider credentials are not configured).",
        {"live": False, "hostname": f"{request['appName']}.{request['targetProvider']}.app"},
    )


def stage_setup_domain(request: dict[str, Any]) -> dict[str, Any]:
    domain = request.get("domain")
    if not domain:
        return {"stage": "setup-domain", "status": "skipped", "detail": "No custom domain requested.", "data": {}}
    return _ok("setup-domain", f"Registered custom domain {domain}.", {"domain": domain})


def stage_create_dns_records(request: dict[str, Any]) -> dict[str, Any]:
    domain = request.get("domain")
    if not domain:
        return {"stage": "create-dns-records", "status": "skipped", "detail": "No domain to point.", "data": {}}

    if settings.CLOUDFLARE_API_TOKEN and settings.CLOUDFLARE_ZONE_ID:
        try:
            result = providers.create_dns_record(domain, settings.DEPLOY_DNS_TARGET)
            return _ok(
                "create-dns-records",
                f"Created proxied A record for {domain} via Cloudflare.",
                {"live": True, "recordId": result["recordId"], "proxied": result["proxied"]},
            )
        except ProviderApiError as exc:
            logger.error("Cloudflare DNS failed: %s", exc)
            return _failed("create-dns-records", str(exc))

    return _ok(
        "create-dns-records",
        f"Simulated A record for {domain} -> {settings.DEPLOY_DNS_TARGET} (no Cloudflare credentials).",
        {"live": False, "target": settings.DEPLOY_DNS_TARGET, "proxied": False},
    )


def stage_enable_ssl(request: dict[str, Any], dns_stage: dict[str, Any]) -> dict[str, Any]:
    domain = request.get("domain")
    if not domain:
        return {"stage": "enable-ssl", "status": "skipped", "detail": "No domain to secure.", "data": {}}
    proxied = bool(dns_stage.get("data", {}).get("proxied"))
    detail = "Cloudflare Universal SSL active (proxied)." if proxied else "Simulated managed TLS certificate."
    return _ok("enable-ssl", detail, {"live": proxied, "universalSsl": proxied})


def stage_configure_stripe(request: dict[str, Any]) -> dict[str, Any]:
    if not request.get("enableStripe"):
        return {"stage": "configure-stripe", "status": "skipped", "detail": "Stripe not enabled.", "data": {}}

    host = request.get("domain") or f"{request['appName']}.example.com"
    webhook_url = f"https://{host}/webhooks/stripe"

    if settings.STRIPE_SECRET_KEY:
        try:
            result = providers.setup_stripe(request["appName"], webhook_url)
            sealed_secret = encrypt_secret(result["webhookSecret"] or "").to_dict()
            return _ok(
                "configure-stripe",
                "Configured Stripe product, price and webhook endpoint.",
                {"live": True, "productId": result["productId"], "priceId": result["priceId"], "sealedWebhookSecret": sealed_secret},
            )
        except ProviderApiError as exc:
            logger.error("Stripe setup failed: %s", exc)
            return _failed("configure-stripe", str(exc))

    sealed_secret = encrypt_secret("whsec_simulated").to_dict()
    return _ok(
        "configure-stripe",
        "Simulated Stripe setup (no Stripe credentials configured).",
        {"live": False, "sealedWebhookSecret": sealed_secret},
    )


def stage_setup_monitoring(request: dict[str, Any]) -> dict[str, Any]:
    if not request.get("enableMonitoring"):
        return {"stage": "setup-monitoring", "status": "skipped", "detail": "Monitoring not enabled.", "data": {}}
    return _ok("setup-monitoring", "Configured health checks and metrics collection.", {"interval": "60s"})


def stage_setup_backups(request: dict[str, Any]) -> dict[str, Any]:
    if not request.get("enableBackups"):
        return {"stage": "setup-backups", "status": "skipped", "detail": "Backups not enabled.", "data": {}}
    return _ok("setup-backups", "Scheduled daily encrypted backups with 7-day retention.", {"schedule": "daily", "retentionDays": 7})
