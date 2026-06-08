from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from billing.models import Subscription

from .models import License, LicenseInstance

DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE)


def normalize_domain(value: str) -> str:
    domain = (value or "").strip().lower().rstrip(".")
    if not DOMAIN_RE.match(domain):
        raise ValueError("A valid registrable domain is required.")
    return domain


def _hash_license_key(raw_key: str) -> str:
    pepper = settings.SECRET_KEY
    return hashlib.sha256(f"{pepper}:{raw_key}".encode("utf-8")).hexdigest()


def generate_license_key() -> str:
    return f"lic_{secrets.token_urlsafe(24)}"


def _issue_new_license(subscription: Subscription, domain: str, max_instances: int, raw_key: str) -> License:
    key_hash = _hash_license_key(raw_key)
    return License.objects.create(
        customer=subscription.customer,
        subscription=subscription,
        key_hash=key_hash,
        key_last4=raw_key[-4:],
        registered_domain=domain,
        max_instances=max_instances,
        status="active",
        expires_at=subscription.current_period_end,
    )


def _send_license_email(to_email: str, key: str, domain: str, max_instances: int) -> None:
    subject = "Your Stripe Installer license key"
    message = (
        "Your license key is ready.\n\n"
        f"License key: {key}\n"
        f"Registered domain: {domain}\n"
        f"Max active instances: {max_instances}\n\n"
        "Store this key securely. It is shown once at issuance time."
    )
    # If email isn't configured in an environment, this safely no-ops in common dev setups.
    send_mail(subject, message, "noreply@apitransfer.local", [to_email], fail_silently=True)


@transaction.atomic
def upsert_license_for_subscription(
    subscription: Subscription, registered_domain: str, max_instances: int = 1
) -> tuple[License, str | None]:
    domain = normalize_domain(registered_domain)
    max_instances = max(1, int(max_instances or 1))

    existing = License.objects.select_for_update().filter(subscription=subscription).first()
    if existing is None:
        raw_key = generate_license_key()
        license_obj = _issue_new_license(subscription, domain, max_instances, raw_key)
        _send_license_email(subscription.customer.email, raw_key, domain, max_instances)
        return license_obj, raw_key

    existing.registered_domain = domain
    existing.max_instances = max_instances
    existing.expires_at = subscription.current_period_end
    existing.status = "active" if subscription.is_active else "expired"
    existing.save(update_fields=["registered_domain", "max_instances", "expires_at", "status", "updated_at"])
    return existing, None


def revoke_license(license_obj: License) -> License:
    license_obj.status = "revoked"
    license_obj.save(update_fields=["status", "updated_at"])
    license_obj.instances.filter(is_active=True).update(is_active=False)
    return license_obj


def _activate_or_create_instance(
    license_obj: License, instance_id: str, normalized_domain: str
) -> tuple[bool, int]:
    instance = LicenseInstance.objects.filter(license=license_obj, instance_id=instance_id).first()
    if instance is None:
        active_count = LicenseInstance.objects.filter(license=license_obj, is_active=True).count()
        if active_count >= license_obj.max_instances:
            return False, active_count
        LicenseInstance.objects.create(license=license_obj, instance_id=instance_id, domain=normalized_domain)
        return True, active_count + 1

    if not instance.is_active:
        active_count = LicenseInstance.objects.filter(license=license_obj, is_active=True).count()
        if active_count >= license_obj.max_instances:
            return False, active_count
        instance.is_active = True
    instance.domain = normalized_domain
    instance.last_seen_at = timezone.now()
    instance.save(update_fields=["domain", "is_active", "last_seen_at"])
    active_count = LicenseInstance.objects.filter(license=license_obj, is_active=True).count()
    return True, active_count


@dataclass
class ValidationResult:
    valid: bool
    reason: str
    expires_at: datetime | None
    active_instances: int
    max_instances: int


@transaction.atomic
def validate_instance(license_key: str, domain: str, instance_id: str) -> ValidationResult:
    if not license_key:
        return ValidationResult(False, "missing_license_key", None, 0, 0)
    if not instance_id:
        return ValidationResult(False, "missing_instance_id", None, 0, 0)

    try:
        normalized_domain = normalize_domain(domain)
    except ValueError:
        return ValidationResult(False, "invalid_domain", None, 0, 0)

    key_hash = _hash_license_key(license_key)
    license_obj = License.objects.select_for_update().filter(key_hash=key_hash).first()
    if license_obj is None:
        return ValidationResult(False, "license_not_found", None, 0, 0)

    if not license_obj.is_valid_now:
        reason = "license_revoked" if license_obj.status == "revoked" else "license_expired"
        return ValidationResult(False, reason, license_obj.expires_at, 0, license_obj.max_instances)

    if normalized_domain != license_obj.registered_domain:
        return ValidationResult(False, "domain_mismatch", license_obj.expires_at, 0, license_obj.max_instances)

    activated, active_count = _activate_or_create_instance(license_obj, instance_id, normalized_domain)
    if not activated:
        return ValidationResult(
            False,
            "instance_limit_exceeded",
            license_obj.expires_at,
            active_count,
            license_obj.max_instances,
        )

    return ValidationResult(True, "ok", license_obj.expires_at, active_count, license_obj.max_instances)
