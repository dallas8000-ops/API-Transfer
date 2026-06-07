"""Deterministic Terraform plan/apply over a canonical migration spec.

Produces sorted HCL and a desired-resource set, computes drift against a supplied
current state, and simulates an apply by emitting remediation steps. Pure and
side-effect free so the same spec always yields the same plan and integrity hash.
"""
from __future__ import annotations

from typing import Any

from core.integrity import integrity_hash


def build_desired_resources(spec: dict[str, Any]) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for service in spec.get("services", []):
        resources.append(
            {
                "type": "app_service",
                "name": service["name"],
                "attributes": {
                    "runtime": service.get("runtime", "node"),
                    "region": service.get("region", "us-east-1"),
                    "replicas": service.get("replicas", 1),
                    "startCommand": service.get("startCommand", ""),
                },
            }
        )
    for database in spec.get("databases", []):
        resources.append(
            {
                "type": "database",
                "name": database["name"],
                "attributes": {"engine": database["engine"], "version": database.get("version", "latest")},
            }
        )
    for domain in spec.get("domains", []):
        resources.append(
            {
                "type": "domain",
                "name": domain["host"],
                "attributes": {"tlsRequired": domain.get("tlsRequired", True)},
            }
        )
    return sorted(resources, key=lambda r: (r["type"], r["name"]))


def compute_drift(desired: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_index = {(r.get("type"), r.get("name")): r for r in current}
    desired_index = {(r["type"], r["name"]): r for r in desired}
    drift: list[dict[str, Any]] = []

    for key, resource in desired_index.items():
        existing = current_index.get(key)
        if existing is None:
            drift.append({"kind": "create", "type": key[0], "name": key[1]})
        elif existing.get("attributes") != resource["attributes"]:
            drift.append({"kind": "update", "type": key[0], "name": key[1]})

    for key in current_index:
        if key not in desired_index:
            drift.append({"kind": "delete", "type": key[0], "name": key[1]})

    return sorted(drift, key=lambda d: (d["kind"], d["type"], d["name"]))


def _hcl_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return f'"{value}"'


def generate_hcl(resources: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for resource in resources:
        lines = [f'resource "{resource["type"]}" "{resource["name"]}" {{']
        for key in sorted(resource["attributes"].keys()):
            lines.append(f"  {key} = {_hcl_value(resource['attributes'][key])}")
        lines.append("}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def create_plan(plan_id: str, spec: dict[str, Any], current_state: list[dict[str, Any]]) -> dict[str, Any]:
    desired = build_desired_resources(spec)
    drift = compute_drift(desired, current_state)
    hcl = generate_hcl(desired)
    summary = (
        f"{sum(1 for d in drift if d['kind'] == 'create')} to create, "
        f"{sum(1 for d in drift if d['kind'] == 'update')} to update, "
        f"{sum(1 for d in drift if d['kind'] == 'delete')} to delete"
    )
    plan = {
        "planId": plan_id,
        "summary": summary,
        "resources": desired,
        "drift": drift,
        "hcl": hcl,
    }
    plan["integrityHash"] = integrity_hash(plan)
    return plan


def apply_plan(plan: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for change in plan.get("drift", []):
        verb = {"create": "Creating", "update": "Updating", "delete": "Destroying"}[change["kind"]]
        steps.append(f"{verb} {change['type']} '{change['name']}'")
    return {"planId": plan["planId"], "steps": steps, "applied": len(steps)}
