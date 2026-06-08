from __future__ import annotations

from django.db import models
from django.utils import timezone


class License(models.Model):
    STATUS_CHOICES = [
        ("active", "active"),
        ("revoked", "revoked"),
        ("expired", "expired"),
    ]

    customer = models.ForeignKey("billing.Customer", on_delete=models.CASCADE, related_name="licenses")
    subscription = models.OneToOneField(
        "billing.Subscription", on_delete=models.CASCADE, related_name="license", null=True, blank=True
    )
    key_hash = models.CharField(max_length=64, unique=True)
    key_last4 = models.CharField(max_length=4)
    registered_domain = models.CharField(max_length=255)
    max_instances = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["registered_domain"]),
        ]

    @property
    def is_valid_now(self) -> bool:
        if self.status != "active":
            return False
        return self.expires_at is None or self.expires_at > timezone.now()


class LicenseInstance(models.Model):
    license = models.ForeignKey(License, on_delete=models.CASCADE, related_name="instances")
    instance_id = models.CharField(max_length=255)
    domain = models.CharField(max_length=255)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("license", "instance_id")]
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["license", "is_active"]),
            models.Index(fields=["instance_id"]),
        ]
