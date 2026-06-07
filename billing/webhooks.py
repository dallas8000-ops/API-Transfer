"""Stripe webhook event handlers that keep local billing state in sync.

Each handler is idempotent: Stripe may deliver the same event more than once, so
we upsert rather than assume first-delivery.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .models import Customer, Subscription
from .stripe_config import plan_for_price_id

logger = logging.getLogger("billing")


def _epoch_to_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _customer_for(stripe_customer_id: str, email: str = "") -> Customer | None:
    if stripe_customer_id:
        customer = Customer.objects.filter(stripe_customer_id=stripe_customer_id).first()
        if customer:
            return customer
    if email:
        customer, _ = Customer.objects.get_or_create(email=email)
        if stripe_customer_id and not customer.stripe_customer_id:
            customer.stripe_customer_id = stripe_customer_id
            customer.save(update_fields=["stripe_customer_id"])
        return customer
    return None


def _handle_checkout_completed(obj: dict[str, Any]) -> None:
    email = obj.get("client_reference_id") or (obj.get("customer_details") or {}).get("email") or ""
    stripe_customer_id = obj.get("customer") or ""
    if not email:
        logger.warning("checkout.session.completed without an email reference; skipping.")
        return
    customer, _ = Customer.objects.get_or_create(email=email)
    if stripe_customer_id and customer.stripe_customer_id != stripe_customer_id:
        customer.stripe_customer_id = stripe_customer_id
        customer.save(update_fields=["stripe_customer_id"])


def _handle_subscription_event(obj: dict[str, Any]) -> None:
    stripe_customer_id = obj.get("customer") or ""
    customer = _customer_for(stripe_customer_id)
    if customer is None:
        logger.warning("Subscription event for unknown customer %s; skipping.", stripe_customer_id)
        return

    items = (obj.get("items") or {}).get("data") or []
    price_id = items[0].get("price", {}).get("id") if items else ""
    plan = plan_for_price_id(price_id)
    plan_slug = plan.slug if plan else "unknown"

    Subscription.objects.update_or_create(
        stripe_subscription_id=obj.get("id"),
        defaults={
            "customer": customer,
            "plan_slug": plan_slug,
            "status": obj.get("status", "incomplete"),
            "current_period_end": _epoch_to_dt(obj.get("current_period_end")),
            "cancel_at_period_end": bool(obj.get("cancel_at_period_end")),
        },
    )


def _handle_subscription_deleted(obj: dict[str, Any]) -> None:
    sub = Subscription.objects.filter(stripe_subscription_id=obj.get("id")).first()
    if sub:
        sub.status = "canceled"
        sub.cancel_at_period_end = False
        sub.save(update_fields=["status", "cancel_at_period_end", "updated_at"])


_DISPATCH = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.created": _handle_subscription_event,
    "customer.subscription.updated": _handle_subscription_event,
    "customer.subscription.deleted": _handle_subscription_deleted,
}


def process_event(event: dict[str, Any]) -> str:
    """Dispatch a verified Stripe event. Returns a short status string."""
    event_type = event.get("type", "")
    handler = _DISPATCH.get(event_type)
    if handler is None:
        return "ignored"
    obj = (event.get("data") or {}).get("object") or {}
    handler(obj)
    return "processed"
