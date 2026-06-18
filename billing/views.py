from __future__ import annotations

import logging

from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import client, paystack_client, paystack_webhooks, webhooks
from .entitlements import account_email_from_request, entitlements_payload, get_or_create_workspace
from .models import Customer, Subscription
from .serializers import CheckoutRequestSerializer, PortalRequestSerializer
from .stripe_config import PLAN_BY_SLUG, paystack_amount_cents, public_catalog

logger = logging.getLogger("billing")


class PlansView(APIView):
    """Public pricing catalog for the marketing/pricing page."""

    permission_classes = [AllowAny]

    def get(self, request):
        currency = (request.query_params.get("currency") or "").strip().lower() or None
        return Response(
            {
                "plans": public_catalog(currency=currency),
                "publishableKey": settings.STRIPE_PUBLISHABLE_KEY,
                "paystackPublicKey": settings.PAYSTACK_PUBLIC_KEY,
                "billingEnabled": client.is_configured() or paystack_client.is_configured(),
                "paymentProviders": {
                    "stripe": {"enabled": client.is_configured(), "currency": settings.BILLING_CURRENCY},
                    "paystack": {
                        "enabled": paystack_client.is_configured(),
                        "currency": settings.PAYSTACK_CURRENCY,
                        "channels": ["card", "mobile_money"],
                    },
                },
                "regional": {
                    "defaultProvider": settings.DEFAULT_EAST_AFRICA_PROVIDER,
                    "defaultRegion": settings.DEFAULT_EAST_AFRICA_REGION,
                    "supportedCurrencies": ["usd", "kes"],
                },
            }
        )


class AccountView(APIView):
    """Return the current workspace, plan, usage and entitlement limits."""

    permission_classes = [AllowAny]

    def get(self, request):
        email = account_email_from_request(request)
        ctx = get_or_create_workspace(email)
        return Response(entitlements_payload(ctx))


class CreateCheckoutSessionView(APIView):
    """Start a Stripe Checkout session for a self-service subscription."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CheckoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        plan = PLAN_BY_SLUG[serializer.validated_data["planSlug"]]
        registered_domain = serializer.validated_data.get("registeredDomain", "")
        max_instances = serializer.validated_data.get("maxInstances", 1)
        payment_provider = serializer.validated_data.get("paymentProvider", "auto")

        if payment_provider in {"auto", "paystack"} and paystack_client.is_configured() and plan.paystack_plan_code:
            try:
                expected_amount = paystack_amount_cents(plan)
                paystack_client.verify_plan_amount(plan.paystack_plan_code, expected_amount)
                metadata = {
                    "plan_slug": plan.slug,
                    "registered_domain": registered_domain,
                    "max_instances": str(max(1, int(max_instances or 1))),
                    "email": email,
                }
                session = paystack_client.initialize_transaction(
                    email,
                    paystack_amount_cents(plan),
                    plan_code=plan.paystack_plan_code,
                    metadata=metadata,
                )
            except paystack_client.PaystackBillingError as exc:
                logger.exception("Paystack checkout failed: %s", exc.detail)
                if payment_provider == "paystack":
                    return Response({"error": "Could not start Paystack checkout."}, status=502)
            else:
                return Response(
                    {
                        "provider": "paystack",
                        "reference": session["reference"],
                        "url": session["url"],
                    }
                )

        if not client.is_configured():
            return Response(
                {"error": "Billing is not configured on this server."}, status=503
            )

        try:
            customer, _ = Customer.objects.get_or_create(email=email)
            stripe_customer_id = customer.stripe_customer_id or client.get_or_create_customer(email)
            if customer.stripe_customer_id != stripe_customer_id:
                customer.stripe_customer_id = stripe_customer_id
                customer.save(update_fields=["stripe_customer_id"])
            session = client.create_checkout_session(
                email,
                plan.stripe_price_id,
                stripe_customer_id,
                registered_domain=registered_domain,
                max_instances=max_instances,
            )
        except client.StripeBillingError as exc:
            logger.exception("Checkout session failed: %s", exc.detail)
            return Response({"error": "Could not start checkout."}, status=502)

        return Response({"provider": "stripe", "sessionId": session["id"], "url": session["url"]})


class BillingPortalView(APIView):
    """Return a Stripe Billing Portal URL so a customer can manage their plan."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PortalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        return_url = serializer.validated_data.get("returnUrl") or settings.BILLING_CANCEL_URL

        customer = Customer.objects.filter(email=email).first()
        if customer is None or not customer.stripe_customer_id:
            return Response({"error": "No billing account found for that email."}, status=404)
        if not client.is_configured():
            return Response({"error": "Billing is not configured on this server."}, status=503)

        try:
            session = client.create_billing_portal_session(customer.stripe_customer_id, return_url)
        except client.StripeBillingError as exc:
            logger.exception("Billing portal failed: %s", exc.detail)
            return Response({"error": "Could not open billing portal."}, status=502)
        return Response({"url": session["url"]})


class SubscriptionStatusView(APIView):
    """Look up the current subscription for an email (customer self-service)."""

    permission_classes = [AllowAny]

    def get(self, request):
        email = request.query_params.get("email", "").strip()
        if not email:
            return Response({"error": "email query parameter is required."}, status=400)
        customer = Customer.objects.filter(email=email).first()
        if customer is None:
            return Response({"email": email, "subscription": None, "planSlug": "free"})
        sub = (
            Subscription.objects.filter(customer=customer, status__in=["active", "trialing"])
            .order_by("-created_at")
            .first()
        )
        if sub is None:
            return Response({"email": email, "subscription": None, "planSlug": "free"})
        return Response({"email": email, "subscription": sub.to_dict(), "planSlug": sub.plan_slug})


class PaystackWebhookView(APIView):
    """Receive Paystack webhooks. Secured by HMAC-SHA512 signature verification."""

    permission_classes = [AllowAny]

    def post(self, request):
        signature = request.META.get("HTTP_X_PAYSTACK_SIGNATURE", "")
        try:
            event = paystack_client.verify_webhook_signature(
                request.body, signature, settings.PAYSTACK_SECRET_KEY
            )
        except paystack_client.PaystackSignatureError as exc:
            logger.warning("Rejected Paystack webhook: %s", exc)
            return Response({"error": "Invalid signature."}, status=400)

        status_text = paystack_webhooks.process_event(event)
        logger.info("Paystack webhook %s -> %s", event.get("event"), status_text)
        return Response({"received": True, "status": status_text})


class StripeWebhookView(APIView):
    """Receive Stripe webhooks. Secured by signature verification, not RBAC."""

    permission_classes = [AllowAny]

    def post(self, request):
        signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = client.verify_webhook_signature(
                request.body, signature, settings.STRIPE_WEBHOOK_SECRET
            )
        except client.StripeSignatureError as exc:
            logger.warning("Rejected Stripe webhook: %s", exc)
            return Response({"error": "Invalid signature."}, status=400)

        status_text = webhooks.process_event(event)
        logger.info("Stripe webhook %s -> %s", event.get("type"), status_text)
        return Response({"received": True, "status": status_text})
