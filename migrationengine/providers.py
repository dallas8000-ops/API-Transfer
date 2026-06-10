"""Thin HTTP clients for real provider integrations.

Each function performs a real API call when its credential is configured. Tokens
are never logged. Callers are responsible for falling back to a simulated result
when a credential is absent (see deployments.stages).
"""
from __future__ import annotations

import time
from typing import Any

import requests
from django.conf import settings

TIMEOUT = 20
RAILWAY_TERMINAL_STATUSES = {"SUCCESS", "FAILED", "CRASHED", "REMOVED", "SKIPPED"}


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


def list_render_services(limit: int = 100) -> list[dict[str, Any]]:
    base = settings.RENDER_API_BASE_URL.rstrip("/")
    response = requests.get(
        f"{base}/v1/services",
        headers=_render_headers(),
        params={"limit": limit},
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise ProviderApiError("render", response.status_code, str(_json_or_text(response)))
    body = _json_or_text(response)
    services: list[dict[str, Any]] = []
    for item in body if isinstance(body, list) else body.get("services", []):
        service = item.get("service", item) if isinstance(item, dict) else {}
        if not isinstance(service, dict) or not service.get("id"):
            continue
        details = service.get("serviceDetails", {})
        services.append(
            {
                "id": service.get("id"),
                "name": service.get("name"),
                "type": service.get("type"),
                "branch": service.get("branch"),
                "repo": service.get("repo"),
                "region": details.get("region"),
                "runtime": details.get("runtime"),
                "buildCommand": details.get("buildCommand"),
                "startCommand": details.get("startCommand"),
                "url": details.get("url"),
            }
        )
    return services


def get_render_env_vars(service_id: str) -> dict[str, str]:
    base = settings.RENDER_API_BASE_URL.rstrip("/")
    response = requests.get(
        f"{base}/v1/services/{service_id}/env-vars",
        headers=_render_headers(),
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        raise ProviderApiError("render", response.status_code, str(_json_or_text(response)))
    body = _json_or_text(response)
    variables: dict[str, str] = {}
    for item in body if isinstance(body, list) else body.get("envVars", []):
        if not isinstance(item, dict):
            continue
        key = item.get("key") or item.get("envVar", {}).get("key")
        value = item.get("value") or item.get("envVar", {}).get("value")
        if key:
            variables[str(key)] = str(value or "")
    return variables


# --- Railway ----------------------------------------------------------------

def _railway_gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    if not settings.RAILWAY_API_TOKEN:
        raise ProviderApiError("railway", 401, "RAILWAY_API_TOKEN is not configured")
    endpoint = settings.RAILWAY_API_BASE_URL.rstrip("/")
    if "/graphql" not in endpoint:
        endpoint = f"{endpoint}/graphql/v2"
    headers = {
        "Authorization": f"Bearer {settings.RAILWAY_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": variables or {}}

    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=max(TIMEOUT, 60),
            )
        except requests.RequestException as exc:
            if attempt == max_attempts:
                raise ProviderApiError("railway", 502, str(exc)) from exc
            time.sleep(min(10, 2 ** attempt))
            continue

        if response.status_code == 200:
            body = _json_or_text(response)
            if isinstance(body, dict) and body.get("errors"):
                messages = "; ".join(str(error.get("message", "unknown")) for error in body["errors"])
                raise ProviderApiError("railway", 400, messages)
            return body.get("data", {}) if isinstance(body, dict) else {}

        raw_text = response.text or ""
        lower_text = raw_text.lower()
        is_transient = response.status_code in {403, 429, 500, 502, 503, 504}
        is_cloudflare_gate = "cloudflare" in lower_text or "attention required" in lower_text
        if attempt < max_attempts and (is_transient or is_cloudflare_gate):
            time.sleep(min(20, 2 ** attempt * 2))
            continue

        raise ProviderApiError("railway", response.status_code, str(_json_or_text(response)))

    raise ProviderApiError("railway", 502, "Railway GraphQL request failed after retries")


def _parse_github_repo(repo_url: str) -> str:
    url = repo_url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if prefix in url:
            return url.split(prefix, 1)[-1]
    if "/" in url and "://" not in url:
        return url
    raise ProviderApiError("railway", 400, "repoUrl must be a GitHub repository URL or org/repo slug")


def _railway_environment_id(project_id: str) -> str:
    data = _railway_gql(
        """
        query($id: String!) {
          project(id: $id) {
            environments { edges { node { id } } }
          }
        }
        """,
        {"id": project_id},
    )
    environment_id = (
        ((data.get("project") or {}).get("environments") or {}).get("edges") or [{}]
    )[0].get("node", {}).get("id")
    if not environment_id:
        raise ProviderApiError("railway", 404, "No environment found for Railway project")
    return environment_id


def deploy_railway_service(
    app_name: str,
    repo_url: str,
    branch: str,
    build_command: str | None,
    start_command: str | None,
    env: dict[str, str],
    root_directory: str | None = None,
    existing_service_id: str | None = None,
    trigger_deploy: bool = True,
) -> dict[str, Any]:
    if not settings.RAILWAY_PROJECT_ID:
        raise ProviderApiError("railway", 400, "RAILWAY_PROJECT_ID is required")
    if not repo_url:
        raise ProviderApiError("railway", 400, "repoUrl is required for live Railway deploys")

    project_id = settings.RAILWAY_PROJECT_ID
    repo = _parse_github_repo(repo_url)
    environment_id = _railway_environment_id(project_id)

    service_id = existing_service_id
    if not service_id:
        create_data = _railway_gql(
            """
            mutation($input: ServiceCreateInput!) {
              serviceCreate(input: $input) { id }
            }
            """,
            {"input": {"projectId": project_id, "name": app_name}},
        )
        service_id = (create_data.get("serviceCreate") or {}).get("id")
        if not service_id:
            raise ProviderApiError("railway", 500, "Railway response did not include a service id")

    _railway_gql(
        """
        mutation($id: String!, $input: ServiceConnectInput!) {
          serviceConnect(id: $id, input: $input) { id }
        }
        """,
        {"id": service_id, "input": {"repo": repo, "branch": branch or "main"}},
    )

    instance_input: dict[str, Any] = {}
    if build_command:
        instance_input["buildCommand"] = build_command
    if start_command:
        instance_input["startCommand"] = start_command
    if root_directory:
        instance_input["rootDirectory"] = root_directory
    if instance_input:
        _railway_gql(
            """
            mutation($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
              serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input)
            }
            """,
            {"serviceId": service_id, "environmentId": environment_id, "input": instance_input},
        )

    if env:
        _railway_gql(
            """
            mutation($input: VariableCollectionUpsertInput!) {
              variableCollectionUpsert(input: $input)
            }
            """,
            {
                "input": {
                    "projectId": project_id,
                    "serviceId": service_id,
                    "environmentId": environment_id,
                    "variables": env,
                }
            },
        )

        deploy_id: str | None = None
        if trigger_deploy:
                deploy_data = _railway_gql(
                        """
                        mutation($serviceId: String!, $environmentId: String!) {
                            serviceInstanceDeployV2(serviceId: $serviceId, environmentId: $environmentId)
                        }
                        """,
                        {"serviceId": service_id, "environmentId": environment_id},
                )
                deploy_id = deploy_data.get("serviceInstanceDeployV2")
                if not deploy_id:
                        latest = _railway_latest_deployment(project_id, service_id, environment_id)
                        deploy_id = latest.get("id") if latest else None

    hostname = f"{app_name}.up.railway.app"
    try:
        domain_data = _railway_gql(
            """
            mutation($input: ServiceDomainCreateInput!) {
              serviceDomainCreate(input: $input) { domain }
            }
            """,
            {"input": {"serviceId": service_id, "environmentId": environment_id}},
        )
        hostname = (domain_data.get("serviceDomainCreate") or {}).get("domain") or hostname
    except ProviderApiError:
        pass

    return {
        "serviceId": service_id,
        "deployId": deploy_id,
        "environmentId": environment_id,
        "hostname": hostname,
        "dashboardUrl": f"https://railway.app/project/{project_id}/service/{service_id}",
        "live": True,
    }


def _railway_latest_deployment(project_id: str, service_id: str, environment_id: str) -> dict[str, Any] | None:
    data = _railway_gql(
        """
        query($input: DeploymentListInput!) {
          deployments(input: $input, first: 1) {
            edges { node { id status createdAt updatedAt } }
          }
        }
        """,
        {"input": {"projectId": project_id, "serviceId": service_id, "environmentId": environment_id}},
    )
    edges = ((data.get("deployments") or {}).get("edges") or [])
    if not edges:
        return None
    node = edges[0].get("node") or {}
    return {
        "id": node.get("id"),
        "status": node.get("status"),
        "createdAt": node.get("createdAt"),
        "updatedAt": node.get("updatedAt"),
    }


def get_railway_latest_service_deployment(project_id: str, service_id: str) -> dict[str, Any] | None:
    environment_id = _railway_environment_id(project_id)
    return _railway_latest_deployment(project_id, service_id, environment_id)


def list_railway_services(project_id: str | None = None) -> list[dict[str, Any]]:
    project_id = project_id or settings.RAILWAY_PROJECT_ID
    if not project_id:
        raise ProviderApiError("railway", 400, "RAILWAY_PROJECT_ID is required")
    environment_id = _railway_environment_id(project_id)
    data = _railway_gql(
        """
        query($id: String!) {
          project(id: $id) {
            services {
              edges {
                node {
                  id
                  name
                }
              }
            }
          }
        }
        """,
        {"id": project_id},
    )
    services: list[dict[str, Any]] = []
    for edge in ((data.get("project") or {}).get("services") or {}).get("edges", []):
        node = edge.get("node") or {}
        if not node.get("id"):
            continue
        instance = get_railway_service_instance(node["id"], environment_id)
        services.append(
            {
                "id": node.get("id"),
                "name": node.get("name"),
                                "branch": None,
                                "repo": None,
                "environmentId": environment_id,
                "projectId": project_id,
                **instance,
            }
        )
    return services


def get_railway_service_id_by_name(project_id: str, name: str) -> str | None:
        data = _railway_gql(
                """
                query($id: String!) {
                    project(id: $id) {
                        services {
                            edges {
                                node {
                                    id
                                    name
                                }
                            }
                        }
                    }
                }
                """,
                {"id": project_id},
        )
        target = name.strip().lower()
        for edge in ((data.get("project") or {}).get("services") or {}).get("edges", []):
                node = edge.get("node") or {}
                node_name = str(node.get("name") or "").strip().lower()
                node_id = str(node.get("id") or "").strip()
                if node_id and node_name == target:
                        return node_id
        return None


def get_railway_service_instance(service_id: str, environment_id: str) -> dict[str, Any]:
    data = _railway_gql(
        """
        query($serviceId: String!, $environmentId: String!) {
          serviceInstance(serviceId: $serviceId, environmentId: $environmentId) {
            buildCommand
            startCommand
            rootDirectory
          }
        }
        """,
        {"serviceId": service_id, "environmentId": environment_id},
    )
    instance = data.get("serviceInstance") or {}
    return {
        "buildCommand": instance.get("buildCommand"),
        "startCommand": instance.get("startCommand"),
        "rootDirectory": instance.get("rootDirectory"),
    }


def get_railway_env_vars(project_id: str, service_id: str, environment_id: str) -> dict[str, str]:
    data = _railway_gql(
        """
        query($projectId: String!, $environmentId: String!, $serviceId: String!) {
          variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId)
        }
        """,
        {"projectId": project_id, "environmentId": environment_id, "serviceId": service_id},
    )
    variables = data.get("variables") or {}
    if not isinstance(variables, dict):
        return {}
    return {str(key): str(value) for key, value in variables.items()}


def get_railway_deployment(deployment_id: str) -> dict[str, Any]:
    data = _railway_gql(
        """
        query($id: String!) {
                    deployment(id: $id) { id status createdAt updatedAt diagnosis staticUrl url }
        }
        """,
        {"id": deployment_id},
    )
    body = data.get("deployment") or {}
    return {
        "id": body.get("id") or deployment_id,
        "status": body.get("status") or "unknown",
        "createdAt": body.get("createdAt"),
        "updatedAt": body.get("updatedAt"),
        "diagnosis": body.get("diagnosis"),
        "staticUrl": body.get("staticUrl"),
        "url": body.get("url"),
        "raw": body,
    }


def wait_for_railway_deployment(
    deployment_id: str,
    timeout_seconds: int = 180,
    poll_interval_seconds: int = 10,
) -> dict[str, Any]:
    deadline = time.time() + max(0, timeout_seconds)
    last: dict[str, Any] | None = None

    while True:
        last = get_railway_deployment(deployment_id)
        status = str(last.get("status") or "").upper()
        if status in RAILWAY_TERMINAL_STATUSES:
            break
        if time.time() >= deadline:
            break
        time.sleep(max(1, poll_interval_seconds))

    return {
        **(last or {"id": deployment_id, "status": "unknown"}),
        "terminal": str((last or {}).get("status") or "").upper() in RAILWAY_TERMINAL_STATUSES,
        "timedOut": str((last or {}).get("status") or "").upper() not in RAILWAY_TERMINAL_STATUSES,
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
