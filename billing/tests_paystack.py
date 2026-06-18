from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from billing import paystack_client, paystack_webhooks


class PaystackSignatureTests(SimpleTestCase):
    @override_settings(PAYSTACK_SECRET_KEY="sk_test_secret")
    def test_verify_webhook_signature_accepts_valid_hmac(self):
        payload = b'{"event":"charge.success","data":{"status":"success","email":"a@b.com"}}'
        signature = hmac.new(b"sk_test_secret", payload, hashlib.sha512).hexdigest()
        event = paystack_client.verify_webhook_signature(payload, signature, "sk_test_secret")
        self.assertEqual(event["event"], "charge.success")


class PaystackWebhookDispatchTests(TestCase):
    @override_settings(PAYSTACK_PLAN_PRO="PLN_test")
    def test_charge_success_creates_subscription(self):
        from billing.models import Subscription

        with patch("billing.paystack_webhooks.upsert_license_for_subscription"):
            paystack_webhooks.process_event(
                {
                    "event": "charge.success",
                    "data": {
                        "status": "success",
                        "email": "buyer@example.com",
                        "reference": "ref_123",
                        "metadata": {
                            "registered_domain": "app.example.com",
                            "max_instances": "1",
                        },
                        "plan": {"plan_code": "PLN_test"},
                    },
                }
            )

        from billing.models import Subscription

        sub = Subscription.objects.get()
        self.assertEqual(sub.plan_slug, "pro")
        self.assertEqual(sub.payment_provider, "paystack")
        self.assertTrue(sub.stripe_subscription_id.startswith("paystack:"))
