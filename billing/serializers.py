from __future__ import annotations

from rest_framework import serializers

from .stripe_config import PLAN_BY_SLUG


class CheckoutRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    planSlug = serializers.CharField()

    def validate_planSlug(self, value: str) -> str:
        plan = PLAN_BY_SLUG.get(value)
        if plan is None:
            raise serializers.ValidationError(f"Unknown plan '{value}'.")
        if not plan.is_purchasable:
            raise serializers.ValidationError(
                f"Plan '{value}' is not available for self-service checkout."
            )
        return value


class PortalRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    returnUrl = serializers.URLField(required=False, allow_blank=True)
