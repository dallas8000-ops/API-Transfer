"""Thin Paystack REST client for East Africa billing (KES, M-Pesa, cards).

Mirrors billing.client (Stripe) — no SDK dependency, HMAC webhook verification,
and no secret logging.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

import requests
from django.conf import settings

TIMEOUT = 20


class PaystackBillingError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Paystack billing error ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


class PaystackSignatureError(Exception):
    """Raised when a webhook signature cannot be verified."""


def is_configured() -> bool:
    return bool(settings.PAYSTACK_SECRET_KEY)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def list_plans() -> list[dict[str, Any]]:
    data = _request("GET", "/plan")
    if isinstance(data, list):
        return data
    raw = data.get("raw")
    if isinstance(raw, list):
        return raw
    return []


def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base = settings.PAYSTACK_API_BASE_URL.rstrip("/")
    response = requests.request(
        method,
        f"{base}{path}",
        headers=_headers(),
        json=payload,
        timeout=TIMEOUT,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text[:500]}
    if response.status_code not in (200, 201):
        detail = body.get("message") if isinstance(body, dict) else str(body)
        raise PaystackBillingError(response.status_code, detail or "request failed")
    if not isinstance(body, dict) or not body.get("status"):
        raise PaystackBillingError(response.status_code, "unexpected Paystack response")
    data = body.get("data")
    return data if isinstance(data, dict) else {"raw": data}


def verify_plan_amount(plan_code: str, expected_amount_cents: int) -> None:
    """Ensure Paystack dashboard plan pricing matches the app catalog."""
    if not plan_code:
        return
    for plan in list_plans():
        if str(plan.get("plan_code") or "") != plan_code:
            continue
        actual = int(plan.get("amount") or 0)
        if actual != int(expected_amount_cents):
            raise PaystackBillingError(
                400,
                f"Paystack plan {plan_code} charges {actual} but catalog expects {expected_amount_cents}.",
            )
        return
    raise PaystackBillingError(404, f"Paystack plan {plan_code} was not found in the dashboard.")


def initialize_transaction(
    email: str,
    amount_cents: int,
    plan_code: str = "",
    metadata: dict[str, Any] | None = None,
    callback_url: str = "",
) -> dict[str, Any]:
    """Start Paystack checkout.

    When ``plan_code`` is set, Paystack uses the dashboard plan amount — call
    ``verify_plan_amount`` before this if catalog pricing must match exactly.
    """
    reference = f"at_{uuid.uuid4().hex[:24]}"
    payload: dict[str, Any] = {
        "email": email,
        "reference": reference,
        "callback_url": callback_url or settings.PAYSTACK_CALLBACK_URL,
        "metadata": metadata or {},
    }
    if plan_code:
        payload["plan"] = plan_code
    else:
        payload["amount"] = max(0, int(amount_cents))
        payload["currency"] = settings.PAYSTACK_CURRENCY.upper()
    data = _request("POST", "/transaction/initialize", payload)
    return {
        "reference": data.get("reference") or reference,
        "url": data.get("authorization_url") or data.get("url"),
        "accessCode": data.get("access_code"),
    }


def verify_transaction(reference: str) -> dict[str, Any]:
    return _request("GET", f"/transaction/verify/{reference}")


def verify_webhook_signature(payload: bytes, signature_header: str, secret: str) -> dict[str, Any]:
    if not secret:
        raise PaystackSignatureError("Paystack webhook secret is not configured.")
    if not signature_header:
        raise PaystackSignatureError("Missing x-paystack-signature header.")
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, signature_header.strip()):
        raise PaystackSignatureError("Signature verification failed.")
    try:
        return json.loads(payload.decode("utf-8"))
    except ValueError as exc:
        raise PaystackSignatureError("Webhook payload is not valid JSON.") from exc
