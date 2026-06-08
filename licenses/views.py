from __future__ import annotations

import hashlib

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import Subscription

from .models import License
from .serializers import IssueLicenseSerializer, RevokeLicenseSerializer, ValidateLicenseSerializer
from .services import revoke_license, upsert_license_for_subscription, validate_instance


def _license_hash(raw_key: str) -> str:
    return hashlib.sha256(f"{settings.SECRET_KEY}:{raw_key}".encode("utf-8")).hexdigest()


class IssueLicenseView(APIView):
    """Issue or update a license for an active Stripe subscription."""

    def post(self, request):
        serializer = IssueLicenseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sub = Subscription.objects.filter(
            stripe_subscription_id=serializer.validated_data["subscriptionId"]
        ).first()
        if sub is None:
            return Response({"error": "Subscription not found."}, status=404)

        try:
            license_obj, raw_key = upsert_license_for_subscription(
                sub,
                serializer.validated_data["registeredDomain"],
                serializer.validated_data.get("maxInstances", 1),
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=400)

        return Response(
            {
                "license": {
                    "subscriptionId": sub.stripe_subscription_id,
                    "domain": license_obj.registered_domain,
                    "maxInstances": license_obj.max_instances,
                    "status": license_obj.status,
                    "expiresAt": license_obj.expires_at.isoformat() if license_obj.expires_at else None,
                    "keyLast4": license_obj.key_last4,
                },
                "issuedKey": raw_key,
            }
        )


class ValidateLicenseView(APIView):
    """Public endpoint used by deployed customer instances at startup and every 24h."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ValidateLicenseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = validate_instance(
            serializer.validated_data["licenseKey"],
            serializer.validated_data["domain"],
            serializer.validated_data["instanceId"],
        )

        return Response(
            {
                "valid": result.valid,
                "reason": result.reason,
                "expiresAt": result.expires_at.isoformat() if result.expires_at else None,
                "maxInstances": result.max_instances,
                "activeInstances": result.active_instances,
            },
            status=200 if result.valid else 403,
        )


class RevokeLicenseView(APIView):
    """Admin endpoint to revoke an issued license key."""

    def post(self, request):
        serializer = RevokeLicenseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        license_obj = License.objects.filter(
            key_hash=_license_hash(serializer.validated_data["licenseKey"])
        ).first()
        if license_obj is None:
            return Response({"error": "License not found."}, status=404)

        revoke_license(license_obj)
        return Response({"revoked": True, "keyLast4": license_obj.key_last4})
