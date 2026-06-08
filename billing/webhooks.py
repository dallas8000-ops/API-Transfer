"""Stripe webhook event handlers that keep local billing state in sync.

Each handler is idempotent: Stripe may deliver the same event more than once, so
we upsert rather than assume first-delivery.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from licenses.services import revoke_license, upsert_license_for_subscription

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


def _parse_license_metadata(obj: dict[str, Any]) -> tuple[str, int]:
    metadata = obj.get("metadata") or {}
    registered_domain = (metadata.get("registered_domain") or "").strip()
    max_instances_raw = metadata.get("max_instances") or "1"
    try:
        max_instances = max(1, int(max_instances_raw))
    except (TypeError, ValueError):
        max_instances = 1
    return registered_domain, max_instances


def _sync_subscription_license(subscription: Subscription, plan_slug: str, registered_domain: str, max_instances: int) -> None:
    if subscription.is_active and plan_slug in {"pro", "scale"} and registered_domain:
        try:
            upsert_license_for_subscription(subscription, registered_domain, max_instances=max_instances)
        except ValueError:
            logger.warning(
                "Subscription %s has invalid registered_domain metadata",
                subscription.stripe_subscription_id,
            )
        return

    existing_license = getattr(subscription, "license", None)
    if existing_license is not None and not subscription.is_active:
        revoke_license(existing_license)


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

    subscription, _ = Subscription.objects.update_or_create(
        stripe_subscription_id=obj.get("id"),
        defaults={
            "customer": customer,
            "plan_slug": plan_slug,
            "status": obj.get("status", "incomplete"),
            "current_period_end": _epoch_to_dt(obj.get("current_period_end")),
            "cancel_at_period_end": bool(obj.get("cancel_at_period_end")),
        },
    )

    registered_domain, max_instances = _parse_license_metadata(obj)
    _sync_subscription_license(subscription, plan_slug, registered_domain, max_instances)


def _handle_subscription_deleted(obj: dict[str, Any]) -> None:
    sub = Subscription.objects.filter(stripe_subscription_id=obj.get("id")).first()
    if sub:
        sub.status = "canceled"
        sub.cancel_at_period_end = False
        sub.save(update_fields=["status", "cancel_at_period_end", "updated_at"])
        existing_license = getattr(sub, "license", None)
        if existing_license is not None:
            revoke_license(existing_license)


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
