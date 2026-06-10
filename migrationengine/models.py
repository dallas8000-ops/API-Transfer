from datetime import timedelta

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


class TransferRun(models.Model):
    """Persisted transfer control state for Railway migration runs."""

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_RETRYABLE = "retryable"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    STATUS_DEAD_LETTER = "dead_letter"
    STATUS_STOPPED = "stopped"
    STATUS_PENDING = "pending"

    STEP_QUEUED = "queued"
    STEP_STARTING = "starting"
    STEP_TRANSFER = "transfer"
    STEP_VERIFY = "verify"
    STEP_FINALIZE = "finalize"

    run_id = models.CharField(max_length=64, unique=True, db_index=True)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="transfer_runs", null=True, blank=True
    )
    mode = models.CharField(max_length=16, default="queue")
    requested_by = models.CharField(max_length=128, default="")
    status = models.CharField(max_length=32, default="pending")
    command = models.JSONField(default=list)
    options = models.JSONField(default=dict)
    step = models.CharField(max_length=32, default=STEP_QUEUED)
    step_state = models.JSONField(default=dict)
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    attempt_started_at = models.DateTimeField(null=True, blank=True)
    lease_owner = models.CharField(max_length=64, blank=True, default="")
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    log_path = models.CharField(max_length=260, blank=True, default="")
    exit_code = models.IntegerField(null=True, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def to_dict(self) -> dict:
        return {
            "id": self.run_id,
            "mode": self.mode,
            "requestedBy": self.requested_by,
            "status": self.status,
            "command": self.command,
            "options": self.options,
            "step": self.step,
            "stepState": self.step_state,
            "retryCount": self.retry_count,
            "maxRetries": self.max_retries,
            "nextRetryAt": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "lastError": self.last_error,
            "attemptStartedAt": self.attempt_started_at.isoformat() if self.attempt_started_at else None,
            "leaseOwner": self.lease_owner,
            "leaseExpiresAt": self.lease_expires_at.isoformat() if self.lease_expires_at else None,
            "heartbeatAt": self.heartbeat_at.isoformat() if self.heartbeat_at else None,
            "logPath": self.log_path,
            "exitCode": self.exit_code,
            "startedAt": self.started_at.isoformat() if self.started_at else None,
            "finishedAt": self.finished_at.isoformat() if self.finished_at else None,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }

    def mark_step(self, step: str, status: str | None = None, details: dict | None = None) -> None:
        payload = dict(self.step_state or {})
        payload[step] = {
            "updatedAt": timezone.now().isoformat(),
            "details": details or {},
        }
        self.step = step
        self.step_state = payload
        if status:
            self.status = status
        self.save(update_fields=["step", "step_state", "status", "updated_at"])

    def schedule_retry(self, error: str, delay_seconds: int = 60) -> None:
        self.retry_count += 1
        self.last_error = error
        self.lease_owner = ""
        self.lease_expires_at = None
        self.heartbeat_at = None
        if self.retry_count > self.max_retries:
            self.status = self.STATUS_FAILED
            self.finished_at = timezone.now()
            self.next_retry_at = None
        else:
            self.status = self.STATUS_RETRYABLE
            self.next_retry_at = timezone.now() + timedelta(seconds=max(1, delay_seconds))
        self.save(
            update_fields=[
                "retry_count",
                "last_error",
                "status",
                "next_retry_at",
                "finished_at",
                "lease_owner",
                "lease_expires_at",
                "heartbeat_at",
                "updated_at",
            ]
        )

    def acquire_lease(self, owner: str, lease_seconds: int) -> None:
        now = timezone.now()
        self.lease_owner = owner
        self.lease_expires_at = now + timedelta(seconds=max(1, lease_seconds))
        self.heartbeat_at = now
        self.save(update_fields=["lease_owner", "lease_expires_at", "heartbeat_at", "updated_at"])

    def heartbeat(self, lease_seconds: int) -> None:
        now = timezone.now()
        self.heartbeat_at = now
        self.lease_expires_at = now + timedelta(seconds=max(1, lease_seconds))
        self.save(update_fields=["heartbeat_at", "lease_expires_at", "updated_at"])

    def release_lease(self) -> None:
        self.lease_owner = ""
        self.lease_expires_at = None
        self.heartbeat_at = None
        self.save(update_fields=["lease_owner", "lease_expires_at", "heartbeat_at", "updated_at"])
