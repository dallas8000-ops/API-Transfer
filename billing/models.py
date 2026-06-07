from __future__ import annotations

from django.db import models


class Customer(models.Model):
    """A billable account, keyed by email and linked to a Stripe customer."""

    email = models.EmailField(unique=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, db_index=True)
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

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="subscriptions")
    plan_slug = models.CharField(max_length=50)
    stripe_subscription_id = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="incomplete")
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_active(self) -> bool:
        return self.status in {"active", "trialing"}

    def to_dict(self) -> dict:
        return {
            "email": self.customer.email,
            "planSlug": self.plan_slug,
            "status": self.status,
            "active": self.is_active,
            "cancelAtPeriodEnd": self.cancel_at_period_end,
            "currentPeriodEnd": self.current_period_end.isoformat() if self.current_period_end else None,
        }
