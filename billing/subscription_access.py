"""Entitlement helpers — keep subscription and license state aligned with billing periods."""
from __future__ import annotations

from django.utils import timezone

from .models import Customer, Subscription


def expire_subscription_if_past_period(subscription: Subscription) -> bool:
    """Mark subscription canceled when its paid period has ended. Returns True if expired."""
    if subscription.status not in {"active", "trialing"}:
        return False
    if subscription.current_period_end is None:
        return False
    if subscription.current_period_end > timezone.now():
        return False

    subscription.status = "canceled"
    subscription.save(update_fields=["status", "updated_at"])

    license_obj = getattr(subscription, "license", None)
    if license_obj is not None and license_obj.status == "active":
        license_obj.status = "expired"
        license_obj.save(update_fields=["status", "updated_at"])

    return True


def get_entitled_subscription(customer: Customer) -> Subscription | None:
    """Return the newest subscription that is active and inside its billing period."""
    for subscription in customer.subscriptions.filter(status__in=["active", "trialing"]).order_by("-created_at"):
        if expire_subscription_if_past_period(subscription):
            continue
        return subscription
    return None
