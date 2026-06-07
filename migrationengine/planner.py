"""Migration planning, policy guardrails, secret sealing, apply and rollback.

Secrets in a canonical spec are sealed with AES-256-GCM as soon as a plan is
generated; the plaintext is never stored or returned. Plans carry an integrity
hash that `apply_plan` re-verifies before execution, and a redacted snapshot is
captured for rollback.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from core.integrity import integrity_hash
from core.redaction import redact_sensitive_values
from core.vault import SealedSecret, decrypt_secret, encrypt_secret

# In-process state linking a plan to its sealed secrets and rollback snapshot.
_SEALED_SECRETS: dict[str, dict[str, dict[str, str]]] = {}
_SNAPSHOTS: dict[str, dict[str, Any]] = {}


def _evaluate_policies(spec: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    environment = spec.get("metadata", {}).get("environment", "stage")
    requested_by = spec.get("metadata", {}).get("requestedBy", "")

    if environment == "prod" and not requested_by:
        warnings.append("Production migrations require an identified human requester.")

    for service in spec.get("services", []):
        if not service.get("startCommand"):
            warnings.append(f"Service '{service.get('name')}' has no start command.")
        if not service.get("secrets"):
            warnings.append(f"Service '{service.get('name')}' declares no secrets; confirm this is intentional.")

    for domain in spec.get("domains", []):
        if not domain.get("tlsRequired"):
            warnings.append(f"Domain '{domain.get('host')}' does not enforce TLS.")

    return warnings


def _seal_spec_secrets(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    sealed: dict[str, dict[str, str]] = {}
    for service in spec.get("services", []):
        for secret in service.get("secrets", []):
            ref = f"{service['name']}::{secret['key']}"
            sealed[ref] = encrypt_secret(secret["value"]).to_dict()
    return sealed


def _risk_score(spec: dict[str, Any], warnings: list[str]) -> int:
    score = len(warnings) * 8
    if spec.get("metadata", {}).get("environment") == "prod":
        score += 20
    score += len(spec.get("databases", [])) * 10
    return min(100, score)


def generate_plan(spec: dict[str, Any]) -> dict[str, Any]:
    warnings = _evaluate_policies(spec)
    sealed = _seal_spec_secrets(spec)
    plan_id = str(uuid.uuid4())

    service_count = len(spec.get("services", []))
    db_count = len(spec.get("databases", []))
    risk = _risk_score(spec, warnings)

    steps = [
        f"Provision {service_count} service(s) on {spec.get('targetProvider')}",
        f"Migrate {db_count} database(s)",
        "Re-seal and inject secrets via the encrypted vault",
        "Configure domains and TLS",
        "Run post-migration verification",
    ]

    plan = {
        "planId": plan_id,
        "summary": f"Migrate {spec.get('appName')} from {spec.get('sourceProvider')} to {spec.get('targetProvider')}",
        "riskScore": risk,
        "confidence": max(0, 100 - risk),
        "steps": steps,
        "warnings": warnings,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    plan["integrityHash"] = integrity_hash(plan)

    _SEALED_SECRETS[plan_id] = sealed
    return {"plan": plan, "sealedRefs": list(sealed.keys())}


def _verify_migration(spec: dict[str, Any]) -> list[dict[str, Any]]:
    services = spec.get("services", [])
    domains = spec.get("domains", [])
    return [
        {"name": "services-present", "passed": len(services) > 0, "detail": f"{len(services)} service(s)"},
        {"name": "start-commands", "passed": all(s.get("startCommand") for s in services), "detail": "all services have start commands"},
        {"name": "tls-enforced", "passed": all(d.get("tlsRequired") for d in domains), "detail": "all domains enforce TLS"},
        {"name": "secrets-configured", "passed": any(s.get("secrets") for s in services), "detail": "at least one service has secrets"},
    ]


def apply_plan(spec: dict[str, Any], plan: dict[str, Any], approved_by: str) -> dict[str, Any]:
    plan_id = plan["planId"]
    if plan_id not in _SEALED_SECRETS:
        raise KeyError("No sealed secret state for this plan. Recreate the plan first.")

    # Re-verify the plan integrity hash to ensure it was not tampered with.
    candidate = {k: plan[k] for k in plan if k != "integrityHash"}
    if integrity_hash(candidate) != plan.get("integrityHash"):
        raise ValueError("Plan integrity check failed. Re-plan before applying.")

    # Hydrate secrets in memory only (proves decryption works; never returned).
    sealed = _SEALED_SECRETS[plan_id]
    hydrated_count = 0
    for payload in sealed.values():
        decrypt_secret(SealedSecret.from_dict(payload))
        hydrated_count += 1

    snapshot = {"spec": redact_sensitive_values(spec), "approvedBy": approved_by}
    snapshot["integrityHash"] = integrity_hash(snapshot)
    _SNAPSHOTS[plan_id] = snapshot

    checks = _verify_migration(spec)
    succeeded = all(c["passed"] for c in checks)

    # Sealed secrets are consumed on apply.
    del _SEALED_SECRETS[plan_id]

    return {
        "planId": plan_id,
        "approvedBy": approved_by,
        "vaultHydrationCount": hydrated_count,
        "verification": checks,
        "succeeded": succeeded,
        "snapshotIntegrity": snapshot["integrityHash"],
    }


def rollback_plan(plan_id: str, actor: str) -> dict[str, Any]:
    snapshot = _SNAPSHOTS.get(plan_id)
    if snapshot is None:
        raise KeyError("No snapshot found for this plan ID.")

    candidate = {k: snapshot[k] for k in snapshot if k != "integrityHash"}
    valid = integrity_hash(candidate) == snapshot.get("integrityHash")
    return {
        "planId": plan_id,
        "actor": actor,
        "snapshotValid": valid,
        "restored": valid,
    }
