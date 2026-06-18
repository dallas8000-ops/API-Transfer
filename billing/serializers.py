from __future__ import annotations

import re

from rest_framework import serializers

from .stripe_config import PLAN_BY_SLUG


class CheckoutRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    planSlug = serializers.CharField()
    registeredDomain = serializers.CharField(required=False, allow_blank=True)
    maxInstances = serializers.IntegerField(required=False, min_value=1, default=1)
    paymentProvider = serializers.ChoiceField(
        choices=["auto", "stripe", "paystack"],
        required=False,
        default="auto",
    )

    DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE)

    def validate_planSlug(self, value: str) -> str:
        plan = PLAN_BY_SLUG.get(value)
        if plan is None:
            raise serializers.ValidationError(f"Unknown plan '{value}'.")
        if not plan.is_purchasable:
            raise serializers.ValidationError(
                f"Plan '{value}' is not available for self-service checkout."
            )
        return value

    def validate(self, attrs):
        plan_slug = attrs.get("planSlug", "")
        if plan_slug in {"pro", "scale"}:
            domain = (attrs.get("registeredDomain") or "").strip().lower().rstrip(".")
            if not domain or not self.DOMAIN_RE.match(domain):
                raise serializers.ValidationError(
                    {"registeredDomain": "A valid registered domain is required for paid plans."}
                )
            attrs["registeredDomain"] = domain
        return attrs


class PortalRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    returnUrl = serializers.URLField(required=False, allow_blank=True)
