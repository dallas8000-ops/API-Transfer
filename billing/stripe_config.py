"""Stripe billing configuration for the platform's own subscription plans.

This module is the single source of truth for API Transfer's self-service
billing tiers. Stripe Price IDs are injected from environment/settings so the
same code runs against test and live Stripe accounts without edits.

Nothing secret lives here: only the publishable key and plan catalog are exposed
to the browser via the public ``/api/billing/plans`` endpoint.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.conf import settings


@dataclass(frozen=True)
class Plan:
    slug: str
    name: str
    description: str
    price_cents: int  # display price; the real charge is the Stripe Price.
    interval: str  # "month" | "year" | "" for free/custom
    features: list[str] = field(default_factory=list)
    # Limits surfaced to the UI and (optionally) enforced server-side.
    limits: dict[str, Any] = field(default_factory=dict)
    cta: str = "Subscribe"
    highlighted: bool = False

    @property
    def stripe_price_id(self) -> str:
        return PRICE_ID_BY_SLUG.get(self.slug, "")

    @property
    def is_purchasable(self) -> bool:
        """A plan is purchasable when it maps to a configured Stripe Price."""
        return bool(self.stripe_price_id)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "price": self.price_cents / 100,
            "priceCents": self.price_cents,
            "interval": self.interval,
            "currency": settings.BILLING_CURRENCY,
            "features": list(self.features),
            "limits": dict(self.limits),
            "cta": self.cta,
            "highlighted": self.highlighted,
            "purchasable": self.is_purchasable,
        }


# Plan catalog. Free and Enterprise are not purchasable via self-serve Checkout
# (Free needs no payment; Enterprise routes to sales).
PLANS: list[Plan] = [
    Plan(
        slug="free",
        name="Free",
        description="Kick the tires on migrations and diagnostics.",
        price_cents=0,
        interval="",
        features=[
            "3 migrations / month",
            "Project diagnostics + auto-fix",
            "Simulated deployments",
            "Community support",
        ],
        limits={"migrationsPerMonth": 3, "liveDeployments": 0, "seats": 1},
        cta="Start free",
    ),
    Plan(
        slug="pro",
        name="Pro",
        description="Stripe Installer with dedicated license issuance and instance validation.",
        price_cents=7900,
        interval="month",
        features=[
            "Unlimited migrations",
            "Live deployments (Fly, Supabase, Cloudflare, Stripe)",
            "License key issuance tied to subscription + registered domain",
            "1 validated production instance per subscription",
            "24h heartbeat validation for deployed instances",
            "Terraform plan/apply with drift detection",
            "Tamper-evident audit log",
            "Email support",
        ],
        limits={"migrationsPerMonth": None, "liveDeployments": 50, "seats": 5, "maxInstances": 1},
        cta="Upgrade to Pro",
        highlighted=True,
    ),
    Plan(
        slug="scale",
        name="Scale",
        description="High-volume automation with priority guarantees.",
        price_cents=19900,
        interval="month",
        features=[
            "Everything in Pro",
            "Unlimited live deployments",
            "Priority queue + SLAs",
            "SSO-ready RBAC",
            "Priority support",
        ],
        limits={"migrationsPerMonth": None, "liveDeployments": None, "seats": 25},
        cta="Upgrade to Scale",
    ),
    Plan(
        slug="enterprise",
        name="Enterprise",
        description="Custom contracts, dedicated infra, and security review.",
        price_cents=0,
        interval="",
        features=[
            "Everything in Scale",
            "Dedicated tenancy",
            "Custom integrations",
            "Security & compliance review",
            "Dedicated support engineer",
        ],
        limits={"migrationsPerMonth": None, "liveDeployments": None, "seats": None},
        cta="Contact sales",
    ),
]

PLAN_BY_SLUG: dict[str, Plan] = {plan.slug: plan for plan in PLANS}


def _price_id_by_slug() -> dict[str, str]:
    # Resolved lazily against settings so tests/dev can run without price IDs.
    return {
        "pro": settings.STRIPE_PRICE_PRO,
        "scale": settings.STRIPE_PRICE_SCALE,
    }


class _PriceMap:
    """Lazy, settings-backed mapping of plan slug -> Stripe Price ID."""

    def get(self, slug: str, default: str = "") -> str:
        return _price_id_by_slug().get(slug, default) or default

    def __getitem__(self, slug: str) -> str:
        return self.get(slug)


PRICE_ID_BY_SLUG = _PriceMap()


def public_catalog() -> list[dict[str, Any]]:
    return [plan.to_public_dict() for plan in PLANS]


def plan_for_price_id(price_id: str) -> Plan | None:
    if not price_id:
        return None
    for plan in PLANS:
        if plan.stripe_price_id and plan.stripe_price_id == price_id:
            return plan
    return None
