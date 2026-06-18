"""East Africa regional defaults for migration, billing, and compliance checks."""
from __future__ import annotations

from typing import Any

# Orena ke-1 (Nairobi) and common Africa-adjacent AWS region codes.
AFRICA_REGION_CODES = frozenset(
    {
        "ke-1",
        "nairobi",
        "af-south-1",
        "cape-town",
        "johannesburg",
        "lagos",
        "ng-1",
    }
)

# US / EU defaults that increase latency for East Africa users.
HIGH_LATENCY_REGION_CODES = frozenset(
    {
        "us-east-1",
        "us-east-2",
        "us-west-1",
        "us-west-2",
        "oregon",
        "virginia",
        "eu-west-1",
        "eu-west-2",
        "eu-central-1",
        "frankfurt",
        "london",
    }
)

NON_AFRICA_DB_HOST_MARKERS = (
    ".rds.amazonaws.com",
    ".supabase.co",
    ".neon.tech",
    "us-east-",
    "us-west-",
    "eu-west-",
    "eu-central-",
    "oregon",
    "virginia",
    "frankfurt",
    "london",
)

DEFAULT_EAST_AFRICA_PROVIDER = "orena"
DEFAULT_EAST_AFRICA_REGION = "ke-1"

# Display pricing for Kenya (minor units — cents).
KES_PRICE_CENTS_BY_SLUG: dict[str, int] = {
    "pro": 990_000,  # KES 9,900 / month
    "scale": 2_490_000,  # KES 24,900 / month
}

USD_TO_KES_DISPLAY_RATE = 129.0


def is_africa_region(region: str | None) -> bool:
    if not region:
        return False
    normalized = region.strip().lower().replace("_", "-")
    return normalized in AFRICA_REGION_CODES or normalized.startswith(("ke-", "af-", "ng-"))


def is_high_latency_region(region: str | None) -> bool:
    if not region:
        return False
    normalized = region.strip().lower().replace("_", "-")
    return normalized in HIGH_LATENCY_REGION_CODES or normalized.startswith(("us-", "eu-"))


def database_host_outside_africa(host: str | None) -> bool:
    """Heuristic: flag hostnames that embed known US/EU region markers.

    Platform hostnames (.railway.app, .fly.dev) do not encode region — those are
    intentionally excluded because they would false-positive every deployment.
    """
    if not host:
        return False
    lowered = host.strip().lower()
    return any(marker in lowered for marker in NON_AFRICA_DB_HOST_MARKERS)


def kes_price_cents(slug: str, usd_cents: int) -> int:
    if slug in KES_PRICE_CENTS_BY_SLUG:
        return KES_PRICE_CENTS_BY_SLUG[slug]
    return int(round((usd_cents / 100) * USD_TO_KES_DISPLAY_RATE * 100))


def regional_plan_pricing(slug: str, usd_cents: int) -> dict[str, Any]:
    kes = kes_price_cents(slug, usd_cents)
    return {
        "usd": {"amount": usd_cents / 100, "currency": "usd", "priceCents": usd_cents},
        "kes": {"amount": kes / 100, "currency": "kes", "priceCents": kes},
    }
