from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIRequestFactory

from migrationengine.views import ConsoleBootstrapView, _server_provider_config


class ConsoleBootstrapTests(SimpleTestCase):
    def test_server_provider_config_lists_missing_railway_keys(self):
        with override_settings(RAILWAY_API_TOKEN="", RAILWAY_PROJECT_ID=""):
            config = _server_provider_config()
        self.assertFalse(config["railway"]["configured"])
        self.assertIn("RAILWAY_API_TOKEN", config["railway"]["missing"])
        self.assertIn("RAILWAY_PROJECT_ID", config["railway"]["missing"])

class ConsoleBootstrapApiTests(TestCase):
    @override_settings(
        DEBUG=True,
        RBAC_ADMIN_KEYS=[],
        RBAC_OPERATOR_KEYS=[],
        RBAC_VIEWER_KEYS=[],
        RAILWAY_API_TOKEN="token",
        RAILWAY_PROJECT_ID="proj-1",
    )
    def test_bootstrap_includes_railway_inventory_when_live(self):
        inventory = {
            "provider": "railway",
            "live": True,
            "apps": [{"id": "svc-1", "name": "stripe-installer", "settings": {}, "environmentKeys": [], "secretKeys": []}],
            "message": "Found 1 Railway service(s).",
        }
        factory = APIRequestFactory()
        request = factory.get("/api/migrations/console/bootstrap", HTTP_X_ACCOUNT_EMAIL="ops@example.com")

        with patch("migrationengine.views.adapters.review_account", return_value=inventory):
            response = ConsoleBootstrapView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        body = response.data
        self.assertEqual(body["accountInventories"]["railway"]["apps"][0]["name"], "stripe-installer")
        self.assertTrue(body["serverConfig"]["railway"]["configured"])
