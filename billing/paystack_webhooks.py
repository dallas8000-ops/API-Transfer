"""Paystack webhook handlers — keep subscription state aligned with Stripe path."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from licenses.services import revoke_license, upsert_license_for_subscription

from .models import Customer, Subscription
from .stripe_config import PLAN_BY_SLUG, plan_for_paystack_plan_code

logger = logging.getLogger("billing")


def _epoch_to_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _parse_license_metadata(metadata: dict[str, Any] | None) -> tuple[str, int]:
    metadata = metadata or {}
    registered_domain = (metadata.get("registered_domain") or metadata.get("registeredDomain") or "").strip()
    max_instances_raw = metadata.get("max_instances") or metadata.get("maxInstances") or "1"
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
            logger.warning("Paystack subscription %s has invalid registered_domain metadata", subscription.stripe_subscription_id)
        return
    existing_license = getattr(subscription, "license", None)
    if existing_license is not None and not subscription.is_active:
        revoke_license(existing_license)


def _customer_for(email: str, customer_code: str = "") -> Customer | None:
    if not email:
        return None
    customer, _ = Customer.objects.get_or_create(email=email)
    if customer_code and getattr(customer, "paystack_customer_code", "") != customer_code:
        customer.paystack_customer_code = customer_code
        customer.save(update_fields=["paystack_customer_code"])
    return customer


def _period_end_from_plan(paid_at: datetime | None, plan_slug: str) -> datetime | None:
    if paid_at is None:
        return None
    plan = PLAN_BY_SLUG.get(plan_slug)
    if plan and plan.interval == "year":
        return paid_at + timedelta(days=365)
    if plan and plan.interval == "month":
        return paid_at + timedelta(days=30)
    return paid_at + timedelta(days=30)


def _upsert_from_charge(data: dict[str, Any]) -> None:
    email = (data.get("customer") or {}).get("email") or data.get("email") or ""
    metadata = data.get("metadata") or {}
    if not email and isinstance(metadata, dict):
        email = metadata.get("email") or metadata.get("customer_email") or ""
    if not email:
        logger.warning("Paystack charge.success without email; skipping.")
        return

    customer_code = (data.get("customer") or {}).get("customer_code") or ""
    customer = _customer_for(email, customer_code)
    if customer is None:
        return

    plan_code = (data.get("plan") or {}).get("plan_code") or metadata.get("plan_code") or ""
    plan = plan_for_paystack_plan_code(plan_code)
    plan_slug = plan.slug if plan else metadata.get("plan_slug") or "unknown"

    subscription_code = (data.get("subscription") or {}).get("subscription_code") or metadata.get("subscription_code") or ""
    registered_domain, max_instances = _parse_license_metadata(metadata if isinstance(metadata, dict) else {})
    paid_at = _epoch_to_dt(data.get("paid_at")) or datetime.now(tz=timezone.utc)
    period_end = _epoch_to_dt((data.get("subscription") or {}).get("next_payment_date"))
    if period_end is None:
        period_end = _period_end_from_plan(paid_at, plan_slug)

    external_id = f"paystack:{subscription_code or data.get('reference') or data.get('id')}"

    subscription, _ = Subscription.objects.update_or_create(
        stripe_subscription_id=external_id,
        defaults={
            "customer": customer,
            "plan_slug": plan_slug,
            "status": "active" if data.get("status") == "success" else "incomplete",
            "current_period_end": period_end,
            "cancel_at_period_end": False,
            "payment_provider": "paystack",
            "paystack_subscription_code": subscription_code,
        },
    )
    _sync_subscription_license(subscription, plan_slug, registered_domain, max_instances)


def _handle_subscription_create(data: dict[str, Any]) -> None:
    email = (data.get("customer") or {}).get("email") or ""
    customer_code = (data.get("customer") or {}).get("customer_code") or ""
    customer = _customer_for(email, customer_code)
    if customer is None:
        logger.warning("Paystack subscription.create without resolvable customer; skipping.")
        return

    plan_code = (data.get("plan") or {}).get("plan_code") or ""
    plan = plan_for_paystack_plan_code(plan_code)
    plan_slug = plan.slug if plan else "unknown"
    subscription_code = data.get("subscription_code") or data.get("code") or ""
    external_id = f"paystack:{subscription_code or data.get('id')}"
    period_end = _epoch_to_dt(data.get("next_payment_date") or data.get("current_period_end"))

    subscription, _ = Subscription.objects.update_or_create(
        stripe_subscription_id=external_id,
        defaults={
            "customer": customer,
            "plan_slug": plan_slug,
            "status": "active" if str(data.get("status", "")).lower() in {"active", "complete"} else "incomplete",
            "current_period_end": period_end,
            "payment_provider": "paystack",
            "paystack_subscription_code": subscription_code,
        },
    )
    registered_domain, max_instances = _parse_license_metadata(data.get("metadata"))
    _sync_subscription_license(subscription, plan_slug, registered_domain, max_instances)


def _handle_subscription_disabled(data: dict[str, Any]) -> None:
    subscription_code = data.get("subscription_code") or data.get("code") or ""
    external_id = f"paystack:{subscription_code or data.get('id')}"
    sub = Subscription.objects.filter(stripe_subscription_id=external_id).first()
    if sub:
        sub.status = "canceled"
        sub.cancel_at_period_end = False
        sub.save(update_fields=["status", "cancel_at_period_end", "updated_at"])
        existing_license = getattr(sub, "license", None)
        if existing_license is not None:
            revoke_license(existing_license)


_DISPATCH = {
    "charge.success": _upsert_from_charge,
    "subscription.create": _handle_subscription_create,
    "subscription.disable": _handle_subscription_disabled,
    "subscription.not_renew": _handle_subscription_disabled,
}


def process_event(event: dict[str, Any]) -> str:
    event_type = event.get("event", "")
    handler = _DISPATCH.get(event_type)
    if handler is None:
        return "ignored"
    data = event.get("data") or {}
    handler(data if isinstance(data, dict) else {})
    return "processed"
