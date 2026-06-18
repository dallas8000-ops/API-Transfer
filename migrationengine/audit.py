"""Tamper-evident audit log backed by a hash chain.

Each entry's hash incorporates the previous entry's hash, so any modification or
deletion breaks the chain and is detectable by `verify_chain`.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction

from core.integrity import integrity_hash
from core.redaction import redact_sensitive_values

from .models import AuditEntry

VALID_ACTIONS = {
    "plan",
    "apply",
    "rollback",
    "verify",
    "discover",
    "status",
    "env_inject",
    "railway_env_backup",
    "platform_setup",
    "client_prewire",
}


def record_audit(action: str, actor: str, payload: dict[str, Any], reference: str = "") -> dict[str, Any]:
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unknown audit action: {action}")

    safe_payload = redact_sensitive_values(payload)
    with transaction.atomic():
        last = AuditEntry.objects.select_for_update().order_by("-sequence").first()
        sequence = (last.sequence + 1) if last else 1
        previous_hash = last.entry_hash if last else ""
        entry_hash = integrity_hash(
            {
                "sequence": sequence,
                "action": action,
                "actor": actor,
                "reference": reference,
                "payload": safe_payload,
                "previousHash": previous_hash,
            }
        )
        entry = AuditEntry.objects.create(
            sequence=sequence,
            action=action,
            actor=actor,
            reference=reference,
            payload=safe_payload,
            previous_hash=previous_hash,
            entry_hash=entry_hash,
        )
    return entry.to_dict()


def list_audit() -> list[dict[str, Any]]:
    return [entry.to_dict() for entry in AuditEntry.objects.all()]


def verify_chain() -> dict[str, Any]:
    previous_hash = ""
    for entry in AuditEntry.objects.all():
        expected = integrity_hash(
            {
                "sequence": entry.sequence,
                "action": entry.action,
                "actor": entry.actor,
                "reference": entry.reference,
                "payload": entry.payload,
                "previousHash": previous_hash,
            }
        )
        if expected != entry.entry_hash or entry.previous_hash != previous_hash:
            return {"valid": False, "brokenAt": entry.sequence}
        previous_hash = entry.entry_hash
    return {"valid": True, "brokenAt": None}
