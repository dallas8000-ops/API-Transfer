"""Thin Stripe REST client for the platform's own subscription billing.

Uses the same credential-aware, no-secret-logging approach as the provider
adapters. Webhook signatures are verified with a constant-time HMAC comparison
so we don't need the Stripe SDK as a dependency.
"""
from __future__ import annotations

import hmac
import time
from hashlib import sha256
from typing import Any

import requests
from django.conf import settings

TIMEOUT = 20
DEFAULT_SIGNATURE_TOLERANCE = 300  # seconds


class StripeBillingError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"Stripe billing error ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


class StripeSignatureError(Exception):
    """Raised when a webhook signature cannot be verified."""


def is_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def _post(path: str, data: dict[str, Any]) -> dict[str, Any]:
    base = settings.STRIPE_API_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"}
    response = requests.post(f"{base}{path}", headers=headers, data=data, timeout=TIMEOUT)
    payload = _json_or_text(response)
    if response.status_code not in (200, 201):
        detail = payload.get("error", {}).get("message") if isinstance(payload, dict) else str(payload)
        raise StripeBillingError(response.status_code, detail or "request failed")
    return payload if isinstance(payload, dict) else {}


def _json_or_text(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def get_or_create_customer(email: str) -> str:
    """Return a Stripe customer id for the email, creating one if needed."""
    base = settings.STRIPE_API_BASE_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.STRIPE_SECRET_KEY}"}
    lookup = requests.get(
        f"{base}/v1/customers", headers=headers, params={"email": email, "limit": 1}, timeout=TIMEOUT
    )
    existing = _json_or_text(lookup)
    if lookup.status_code == 200 and isinstance(existing, dict) and existing.get("data"):
        return existing["data"][0]["id"]
    created = _post("/v1/customers", {"email": email})
    return created["id"]


def create_checkout_session(email: str, price_id: str, customer_id: str = "") -> dict[str, Any]:
    data = {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "success_url": settings.BILLING_SUCCESS_URL,
        "cancel_url": settings.BILLING_CANCEL_URL,
        "client_reference_id": email,
        "allow_promotion_codes": "true",
    }
    if customer_id:
        data["customer"] = customer_id
    else:
        data["customer_email"] = email
    session = _post("/v1/checkout/sessions", data)
    return {"id": session["id"], "url": session.get("url")}


def create_billing_portal_session(customer_id: str, return_url: str) -> dict[str, Any]:
    session = _post(
        "/v1/billing_portal/sessions",
        {"customer": customer_id, "return_url": return_url},
    )
    return {"url": session.get("url")}


def verify_webhook_signature(payload: bytes, signature_header: str, secret: str) -> dict[str, Any]:
    """Verify a Stripe webhook signature and return the parsed event.

    Implements Stripe's documented scheme: HMAC-SHA256 over ``"{t}.{payload}"``
    keyed by the endpoint signing secret, compared in constant time. Raises
    :class:`StripeSignatureError` on any mismatch or stale timestamp.
    """
    if not secret:
        raise StripeSignatureError("Webhook signing secret is not configured.")
    if not signature_header:
        raise StripeSignatureError("Missing Stripe-Signature header.")

    timestamp = ""
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, _, value = part.partition("=")
        key = key.strip()
        if key == "t":
            timestamp = value.strip()
        elif key == "v1":
            signatures.append(value.strip())

    if not timestamp or not signatures:
        raise StripeSignatureError("Malformed Stripe-Signature header.")

    try:
        ts_int = int(timestamp)
    except ValueError as exc:
        raise StripeSignatureError("Invalid signature timestamp.") from exc

    if abs(time.time() - ts_int) > DEFAULT_SIGNATURE_TOLERANCE:
        raise StripeSignatureError("Signature timestamp outside tolerance.")

    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(secret.encode("utf-8"), signed_payload, sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise StripeSignatureError("Signature verification failed.")

    import json

    try:
        return json.loads(payload.decode("utf-8"))
    except ValueError as exc:
        raise StripeSignatureError("Webhook payload is not valid JSON.") from exc
