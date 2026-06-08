from django.db import models
from django.utils import timezone

from billing.models import Workspace


class AuditEntry(models.Model):
    """Tamper-evident audit record. Each row chains to the previous via a
    SHA-256 hash so the full log can be verified for integrity."""

    sequence = models.PositiveIntegerField(unique=True, db_index=True)
    action = models.CharField(max_length=32)
    actor = models.CharField(max_length=128)
    reference = models.CharField(max_length=128, blank=True, default="")
    payload = models.JSONField(default=dict)
    previous_hash = models.CharField(max_length=64, blank=True, default="")
    entry_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "action": self.action,
            "actor": self.actor,
            "reference": self.reference,
            "payload": self.payload,
            "previousHash": self.previous_hash,
            "entryHash": self.entry_hash,
            "createdAt": self.created_at.isoformat(),
        }


class DeploymentRun(models.Model):
    """Persisted deployment history for client-facing status and support."""

    deployment_id = models.CharField(max_length=64, unique=True, db_index=True)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="deployment_runs", null=True, blank=True
    )
    app_name = models.CharField(max_length=128)
    target_provider = models.CharField(max_length=32)
    requested_by = models.CharField(max_length=128)
    live = models.BooleanField(default=False)
    succeeded = models.BooleanField(default=False)
    status = models.CharField(max_length=32, default="unknown")
    provider_service_id = models.CharField(max_length=128, blank=True, default="")
    provider_deploy_id = models.CharField(max_length=128, blank=True, default="")
    provider_status = models.JSONField(default=dict)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    live_url = models.URLField(blank=True, default="")
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def to_dict(self) -> dict:
        return {
            "deploymentId": self.deployment_id,
            "appName": self.app_name,
            "targetProvider": self.target_provider,
            "requestedBy": self.requested_by,
            "live": self.live,
            "succeeded": self.succeeded,
            "status": self.status,
            "providerServiceId": self.provider_service_id,
            "providerDeployId": self.provider_deploy_id,
            "providerStatus": self.provider_status,
            "lastCheckedAt": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "liveUrl": self.live_url,
            "createdAt": self.created_at.isoformat(),
        }

    def mark_status(self, status: str, provider_status: dict) -> None:
        self.status = status
        self.provider_status = provider_status
        self.last_checked_at = timezone.now()
        self.succeeded = status in {"live", "succeeded"}
        self.save(update_fields=["status", "provider_status", "last_checked_at", "succeeded"])
