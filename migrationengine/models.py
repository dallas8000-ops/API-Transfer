from django.db import models


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
