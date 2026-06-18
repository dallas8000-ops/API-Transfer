"""Platform setup audit, safe auto-actions, and client prewire orchestration.

Identifies configuration gaps, runs API-level setup when credentials exist, and
pre-wires client workspaces without mutating unrelated app state.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

from django.conf import settings

from billing import client as stripe_client
from billing import paystack_client
from billing.models import ProviderConnection, Workspace
from billing.stripe_config import PLANS
from core.regional import DEFAULT_EAST_AFRICA_PROVIDER, DEFAULT_EAST_AFRICA_REGION


def _missing(*keys: str) -> list[str]:
    return [key for key in keys if not str(getattr(settings, key, "") or "").strip()]


def _platform_base_url() -> str:
    success = settings.BILLING_SUCCESS_URL or ""
    if success:
        parsed = urlparse(success)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    cancel = settings.BILLING_CANCEL_URL or ""
    if cancel:
        parsed = urlparse(cancel)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return "http://localhost:8000"


@dataclass
class SetupIssue:
    idempotency_id: str
    severity: str
    title: str
    detail: str
    resolution: str
    autoFixable: bool = False
    autoActionId: str = ""
    autoActionLabel: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.idempotency_id,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "resolution": self.resolution,
            "autoFixable": self.autoFixable,
            "autoActionId": self.autoActionId,
        }
        if self.autoActionLabel:
            payload["autoActionLabel"] = self.autoActionLabel
        return payload


@dataclass
class SetupTask:
    id: str
    service: str
    title: str
    status: str  # ready | partial | missing
    category: str = "migration"  # foundation | migration | billing
    issues: list[SetupIssue] = field(default_factory=list)
    autoActions: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "service": self.service,
            "title": self.title,
            "status": self.status,
            "category": self.category,
            "issues": [issue.to_dict() for issue in self.issues],
            "autoActions": self.autoActions,
        }


def _credential_migration_task(
    *,
    id: str,
    service: str,
    title: str,
    required_keys: tuple[str, ...],
    issue_id: str,
    detail: str,
    resolution: str,
    verify_action_id: str,
    verify_label: str,
    optional_keys: tuple[str, ...] = (),
) -> SetupTask:
    """Build a migration-provider audit task from required (and optional) env keys."""
    missing_required = _missing(*required_keys)
    missing_optional = _missing(*optional_keys) if optional_keys else []
    issues: list[SetupIssue] = []
    actions: list[dict[str, str]] = []
    if missing_required:
        issues.append(
            SetupIssue(
                issue_id,
                "high",
                f"{title} credentials incomplete",
                f"Missing: {', '.join(missing_required)}. {detail}",
                resolution,
            )
        )
    else:
        if missing_optional:
            issues.append(
                SetupIssue(
                    f"{issue_id}-optional",
                    "medium",
                    f"{title} deploy credentials incomplete",
                    f"Missing: {', '.join(missing_optional)}. {detail}",
                    resolution,
                )
            )
        actions.append({"id": verify_action_id, "label": verify_label})
    status = "missing" if missing_required else _task_status(issues)
    return SetupTask(
        id=id,
        service=service,
        title=title,
        status=status,
        category="migration",
        issues=issues,
        autoActions=actions,
    )


def _task_status(issues: list[SetupIssue]) -> str:
    if not issues:
        return "ready"
    critical = any(i.severity in {"critical", "high"} for i in issues)
    return "missing" if critical else "partial"


STRIPE_PLATFORM_ENV_KEYS = (
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRICE_PRO",
    "STRIPE_PRICE_SCALE",
)


def _env_lines_block(values: dict[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in values.items() if value)


def detect_stripe_installer_sources() -> list[dict[str, Any]]:
    """Find Stripe Installer-like Railway services and report linked GitHub + env key names."""
    if _missing("RAILWAY_API_TOKEN", "RAILWAY_PROJECT_ID"):
        return []

    from migrationengine.providers import (
        ProviderApiError,
        _railway_environment_id,
        get_railway_env_vars,
        get_railway_service_source,
        list_railway_services,
    )

    sources: list[dict[str, Any]] = []
    try:
        services = list_railway_services()
    except ProviderApiError:
        return sources

    for service in services:
        name = str(service.get("name") or "")
        lowered = name.lower()
        if "stripe" not in lowered and "installer" not in lowered:
            continue
        service_id = str(service.get("id") or "")
        project_id = str(service.get("projectId") or settings.RAILWAY_PROJECT_ID)
        environment_id = str(service.get("environmentId") or _railway_environment_id(project_id))
        try:
            env = get_railway_env_vars(project_id, service_id, environment_id)
        except ProviderApiError:
            env = {}
        source = get_railway_service_source(service_id)
        repo_url = str(source.get("repoUrl") or "")
        github_scan: dict[str, Any] = {}
        if repo_url:
            try:
                from migrationengine.github_import import scan_stripe_env_keys_from_github

                github_scan = scan_stripe_env_keys_from_github(
                    repo_url,
                    branch=str(source.get("branch") or ""),
                )
            except Exception:  # noqa: BLE001
                github_scan = {"repoUrl": repo_url, "stripeKeys": [], "envTemplateFile": None}

        stripe_keys = sorted(key for key in env if key.startswith("STRIPE_"))
        sources.append(
            {
                "platform": "railway",
                "serviceName": name,
                "serviceId": service_id,
                "projectId": project_id,
                "repoUrl": repo_url or None,
                "branch": source.get("branch"),
                "stripeKeysOnRailway": stripe_keys,
                "hasStripeSecret": bool(str(env.get("STRIPE_SECRET_KEY") or "").strip()),
                "githubEnvTemplate": github_scan.get("envTemplateFile"),
                "githubStripeKeys": github_scan.get("stripeKeys") or [],
            }
        )
    sources.sort(key=lambda item: (0 if item.get("serviceName", "").lower() == "stripe-installer" else 1, item.get("serviceName", "")))
    return sources


def east_africa_env_template() -> str:
    """Full annotated .env template for East Africa prep (no clients required)."""
    path = settings.BASE_DIR / "env.east-africa.template"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def audit_platform() -> dict[str, Any]:
    tasks: list[SetupTask] = []
    base_url = _platform_base_url()

    vault_env_missing = not os.environ.get("VAULT_MASTER_KEY_BASE64", "").strip()
    vault_issues: list[SetupIssue] = []
    vault_actions: list[dict[str, str]] = []
    if vault_env_missing:
        vault_issues.append(
            SetupIssue(
                "vault-master-key",
                "critical" if not settings.DEBUG else "high",
                "Vault master key not persisted in .env",
                "Secrets cannot be sealed consistently without VAULT_MASTER_KEY_BASE64 in .env.",
                "Generate a key and save it to .env (auto on localhost). Restart is not required after apply.",
                autoFixable=True,
                autoActionId="generate_vault_key",
                autoActionLabel="Generate vault key & save to .env",
            )
        )
        vault_actions.append({"id": "generate_vault_key", "label": "Generate vault key & save to .env"})
    tasks.append(
        SetupTask(
            id="vault",
            service="vault",
            title="Encrypted secret vault",
            status="missing" if vault_env_missing and not settings.DEBUG else ("partial" if vault_env_missing else "ready"),
            category="foundation",
            issues=vault_issues,
            autoActions=vault_actions,
        )
    )

    # --- Migration & deploy APIs (core API Transfer) ----------------------------
    tasks.append(
        _credential_migration_task(
            id="railway",
            service="railway",
            title="Railway (discover, deploy, transfer)",
            required_keys=("RAILWAY_API_TOKEN", "RAILWAY_PROJECT_ID"),
            issue_id="railway-creds",
            detail="Used for account review, live discovery, Render→Railway transfers, and deploy stages.",
            resolution="Add RAILWAY_API_TOKEN and RAILWAY_PROJECT_ID from railway.app → Account → Tokens and project Settings.",
            verify_action_id="verify_railway",
            verify_label="Test Railway GraphQL connection",
        )
    )
    tasks.append(
        _credential_migration_task(
            id="render",
            service="render",
            title="Render (source inventory & deploy)",
            required_keys=("RENDER_API_TOKEN",),
            optional_keys=("RENDER_OWNER_ID",),
            issue_id="render-creds",
            detail="Account review works with RENDER_API_TOKEN; live deploy also needs RENDER_OWNER_ID.",
            resolution="Add RENDER_API_TOKEN from dashboard.render.com → Account → API Keys and RENDER_OWNER_ID from team settings.",
            verify_action_id="verify_render",
            verify_label="Test Render API connection",
        )
    )
    tasks.append(
        _credential_migration_task(
            id="fly",
            service="fly",
            title="Fly.io (discover & deploy)",
            required_keys=("FLY_API_TOKEN",),
            issue_id="fly-creds",
            detail="Enables live Fly.io deploy stages in the one-click pipeline.",
            resolution="Add FLY_API_TOKEN from fly.io → Account → Access Tokens.",
            verify_action_id="verify_fly",
            verify_label="Test Fly.io API connection",
        )
    )

    orena_missing = _missing("ORENA_API_TOKEN")
    orena_issues: list[SetupIssue] = []
    orena_actions: list[dict[str, str]] = []
    if orena_missing:
        orena_issues.append(
            SetupIssue(
                "orena-token",
                "high",
                "Orena API token missing",
                "East Africa target deploys and account review require ORENA_API_TOKEN.",
                "Create an API token in Orena Console → Access → API tokens.",
            )
        )
    else:
        orena_actions.append({"id": "verify_orena", "label": "Test Orena connection & list apps"})

    tasks.append(
        SetupTask(
            id="orena",
            service="orena",
            title=f"Orena Cloud ({settings.ORENA_DEFAULT_REGION}) — regional target",
            status=_task_status(orena_issues),
            category="migration",
            issues=orena_issues,
            autoActions=orena_actions,
        )
    )

    tasks.append(
        _credential_migration_task(
            id="supabase",
            service="supabase",
            title="Supabase (database provisioning)",
            required_keys=("SUPABASE_ACCESS_TOKEN", "SUPABASE_ORG_ID"),
            issue_id="supabase-creds",
            detail="Used by deploy stages to provision Postgres when migrating apps with databases.",
            resolution="Add SUPABASE_ACCESS_TOKEN and SUPABASE_ORG_ID from supabase.com → Account → Access Tokens.",
            verify_action_id="verify_supabase",
            verify_label="Test Supabase API connection",
        )
    )
    tasks.append(
        _credential_migration_task(
            id="cloudflare",
            service="cloudflare",
            title="Cloudflare (DNS & TLS)",
            required_keys=("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ZONE_ID"),
            issue_id="cloudflare-creds",
            detail="Creates proxied DNS records during domain and SSL deploy stages.",
            resolution="Add CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID from dash.cloudflare.com → My Profile → API Tokens.",
            verify_action_id="verify_cloudflare",
            verify_label="Test Cloudflare zone access",
        )
    )

    github_token_missing = _missing("GITHUB_TOKEN")
    github_issues: list[SetupIssue] = []
    github_actions: list[dict[str, str]] = [{"id": "verify_github", "label": "Test GitHub API connection"}]
    if github_token_missing:
        github_issues.append(
            SetupIssue(
                "github-token-optional",
                "info",
                "GitHub token not set (optional)",
                "Public repo import works without GITHUB_TOKEN; private repos and higher rate limits need a token.",
                "Add GITHUB_TOKEN from github.com → Settings → Developer settings → Personal access tokens.",
            )
        )

    tasks.append(
        SetupTask(
            id="github",
            service="github",
            title="GitHub (repo import & detection)",
            status="ready" if not github_token_missing else "partial",
            category="migration",
            issues=github_issues,
            autoActions=github_actions,
        )
    )

    # --- Platform billing (API Transfer subscriptions — not client app billing) ---
    stripe_missing = _missing("STRIPE_SECRET_KEY")
    stripe_issues: list[SetupIssue] = []
    stripe_actions: list[dict[str, str]] = []
    stripe_installer_sources = detect_stripe_installer_sources()
    if stripe_missing:
        stripe_issues.append(
            SetupIssue(
                "stripe-secret",
                "high",
                "Stripe secret key missing on API Transfer",
                "This server's .env needs Stripe keys for /pricing checkout. Keys on Railway/GitHub are separate until synced here.",
                "Add STRIPE_SECRET_KEY from Stripe Dashboard, or sync from your Railway Stripe Installer service.",
            )
        )
        if stripe_installer_sources:
            detected = stripe_installer_sources[0]
            repo_hint = f" GitHub: {detected['repoUrl']}." if detected.get("repoUrl") else ""
            stripe_issues.append(
                SetupIssue(
                    "stripe-installer-detected",
                    "info",
                    "Stripe Installer detected on Railway",
                    (
                        f"Service '{detected['serviceName']}' has Stripe env on Railway "
                        f"({', '.join(detected.get('stripeKeysOnRailway') or []) or 'no STRIPE_* keys'})."
                        f"{repo_hint}"
                    ),
                    "Run 'Sync Stripe from Railway' to copy keys into this app's .env (for platform billing). On localhost, keys are written to .env automatically.",
                    autoFixable=True,
                    autoActionId="sync_stripe_from_railway",
                    autoActionLabel="Sync Stripe from Railway (Stripe Installer)",
                )
            )
            stripe_actions.append(
                {"id": "sync_stripe_from_railway", "label": "Sync Stripe from Railway (Stripe Installer)"}
            )
    else:
        if _missing("STRIPE_PRICE_PRO"):
            stripe_issues.append(
                SetupIssue(
                    "stripe-price-pro",
                    "high",
                    "Pro plan price ID not set",
                    "Checkout cannot start without STRIPE_PRICE_PRO.",
                    "Run auto-setup to create/find Stripe prices, or paste a price ID from the Stripe catalog.",
                    autoFixable=True,
                    autoActionId="bootstrap_stripe_catalog",
                    autoActionLabel="Create/find Stripe Pro & Scale prices",
                )
            )
            stripe_actions.append({"id": "bootstrap_stripe_catalog", "label": "Create/find Stripe Pro & Scale prices"})
        if _missing("STRIPE_WEBHOOK_SECRET"):
            stripe_issues.append(
                SetupIssue(
                    "stripe-webhook",
                    "medium",
                    "Stripe webhook secret missing",
                    f"Subscriptions won't sync until webhooks hit {base_url}/api/billing/webhook.",
                    "Run auto-setup to register the webhook endpoint; on localhost the secret is saved to .env automatically.",
                    autoFixable=True,
                    autoActionId="bootstrap_stripe_webhook",
                    autoActionLabel="Register Stripe billing webhook",
                )
            )
            stripe_actions.append({"id": "bootstrap_stripe_webhook", "label": "Register Stripe billing webhook"})
        stripe_actions.append({"id": "verify_stripe", "label": "Test Stripe API connection"})

    tasks.append(
        SetupTask(
            id="stripe_billing",
            service="stripe",
            title="Stripe billing (USD subscriptions)",
            status=_task_status(stripe_issues),
            category="billing",
            issues=stripe_issues,
            autoActions=stripe_actions,
        )
    )

    paystack_missing = _missing("PAYSTACK_SECRET_KEY")
    paystack_issues: list[SetupIssue] = []
    paystack_actions: list[dict[str, str]] = []
    if paystack_missing:
        paystack_issues.append(
            SetupIssue(
                "paystack-secret",
                "high",
                "Paystack secret key missing",
                "KES/M-Pesa billing requires PAYSTACK_SECRET_KEY.",
                "Add PAYSTACK_SECRET_KEY from Paystack Dashboard → Settings → API Keys.",
            )
        )
    else:
        if _missing("PAYSTACK_PLAN_PRO"):
            paystack_issues.append(
                SetupIssue(
                    "paystack-plan-pro",
                    "high",
                    "Paystack Pro plan code missing",
                    "East Africa checkout needs PAYSTACK_PLAN_PRO.",
                    "Run auto-setup to match existing Paystack plans or create plans in Paystack dashboard.",
                    autoFixable=True,
                    autoActionId="verify_paystack_plans",
                    autoActionLabel="Find Paystack plan codes",
                )
            )
            paystack_actions.append({"id": "verify_paystack_plans", "label": "Find Paystack plan codes"})
        paystack_issues.append(
            SetupIssue(
                "paystack-webhook-manual",
                "info",
                "Register Paystack webhook",
                f"Add webhook URL {base_url}/api/billing/webhook/paystack in Paystack dashboard (charge.success, subscription.create).",
                "Paystack webhooks are configured in the dashboard — copy events after saving.",
            )
        )
        paystack_actions.append({"id": "verify_paystack", "label": "Test Paystack API connection"})

    tasks.append(
        SetupTask(
            id="paystack_billing",
            service="paystack",
            title="Paystack billing (KES / M-Pesa subscriptions)",
            status=_task_status([i for i in paystack_issues if i.severity != "info"]),
            category="billing",
            issues=paystack_issues,
            autoActions=paystack_actions,
        )
    )

    migration_tasks = [t for t in tasks if t.category == "migration"]
    billing_tasks = [t for t in tasks if t.category == "billing"]
    ready_count = sum(1 for t in tasks if t.status == "ready")
    auto_fixable = sum(1 for t in tasks for i in t.issues if i.autoFixable)

    return {
        "summary": {
            "totalTasks": len(tasks),
            "ready": ready_count,
            "needsAttention": len(tasks) - ready_count,
            "autoFixableIssues": auto_fixable,
            "platformUrl": base_url,
            "migrationReady": sum(1 for t in migration_tasks if t.status == "ready"),
            "migrationTotal": len(migration_tasks),
            "billingReady": sum(1 for t in billing_tasks if t.status == "ready"),
            "billingTotal": len(billing_tasks),
        },
        "tasks": [task.to_dict() for task in tasks],
        "suggestedEnv": _suggested_env_block(tasks),
        "envTemplate": east_africa_env_template(),
        "envTemplatePath": "env.east-africa.template",
        "stripeInstallerSources": stripe_installer_sources,
        "globalAutoActions": [
            {"id": "verify_all_providers", "label": "Run all connection tests"},
            {"id": "generate_env_template", "label": "Refresh .env template"},
        ],
    }


def _suggested_env_block(tasks: list[SetupTask] | None = None) -> str:
    lines = ["# API Transfer — suggested .env (paste missing values only)"]
    if tasks is None:
        raw_tasks = audit_platform()["tasks"]
    else:
        raw_tasks = [t.to_dict() if isinstance(t, SetupTask) else t for t in tasks]
    for task in raw_tasks:
        for issue in task.get("issues", []):
            if issue["severity"] in {"critical", "high", "medium"}:
                lines.append(f"# {issue['title']}: {issue['resolution']}")
    lines.extend(
        [
            "",
            f"DEFAULT_EAST_AFRICA_PROVIDER={DEFAULT_EAST_AFRICA_PROVIDER}",
            f"DEFAULT_EAST_AFRICA_REGION={DEFAULT_EAST_AFRICA_REGION}",
        ]
    )
    return "\n".join(lines)


def _stripe_get(path: str, params: dict | None = None) -> dict[str, Any]:
    return stripe_client.get_api(path, params)


def _action_verify_stripe() -> dict[str, Any]:
    if not stripe_client.is_configured():
        return {"ok": False, "message": "STRIPE_SECRET_KEY is not configured."}
    _stripe_get("/v1/balance")
    return {"ok": True, "message": "Stripe API connection verified."}


def _action_bootstrap_stripe_catalog() -> dict[str, Any]:
    if not stripe_client.is_configured():
        return {"ok": False, "message": "STRIPE_SECRET_KEY is not configured."}

    suggested: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    for plan in PLANS:
        if plan.slug not in {"pro", "scale"}:
            continue
        env_key = f"STRIPE_PRICE_{plan.slug.upper()}"
        existing = getattr(settings, env_key, "")
        if existing:
            results.append({"plan": plan.slug, "priceId": existing, "source": "settings"})
            continue

        prices = _stripe_get("/v1/prices", {"limit": 100, "active": "true"})
        matched = None
        for item in prices.get("data", []):
            if item.get("unit_amount") == plan.price_cents and item.get("recurring", {}).get("interval") == plan.interval:
                matched = item.get("id")
                break

        if not matched:
            product = stripe_client.post_api("/v1/products", {"name": f"API Transfer {plan.name}"})
            price = stripe_client.post_api(
                "/v1/prices",
                {
                    "product": product["id"],
                    "unit_amount": str(plan.price_cents),
                    "currency": settings.BILLING_CURRENCY,
                    "recurring[interval]": plan.interval,
                },
            )
            matched = price.get("id")
            source = "created"
        else:
            source = "found"

        suggested[env_key] = matched or ""
        results.append({"plan": plan.slug, "priceId": matched, "source": source})

    return {
        "ok": True,
        "message": "Stripe catalog ready.",
        "results": results,
        "suggestedEnv": suggested,
        "suggestedEnvText": _env_lines_block(suggested),
    }


def _action_bootstrap_stripe_webhook() -> dict[str, Any]:
    if not stripe_client.is_configured():
        return {"ok": False, "message": "STRIPE_SECRET_KEY is not configured."}

    base_url = _platform_base_url()
    webhook_url = f"{base_url}/api/billing/webhook"
    endpoints = _stripe_get("/v1/webhook_endpoints", {"limit": 100})
    existing = None
    for item in endpoints.get("data", []):
        if item.get("url") == webhook_url:
            existing = item
            break

    if existing:
        return {
            "ok": True,
            "message": "Stripe webhook endpoint already registered.",
            "webhookUrl": webhook_url,
            "endpointId": existing.get("id"),
            "note": "Webhook signing secret is only shown at creation — use Dashboard if STRIPE_WEBHOOK_SECRET is missing.",
        }

    webhook = stripe_client.post_api(
        "/v1/webhook_endpoints",
        {
            "url": webhook_url,
            "enabled_events[]": "checkout.session.completed",
            "enabled_events[1]": "customer.subscription.created",
            "enabled_events[2]": "customer.subscription.updated",
            "enabled_events[3]": "customer.subscription.deleted",
        },
    )
    suggested = {"STRIPE_WEBHOOK_SECRET": webhook.get("secret") or ""}
    return {
        "ok": True,
        "message": "Stripe webhook registered.",
        "webhookUrl": webhook_url,
        "endpointId": webhook.get("id"),
        "suggestedEnv": suggested,
        "suggestedEnvText": _env_lines_block(suggested),
    }


def _load_stripe_from_env_backups(service_name: str = "") -> dict[str, str]:
    """Load STRIPE_* vars from the newest local transfer-env-backups JSON snapshot."""
    backup_dir = settings.BASE_DIR / "transfer-env-backups"
    if not backup_dir.is_dir():
        return {}

    candidates = sorted(backup_dir.glob("*.json"), reverse=True)
    label = (service_name or "").lower()
    for path in candidates:
        if label and label.replace("_", "-") not in path.name.lower() and "stripe" not in path.name.lower():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        variables = payload.get("variables") or {}
        if not isinstance(variables, dict):
            continue
        found = {
            key: str(variables[key]).strip()
            for key in STRIPE_PLATFORM_ENV_KEYS
            if str(variables.get(key) or "").strip()
        }
        if found.get("STRIPE_SECRET_KEY"):
            return found, str(path)
    return {}, None


def _collect_stripe_env_from_railway(project_id: str) -> tuple[dict[str, str], list[str]]:
    """Merge STRIPE_* vars from every Railway service in the project."""
    from migrationengine.providers import (
        ProviderApiError,
        _railway_environment_id,
        get_railway_env_vars,
        list_railway_services,
    )

    environment_id = _railway_environment_id(project_id)
    merged: dict[str, str] = {}
    service_names: list[str] = []
    try:
        services = list_railway_services(project_id)
    except ProviderApiError:
        return merged, service_names

    for service in services:
        service_id = str(service.get("id") or "")
        if not service_id:
            continue
        try:
            env = get_railway_env_vars(project_id, service_id, environment_id)
        except ProviderApiError:
            continue
        stripe_keys = [key for key in env if key.startswith("STRIPE_")]
        if not stripe_keys:
            continue
        service_names.append(str(service.get("name") or service_id))
        for key in STRIPE_PLATFORM_ENV_KEYS:
            value = str(env.get(key) or "").strip()
            if value:
                merged[key] = value
    return merged, service_names


def _action_sync_stripe_from_railway() -> dict[str, Any]:
    """Pull STRIPE_* vars from Stripe Installer on Railway into .env (when API exposes them)."""
    sources = detect_stripe_installer_sources()
    if not sources:
        return {
            "ok": False,
            "message": "No Stripe Installer service found on Railway. Expected a service named like stripe-installer in RAILWAY_PROJECT_ID.",
        }

    picked = sources[0]
    for candidate in sources:
        if str(candidate.get("serviceName") or "").lower() == "stripe-installer":
            picked = candidate
            break

    project_id = str(picked.get("projectId") or settings.RAILWAY_PROJECT_ID)
    suggested, scanned_services = _collect_stripe_env_from_railway(project_id)
    backup_path: str | None = None

    if not suggested.get("STRIPE_SECRET_KEY"):
        backup_vars, backup_path = _load_stripe_from_env_backups(str(picked.get("serviceName") or ""))
        for key, value in backup_vars.items():
            suggested.setdefault(key, value)

    if not suggested.get("STRIPE_SECRET_KEY"):
        railway_keys = picked.get("stripeKeysOnRailway") or []
        sealed_hint = (
            "Railway often seals STRIPE_SECRET_KEY — the public API only returned: "
            f"{', '.join(railway_keys) or 'no STRIPE_* keys'}."
        )
        partial = {key: value for key, value in suggested.items() if value}
        return {
            "ok": False,
            "message": (
                f"Could not read STRIPE_SECRET_KEY from Railway project {project_id}. {sealed_hint} "
                "Copy sk_test_… or sk_live_… from Stripe Dashboard → Developers → API keys, "
                "paste it in the field below, then click Save Stripe secret to .env."
            ),
            "source": picked,
            "scannedServices": scanned_services,
            "stripeKeysOnRailway": railway_keys,
            "partialEnv": partial,
            "suggestedEnv": partial or None,
            "suggestedEnvText": _env_lines_block(partial) if partial else "",
            "needsManualSecret": True,
        }

    return {
        "ok": True,
        "message": (
            f"Pulled {len(suggested)} Stripe variable(s) from Railway "
            f"({', '.join(scanned_services) or picked.get('serviceName')})."
        ),
        "source": picked,
        "scannedServices": scanned_services,
        "suggestedEnv": suggested,
        "suggestedEnvText": _env_lines_block(suggested),
        "note": "These keys power API Transfer /pricing on this server.",
        "backupSource": backup_path,
    }


def _action_verify_paystack() -> dict[str, Any]:
    if not paystack_client.is_configured():
        return {"ok": False, "message": "PAYSTACK_SECRET_KEY is not configured."}
    paystack_client.list_plans()
    return {"ok": True, "message": "Paystack API connection verified."}


def _action_verify_paystack_plans() -> dict[str, Any]:
    if not paystack_client.is_configured():
        return {"ok": False, "message": "PAYSTACK_SECRET_KEY is not configured."}

    from core.regional import kes_price_cents

    plans = paystack_client.list_plans()

    suggested: dict[str, str] = {}
    results: list[dict[str, Any]] = []
    for plan in PLANS:
        if plan.slug not in {"pro", "scale"}:
            continue
        env_key = f"PAYSTACK_PLAN_{plan.slug.upper()}"
        target_amount = kes_price_cents(plan.slug, plan.price_cents)
        matched = None
        for item in plans or []:
            if not isinstance(item, dict):
                continue
            amount = int(item.get("amount") or 0)
            if abs(amount - target_amount) <= target_amount * 0.05:
                matched = item.get("plan_code") or item.get("code")
                break
        if matched:
            suggested[env_key] = str(matched)
        results.append({"plan": plan.slug, "planCode": matched, "targetAmountKobo": target_amount})

    return {
        "ok": True,
        "message": "Paystack plan scan complete.",
        "results": results,
        "suggestedEnv": suggested,
    }


def _action_verify_orena() -> dict[str, Any]:
    if not settings.ORENA_API_TOKEN:
        return {"ok": False, "message": "ORENA_API_TOKEN is not configured."}
    from migrationengine.providers import list_orena_apps

    apps = list_orena_apps()
    return {"ok": True, "message": f"Orena connected — {len(apps)} app(s) visible.", "appCount": len(apps)}


def _action_verify_railway() -> dict[str, Any]:
    if _missing("RAILWAY_API_TOKEN", "RAILWAY_PROJECT_ID"):
        return {"ok": False, "message": "Railway credentials incomplete."}
    from migrationengine.providers import list_railway_services

    services = list_railway_services()
    return {"ok": True, "message": f"Railway connected — {len(services)} service(s).", "serviceCount": len(services)}


def _action_verify_render() -> dict[str, Any]:
    if _missing("RENDER_API_TOKEN"):
        return {"ok": False, "message": "RENDER_API_TOKEN is not configured."}
    from migrationengine.providers import list_render_services

    services = list_render_services()
    return {"ok": True, "message": f"Render connected — {len(services)} service(s).", "serviceCount": len(services)}


def _action_verify_fly() -> dict[str, Any]:
    if _missing("FLY_API_TOKEN"):
        return {"ok": False, "message": "FLY_API_TOKEN is not configured."}
    import requests

    base = settings.FLY_API_BASE_URL.rstrip("/")
    response = requests.get(
        f"{base}/v1/apps",
        headers={"Authorization": f"Bearer {settings.FLY_API_TOKEN}"},
        timeout=20,
    )
    if response.status_code != 200:
        return {"ok": False, "message": f"Fly.io API error ({response.status_code})."}
    body = response.json()
    apps = body if isinstance(body, list) else body.get("apps", body.get("data", []))
    count = len(apps) if isinstance(apps, list) else 0
    return {"ok": True, "message": f"Fly.io connected — {count} app(s) visible.", "appCount": count}


def _action_verify_supabase() -> dict[str, Any]:
    if _missing("SUPABASE_ACCESS_TOKEN", "SUPABASE_ORG_ID"):
        return {"ok": False, "message": "Supabase credentials incomplete."}
    import requests

    base = settings.SUPABASE_API_BASE_URL.rstrip("/")
    response = requests.get(
        f"{base}/v1/projects",
        headers={"Authorization": f"Bearer {settings.SUPABASE_ACCESS_TOKEN}"},
        timeout=20,
    )
    if response.status_code != 200:
        return {"ok": False, "message": f"Supabase API error ({response.status_code})."}
    projects = response.json()
    count = len(projects) if isinstance(projects, list) else 0
    return {"ok": True, "message": f"Supabase connected — {count} project(s) visible.", "projectCount": count}


def _action_verify_cloudflare() -> dict[str, Any]:
    if _missing("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ZONE_ID"):
        return {"ok": False, "message": "Cloudflare credentials incomplete."}
    import requests

    base = settings.CLOUDFLARE_API_BASE_URL.rstrip("/")
    response = requests.get(
        f"{base}/zones/{settings.CLOUDFLARE_ZONE_ID}",
        headers={"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}"},
        timeout=20,
    )
    if response.status_code != 200:
        return {"ok": False, "message": f"Cloudflare API error ({response.status_code})."}
    body = response.json()
    zone = body.get("result", {})
    return {
        "ok": True,
        "message": f"Cloudflare zone connected — {zone.get('name') or settings.CLOUDFLARE_ZONE_ID}.",
        "zoneName": zone.get("name"),
    }


def _action_verify_github() -> dict[str, Any]:
    import requests

    headers = {"Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    response = requests.get(
        f"{settings.GITHUB_API_BASE_URL.rstrip('/')}/user",
        headers=headers,
        timeout=20,
    )
    if response.status_code == 401 and not settings.GITHUB_TOKEN:
        return {
            "ok": True,
            "message": "GitHub reachable — public repo import works; add GITHUB_TOKEN for private repos.",
            "authenticated": False,
        }
    if response.status_code != 200:
        return {"ok": False, "message": f"GitHub API error ({response.status_code})."}
    user = response.json()
    login = user.get("login", "authenticated")
    return {"ok": True, "message": f"GitHub connected as {login}.", "login": login, "authenticated": True}


def _action_verify_all_providers() -> dict[str, Any]:
    actions = [
        "verify_railway",
        "verify_render",
        "verify_fly",
        "verify_orena",
        "verify_supabase",
        "verify_cloudflare",
        "verify_github",
        "verify_stripe",
        "verify_paystack",
    ]
    results = {action: run_setup_action(action) for action in actions}
    ok = all(r.get("ok") or "not configured" in str(r.get("message", "")).lower() for r in results.values())
    return {"ok": ok, "message": "Provider connection sweep complete.", "results": results}


def _action_generate_vault_key() -> dict[str, Any]:
    if os.environ.get("VAULT_MASTER_KEY_BASE64", "").strip():
        return {"ok": True, "message": "Vault master key is already set in .env.", "alreadyConfigured": True}

    import base64
    import secrets

    key_b64 = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    return {
        "ok": True,
        "message": "Generated a new vault master key.",
        "suggestedEnv": {"VAULT_MASTER_KEY_BASE64": key_b64},
        "suggestedEnvText": f"VAULT_MASTER_KEY_BASE64={key_b64}",
    }


def _action_generate_env_template() -> dict[str, Any]:
    audit = audit_platform()
    return {"ok": True, "message": "Env template generated.", "envTemplate": audit["suggestedEnv"], "audit": audit}


_ACTIONS: dict[str, Callable[[], dict[str, Any]]] = {
    "generate_vault_key": _action_generate_vault_key,
    "verify_stripe": _action_verify_stripe,
    "bootstrap_stripe_catalog": _action_bootstrap_stripe_catalog,
    "bootstrap_stripe_webhook": _action_bootstrap_stripe_webhook,
    "sync_stripe_from_railway": _action_sync_stripe_from_railway,
    "verify_paystack": _action_verify_paystack,
    "verify_paystack_plans": _action_verify_paystack_plans,
    "verify_orena": _action_verify_orena,
    "verify_railway": _action_verify_railway,
    "verify_render": _action_verify_render,
    "verify_fly": _action_verify_fly,
    "verify_supabase": _action_verify_supabase,
    "verify_cloudflare": _action_verify_cloudflare,
    "verify_github": _action_verify_github,
    "verify_all_providers": _action_verify_all_providers,
    "generate_env_template": _action_generate_env_template,
}


def _action_apply_platform_env(env_vars: dict[str, str]) -> dict[str, Any]:
    allowed_prefixes = ("STRIPE_", "PAYSTACK_", "VAULT_")
    filtered = {
        str(key): str(value).strip()
        for key, value in env_vars.items()
        if str(key).strip() and str(value).strip() and str(key).startswith(allowed_prefixes)
    }
    if not filtered:
        return {"ok": False, "message": "No supported env keys to apply (STRIPE_*, PAYSTACK_*, VAULT_*)."}
    return {
        "ok": True,
        "message": f"Ready to apply {len(filtered)} env key(s).",
        "suggestedEnv": filtered,
        "suggestedEnvText": _env_lines_block(filtered),
    }


def run_setup_action(action_id: str, *, apply_to_env: bool = False, env_vars: dict[str, str] | None = None) -> dict[str, Any]:
    if action_id == "apply_platform_env":
        if not env_vars:
            return {"ok": False, "message": "envVars is required for apply_platform_env."}
        try:
            result = _action_apply_platform_env(env_vars)
            result["actionId"] = action_id
            if apply_to_env and result.get("ok"):
                result = _maybe_apply_suggested_env(result)
            return result
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "actionId": action_id, "message": str(exc)}

    handler = _ACTIONS.get(action_id)
    if handler is None:
        return {"ok": False, "message": f"Unknown setup action '{action_id}'."}
    try:
        result = handler()
        result["actionId"] = action_id
        if apply_to_env:
            result = _maybe_apply_suggested_env(result)
        return result
    except Exception as exc:  # noqa: BLE001 — surface provider errors to UI
        return {"ok": False, "actionId": action_id, "message": str(exc)}


def _maybe_apply_suggested_env(result: dict[str, Any]) -> dict[str, Any]:
    from core.env_file import apply_env_updates, can_auto_apply_dotenv

    suggested = result.get("suggestedEnv") or result.get("partialEnv") or {}
    if not isinstance(suggested, dict) or not suggested:
        return result

    if not can_auto_apply_dotenv():
        result["appliedToEnv"] = False
        result["applyNote"] = "Hosted deploy — paste suggested values into Railway service variables."
        return result

    apply_result = apply_env_updates({key: str(value) for key, value in suggested.items() if str(value).strip()})
    if not apply_result.get("applied"):
        result["appliedToEnv"] = False
        result["applyNote"] = apply_result.get("reason") or "Could not write .env automatically."
        return result

    result["appliedToEnv"] = True
    result["appliedKeys"] = apply_result.get("keys", [])
    result["envPath"] = apply_result.get("path")
    base_message = str(result.get("message") or "Setup action completed.")
    result["message"] = (
        f"{base_message} Wrote {len(result['appliedKeys'])} key(s) to .env and reloaded this server."
    )
    return result


CLIENT_SERVICE_MAP = {
    "stripe": {"capabilities": ["billing", "webhooks"], "provider": "stripe"},
    "paystack": {"capabilities": ["billing", "mobile_money"], "provider": None},
    "orena": {"capabilities": ["discover", "deploy", "account-review"], "provider": "orena"},
    "railway": {"capabilities": ["discover", "deploy", "transfer", "account-review"], "provider": "railway"},
    "render": {"capabilities": ["discover", "account-review", "transfer", "deploy"], "provider": "render"},
    "fly": {"capabilities": ["discover", "deploy"], "provider": "fly"},
    "supabase": {"capabilities": ["database"], "provider": "supabase"},
    "cloudflare": {"capabilities": ["dns", "tls"], "provider": "cloudflare"},
    "monitoring": {"capabilities": ["observability"], "provider": "terraform"},
    "backups": {"capabilities": ["backup"], "provider": "terraform"},
}


def prewire_client(
    *,
    operator_email: str,
    client_email: str,
    client_name: str,
    client_domain: str,
    target_provider: str,
    target_region: str,
    source_provider: str = "",
    app_identifier: str = "",
    services: list[str] | None = None,
    run_discover: bool = True,
) -> dict[str, Any]:
    """Create/update a client workspace and prewire provider connections safely."""
    from billing.entitlements import get_or_create_workspace
    from licenses.models import License

    services = services or ["orena", "paystack", "monitoring", "backups"]
    conflicts: list[dict[str, str]] = []

    domain_taken = License.objects.filter(registered_domain=client_domain, status="active").exclude(
        subscription__customer__email=client_email
    ).exists()
    if domain_taken:
        conflicts.append(
            {
                "code": "domain_in_use",
                "message": f"Domain {client_domain} is already licensed to another customer.",
            }
        )

    ctx = get_or_create_workspace(client_email)
    workspace = ctx.workspace
    if client_name and workspace.name != client_name:
        workspace.name = client_name
        workspace.save(update_fields=["name"])

    valid_providers = {choice[0] for choice in ProviderConnection.PROVIDER_CHOICES}

    connections: list[dict[str, Any]] = []
    for service in services:
        meta = CLIENT_SERVICE_MAP.get(service)
        if not meta:
            continue
        provider = meta["provider"]
        if not provider or provider not in valid_providers:
            connections.append(
                {
                    "provider": provider or service,
                    "service": service,
                    "status": "template_only",
                    "liveEnabled": _provider_configured(provider or service),
                    "created": False,
                }
            )
            continue
        conn, created = ProviderConnection.objects.get_or_create(
            workspace=workspace,
            provider=provider,
            defaults={
                "live_enabled": _provider_configured(provider),
                "status": "ready" if _provider_configured(provider) else "needs_platform_setup",
                "capabilities": meta["capabilities"],
            },
        )
        if not created and conn.live_enabled and not _provider_configured(provider):
            conflicts.append(
                {
                    "code": f"{provider}_was_live",
                    "message": f"{provider} was marked live but platform credentials are missing — status downgraded.",
                }
            )
            conn.live_enabled = False
            conn.status = "needs_platform_setup"
            conn.save(update_fields=["live_enabled", "status", "updated_at"])

        connections.append(
            {
                "provider": provider,
                "service": service,
                "status": conn.status,
                "liveEnabled": conn.live_enabled,
                "created": created,
            }
        )

    discovery = None
    migration_plan = None
    if run_discover and source_provider and app_identifier and not conflicts:
        from migrationengine import adapters, planner

        try:
            discovery = adapters.discover(source_provider, app_identifier)
            spec = discovery.get("spec") or {}
            spec["targetProvider"] = target_provider
            if spec.get("services"):
                spec["services"][0]["region"] = target_region
            spec.setdefault("metadata", {})["clientDomain"] = client_domain
            migration_plan = planner.generate_plan(spec)
        except Exception as exc:  # noqa: BLE001
            conflicts.append({"code": "discover_failed", "message": str(exc)})

    env_template = _client_env_template(client_domain, target_provider, target_region, services)

    checklist = _client_checklist(services, target_provider, conflicts, discovery)

    return {
        "ok": not any(c["code"] == "domain_in_use" for c in conflicts),
        "clientEmail": client_email,
        "workspace": {"id": workspace.id, "name": workspace.name, "ownerEmail": workspace.owner_email},
        "operatorEmail": operator_email,
        "clientDomain": client_domain,
        "targetProvider": target_provider,
        "targetRegion": target_region,
        "connections": connections,
        "conflicts": conflicts,
        "discoveryId": (discovery or {}).get("discoveryId"),
        "migrationPlan": migration_plan,
        "envTemplate": env_template,
        "checklist": checklist,
        "nextSteps": _client_next_steps(services, conflicts, discovery),
    }


def _provider_configured(provider: str) -> bool:
    checks = {
        "stripe": lambda: stripe_client.is_configured(),
        "paystack": lambda: paystack_client.is_configured(),
        "orena": lambda: bool(settings.ORENA_API_TOKEN),
        "railway": lambda: not _missing("RAILWAY_API_TOKEN", "RAILWAY_PROJECT_ID"),
        "render": lambda: not _missing("RENDER_API_TOKEN"),
        "fly": lambda: not _missing("FLY_API_TOKEN"),
        "supabase": lambda: not _missing("SUPABASE_ACCESS_TOKEN", "SUPABASE_ORG_ID"),
        "cloudflare": lambda: not _missing("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ZONE_ID"),
        "terraform": lambda: True,
    }
    return checks.get(provider, lambda: False)()


def _client_env_template(domain: str, provider: str, region: str, services: list[str]) -> dict[str, str]:
    template = {
        "NODE_ENV": "production",
        "PORT": "8080",
        "APP_DOMAIN": domain,
        "DEPLOY_REGION": region,
        "TARGET_PROVIDER": provider,
    }
    if "monitoring" in services:
        template["MONITORING_DSN"] = ""
    if "stripe" in services:
        template["STRIPE_SECRET_KEY"] = "[ENCRYPTED — client app billing]"
        template["STRIPE_WEBHOOK_SECRET"] = "[ENCRYPTED]"
    if "paystack" in services:
        template["PAYSTACK_SECRET_KEY"] = "[ENCRYPTED — client app billing]"
    return template


def _client_checklist(services: list[str], target: str, conflicts: list[dict], discovery: dict | None) -> list[dict[str, Any]]:
    items = [
        {"step": 1, "label": "Platform credentials verified", "done": audit_platform()["summary"]["needsAttention"] == 0},
        {"step": 2, "label": "Client workspace created", "done": True},
        {"step": 3, "label": "No domain conflicts", "done": not any(c["code"] == "domain_in_use" for c in conflicts)},
        {"step": 4, "label": f"Target provider ({target}) prewired", "done": target in services or target == DEFAULT_EAST_AFRICA_PROVIDER},
        {"step": 5, "label": "Discovery + migration plan generated", "done": bool(discovery)},
    ]
    return items


def _client_next_steps(services: list[str], conflicts: list[dict], discovery: dict | None) -> list[str]:
    steps = []
    if audit_platform()["summary"]["needsAttention"]:
        steps.append("Run Platform Setup auto-actions to finish server .env configuration.")
    if conflicts:
        steps.append("Resolve conflicts before deploying for this client.")
    if discovery:
        steps.append("Review migration plan → Apply → Deploy to target region.")
    else:
        steps.append("Connect source app (Account Review) or GitHub import, then Discover.")
    if "paystack" in services:
        steps.append("Confirm Paystack webhook is registered for this platform URL.")
    steps.append("Bind license to client domain after checkout completes.")
    return steps
