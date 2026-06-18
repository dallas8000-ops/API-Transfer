"""Query-aware stand-in for migrationengine.providers._railway_gql in deploy tests."""
from __future__ import annotations

from typing import Any


def railway_gql_test_router(
    query: str,
    variables: dict[str, Any] | None = None,
    *,
    deploy_payload: str | dict[str, str] = "dep_123",
    hostname: str = "demo.up.railway.app",
) -> dict[str, Any]:
    normalized = " ".join(query.split())

    if "project(id:" in normalized and "environments" in normalized:
        return {"project": {"environments": {"edges": [{"node": {"id": "env_123"}}]}}}
    if "serviceCreate" in normalized:
        return {"serviceCreate": {"id": "svc_123"}}
    if "serviceConnect" in normalized:
        return {"serviceConnect": {"id": "svc_123"}}
    if "serviceInstanceUpdate" in normalized:
        return {}
    if "variables(" in normalized:
        return {"variables": {}}
    if "variableCollectionUpsert" in normalized:
        return {}
    if "serviceInstanceDeployV2" in normalized:
        return {"serviceInstanceDeployV2": deploy_payload}
    if "serviceDomainCreate" in normalized:
        return {"serviceDomainCreate": {"domain": hostname}}
    if "deployments(" in normalized:
        return {"deployments": {"edges": []}}
    if "deployment(" in normalized:
        return {"deployment": {"id": "dep_123", "status": "SUCCESS", "updatedAt": "2026-06-07T17:00:00Z"}}
    return {}
