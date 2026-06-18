from __future__ import annotations

from django.db import models
from django.utils import timezone


class Workspace(models.Model):
    """A customer-owned workspace for client teams and agencies."""

    name = models.CharField(max_length=120)
    owner_email = models.EmailField(db_index=True)
    plan_slug = models.CharField(max_length=50, default="free")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover - admin/debug convenience
        return self.name


class WorkspaceMember(models.Model):
    ROLE_CHOICES = [
        ("owner", "owner"),
        ("admin", "admin"),
        ("operator", "operator"),
        ("viewer", "viewer"),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="members")
    email = models.EmailField()
    role = models.CharField(max_length=32, choices=ROLE_CHOICES, default="viewer")
    invited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("workspace", "email")]
        ordering = ["email"]


class ProviderConnection(models.Model):
    """Tracks which providers are connected live versus demo/simulated."""

    PROVIDER_CHOICES = [
        ("render", "render"),
        ("railway", "railway"),
        ("fly", "fly"),
        ("kong", "kong"),
        ("terraform", "terraform"),
        ("supabase", "supabase"),
        ("cloudflare", "cloudflare"),
        ("stripe", "stripe"),
        ("orena", "orena"),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="provider_connections")
    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES)
    live_enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=32, default="not_configured")
    capabilities = models.JSONField(default=list)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("workspace", "provider")]
        ordering = ["provider"]


class UsageEvent(models.Model):
    """Metered product actions used to enforce plan limits."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="usage_events")
    kind = models.CharField(max_length=64)
    quantity = models.PositiveIntegerField(default=1)
    reference = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["workspace", "kind", "created_at"])]
        ordering = ["-created_at"]


class Customer(models.Model):
    """A billable account, keyed by email and linked to a Stripe customer."""

    email = models.EmailField(unique=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, db_index=True)
    paystack_customer_code = models.CharField(max_length=255, blank=True, default="")
    default_workspace = models.ForeignKey(
        Workspace, on_delete=models.SET_NULL, null=True, blank=True, related_name="customers"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover - admin/debug convenience
        return self.email


class Subscription(models.Model):
    """Mirror of a Stripe subscription, kept in sync via webhooks."""

    STATUS_CHOICES = [
        ("incomplete", "incomplete"),
        ("trialing", "trialing"),
        ("active", "active"),
        ("past_due", "past_due"),
        ("canceled", "canceled"),
        ("unpaid", "unpaid"),
    ]

    PAYMENT_PROVIDER_CHOICES = [
        ("stripe", "stripe"),
        ("paystack", "paystack"),
    ]

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="subscriptions")
    plan_slug = models.CharField(max_length=50)
    stripe_subscription_id = models.CharField(max_length=255, unique=True)
    payment_provider = models.CharField(max_length=32, choices=PAYMENT_PROVIDER_CHOICES, default="stripe")
    paystack_subscription_code = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="incomplete")
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_active(self) -> bool:
        if self.status not in {"active", "trialing"}:
            return False
        if self.current_period_end is not None and self.current_period_end <= timezone.now():
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "email": self.customer.email,
            "planSlug": self.plan_slug,
            "status": self.status,
            "active": self.is_active,
            "cancelAtPeriodEnd": self.cancel_at_period_end,
            "currentPeriodEnd": self.current_period_end.isoformat() if self.current_period_end else None,
            "paymentProvider": self.payment_provider,
        }
