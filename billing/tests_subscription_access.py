from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from billing.entitlements import get_or_create_workspace
from billing.models import Customer, Subscription
from billing.paystack_webhooks import process_event
from billing.subscription_access import expire_subscription_if_past_period, get_entitled_subscription


class PaystackPeriodEndTests(TestCase):
    @override_settings(PAYSTACK_PLAN_PRO="PLN_test")
    def test_charge_success_sets_period_end_one_month_ahead(self):
        with patch("billing.paystack_webhooks.upsert_license_for_subscription"):
            process_event(
                {
                    "event": "charge.success",
                    "data": {
                        "status": "success",
                        "email": "buyer@example.com",
                        "reference": "ref_123",
                        "paid_at": int(timezone.now().timestamp()),
                        "metadata": {
                            "registered_domain": "app.example.com",
                            "max_instances": "1",
                        },
                        "plan": {"plan_code": "PLN_test"},
                    },
                }
            )

        sub = Subscription.objects.get()
        self.assertIsNotNone(sub.current_period_end)
        self.assertGreater(sub.current_period_end, timezone.now() + timedelta(days=29))

    def test_expired_subscription_is_not_entitled(self):
        customer = Customer.objects.create(email="expired@example.com")
        sub = Subscription.objects.create(
            customer=customer,
            plan_slug="pro",
            stripe_subscription_id="paystack:ref_old",
            status="active",
            payment_provider="paystack",
            current_period_end=timezone.now() - timedelta(days=1),
        )

        self.assertFalse(sub.is_active)
        self.assertTrue(expire_subscription_if_past_period(sub))
        sub.refresh_from_db()
        self.assertEqual(sub.status, "canceled")
        self.assertIsNone(get_entitled_subscription(customer))

    def test_entitlements_drop_to_free_after_period_expires(self):
        customer = Customer.objects.create(email="grace@example.com")
        Subscription.objects.create(
            customer=customer,
            plan_slug="pro",
            stripe_subscription_id="paystack:ref_grace",
            status="active",
            payment_provider="paystack",
            current_period_end=timezone.now() - timedelta(hours=1),
        )

        ctx = get_or_create_workspace("grace@example.com")
        self.assertEqual(ctx.plan_slug, "free")
