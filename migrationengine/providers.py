"""Thin HTTP clients for real provider integrations.

Each function performs a real API call when its credential is configured. Tokens
are never logged. Callers are responsible for falling back to a simulated result
when a credential is absent (see deployments.stages).
"""
from __future__ import annotations

from typing import Any

import requests
from django.conf import settings

TIMEOUT = 20


class ProviderApiError(RuntimeError):
    def __init__(self, provider: str, status_code: int, message: str) -> None:
        super().__init__(f"{provider} API error ({status_code}): {message}")
        self.provider = provider
        self.status_code = status_code


def _json_or_text(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:500]}


# --- Fly.io ----------------------------------------------------------------

def deploy_fly_app(app_name: str, image: str, env: dict[str, str]) -> dict[str, Any]:
    base = settings.FLY_API_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.FLY_API_TOKEN}", "Content-Type": "application/json"}

    create = requests.post(
        f"{base}/v1/apps",
        headers=headers,
        json={"app_name": app_name, "org_slug": settings.FLY_ORG_SLUG},
        timeout=TIMEOUT,
    )
    if create.status_code not in (200, 201, 409, 422):
        raise ProviderApiError("fly", create.status_code, str(_json_or_text(create)))

    machine = requests.post(
        f"{base}/v1/apps/{app_name}/machines",
        headers=headers,
        json={
            "config": {
                "image": image,
                "env": env,
                "services": [
                    {"ports": [{"port": 443, "handlers": ["tls", "http"]}, {"port": 80, "handlers": ["http"]}], "protocol": "tcp", "internal_port": 8080}
                ],
            }
        },
        timeout=TIMEOUT,
    )
    if machine.status_code not in (200, 201):
        raise ProviderApiError("fly", machine.status_code, str(_json_or_text(machine)))

    body = _json_or_text(machine)
    return {"hostname": f"{app_name}.fly.dev", "machineId": body.get("id"), "live": True}


# --- Render ----------------------------------------------------------------

def _render_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.RENDER_API_TOKEN}",
        "Content-Type": "application/json",
    }


def deploy_render_web_service(
    app_name: str,
    repo_url: str,
    branch: str,
    build_command: str | None,
    start_command: str | None,
    env: dict[str, str],
    region: str | None = None,
) -> dict[str, Any]:
    if not settings.RENDER_OWNER_ID:
        raise ProviderApiError("render", 400, "RENDER_OWNER_ID is required")
    if not repo_url:
        raise ProviderApiError("render", 400, "repoUrl is required for live Render deploys")

    base = settings.RENDER_API_BASE_URL.rstrip("/")
    payload = {
        "type": "web_service",
        "name": app_name,
        "ownerId": settings.RENDER_OWNER_ID,
        "repo": repo_url,
        "branch": branch or "main",
        "serviceDetails": {
            "runtime": "node",
            "plan": settings.RENDER_DEFAULT_PLAN,
            "region": region or settings.RENDER_DEFAULT_REGION,
            "buildCommand": build_command or "npm install",
            "startCommand": start_command or "npm start",
        },
    }
    create = requests.post(f"{base}/v1/services", headers=_render_headers(), json=payload, timeout=TIMEOUT)
    if create.status_code not in (200, 201):
        raise ProviderApiError("render", create.status_code, str(_json_or_text(create)))
    service = _json_or_text(create)
    service_id = service.get("id") or service.get("service", {}).get("id")
    if not service_id:
        raise ProviderApiError("render", 500, "Render response did not include a service id")

    if env:
        env_payload = [{"key": key, "value": value} for key, value in sorted(env.items())]
        env_response = requests.put(
            f"{base}/v1/services/{service_id}/env-vars",
            headers=_render_headers(),
            json=env_payload,
            timeout=TIMEOUT,
        )
        if env_response.status_code not in (200, 201):
            raise ProviderApiError("render", env_response.status_code, str(_json_or_text(env_response)))

    deploy_response = requests.post(
        f"{base}/v1/services/{service_id}/deploys",
        headers=_render_headers(),
        json={"clearCache": "do_not_clear"},
        timeout=TIMEOUT,
    )
    if deploy_response.status_code not in (200, 201, 202):
        raise ProviderApiError("render", deploy_response.status_code, str(_json_or_text(deploy_response)))
    deploy = _json_or_text(deploy_response)

    hostname = (
        service.get("serviceDetails", {}).get("url")
        or service.get("url")
        or service.get("dashboardUrl", "").replace("dashboard.render.com", "onrender.com")
        or f"{app_name}.onrender.com"
    )
    hostname = str(hostname).replace("https://", "").replace("http://", "").strip("/")
    return {
        "serviceId": service_id,
        "deployId": deploy.get("id"),
        "hostname": hostname,
        "dashboardUrl": service.get("dashboardUrl"),
        "live": True,
    }


def get_render_deploy(service_id: str, deploy_id: str) -> dict[str, Any]:
    base = settings.RENDER_API_BASE_URL.rstrip("/")
    response = requests.get(
        f"{base}/v1/services/{service_id}/deploys/{deploy_id}",
        headers=_render_headers(),
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise ProviderApiError("render", response.status_code, str(_json_or_text(response)))
    body = _json_or_text(response)
    return {
        "id": body.get("id") or deploy_id,
        "status": body.get("status") or "unknown",
        "commit": body.get("commit"),
        "createdAt": body.get("createdAt"),
        "updatedAt": body.get("updatedAt"),
        "finishedAt": body.get("finishedAt"),
        "raw": body,
    }


# --- Supabase --------------------------------------------------------------

def provision_supabase_database(name: str, db_pass: str) -> dict[str, Any]:
    base = settings.SUPABASE_API_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.SUPABASE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    response = requests.post(
        f"{base}/v1/projects",
        headers=headers,
        json={
            "name": name,
            "organization_id": settings.SUPABASE_ORG_ID,
            "region": settings.SUPABASE_DEFAULT_REGION,
            "db_pass": db_pass,
            "plan": "free",
        },
        timeout=TIMEOUT,
    )
    if response.status_code not in (200, 201):
        raise ProviderApiError("supabase", response.status_code, str(_json_or_text(response)))
    body = _json_or_text(response)
    ref = body.get("id") or body.get("ref")
    return {
        "projectRef": ref,
        "region": settings.SUPABASE_DEFAULT_REGION,
        "host": f"db.{ref}.supabase.co" if ref else None,
        "live": True,
    }


# --- Stripe ----------------------------------------------------------------

def _stripe_post(path: str, data: dict[str, Any]) -> dict[str, Any]:
    base = settings.STRIPE_API_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"}
    response = requests.post(f"{base}{path}", headers=headers, data=data, timeout=TIMEOUT)
    if response.status_code not in (200, 201):
        raise ProviderApiError("stripe", response.status_code, str(_json_or_text(response)))
    return _json_or_text(response)


def setup_stripe(product_name: str, webhook_url: str) -> dict[str, Any]:
    product = _stripe_post("/v1/products", {"name": product_name})
    price = _stripe_post(
        "/v1/prices",
        {"product": product["id"], "unit_amount": 1000, "currency": "usd", "recurring[interval]": "month"},
    )
    webhook = _stripe_post(
        "/v1/webhook_endpoints",
        {
            "url": webhook_url,
            "enabled_events[]": "checkout.session.completed",
        },
    )
    return {
        "productId": product["id"],
        "priceId": price["id"],
        "webhookSecret": webhook.get("secret"),
        "live": True,
    }


# --- Cloudflare ------------------------------------------------------------

def create_dns_record(name: str, content: str) -> dict[str, Any]:
    if not settings.CLOUDFLARE_ZONE_ID:
        raise ProviderApiError("cloudflare", 400, "CLOUDFLARE_ZONE_ID is required")
    base = settings.CLOUDFLARE_API_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"}
    response = requests.post(
        f"{base}/zones/{settings.CLOUDFLARE_ZONE_ID}/dns_records",
        headers=headers,
        json={"type": "A", "name": name, "content": content, "proxied": True, "ttl": 1},
        timeout=TIMEOUT,
    )
    if response.status_code not in (200, 201):
        raise ProviderApiError("cloudflare", response.status_code, str(_json_or_text(response)))
    body = _json_or_text(response)
    result = body.get("result", {})
    return {"recordId": result.get("id"), "proxied": result.get("proxied", True), "live": True}
