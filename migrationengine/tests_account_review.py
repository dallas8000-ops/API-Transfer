from __future__ import annotations

import json
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from core.secret_classification import partition_env_vars
from migrationengine import adapters, planner
from migrationengine.discovery_vault import hydrate_service_secrets


class SecretClassificationTests(SimpleTestCase):
    def test_partition_env_vars_splits_sensitive_keys(self):
        environment, secrets = partition_env_vars(
            {
                "NODE_ENV": "production",
                "API_KEY": "super-secret",
                "DATABASE_URL": "postgres://secret",
            }
        )
        self.assertEqual(environment, {"NODE_ENV": "production"})
        self.assertEqual(sorted(secrets.keys()), ["API_KEY", "DATABASE_URL"])


class RenderAccountReviewTests(SimpleTestCase):
    @override_settings(RENDER_API_TOKEN="render-token", RENDER_API_BASE_URL="https://api.render.test")
    def test_review_account_returns_settings_and_key_names_only(self):
        services = [
            {
                "id": "srv_123",
                "name": "demo",
                "type": "web_service",
                "branch": "main",
                "repo": "https://github.com/example/demo",
                "region": "oregon",
                "runtime": "node",
                "buildCommand": "npm install",
                "startCommand": "npm start",
                "url": "https://demo.onrender.com",
            }
        ]
        env_vars = {"NODE_ENV": "production", "API_KEY": "hidden-value"}

        with patch("migrationengine.providers.list_render_services", return_value=services), patch(
            "migrationengine.providers.get_render_env_vars", return_value=env_vars
        ):
            result = adapters.review_account("render")

        self.assertTrue(result["live"])
        self.assertEqual(len(result["apps"]), 1)
        app = result["apps"][0]
        self.assertEqual(app["environmentKeys"], ["NODE_ENV"])
        self.assertEqual(app["secretKeys"], ["API_KEY"])
        self.assertNotIn("hidden-value", json.dumps(result))


class DiscoverVaultTests(SimpleTestCase):
    @override_settings(RENDER_API_TOKEN="render-token", RENDER_API_BASE_URL="https://api.render.test")
    def test_discover_seals_secret_values_and_returns_only_key_names(self):
        service = {
            "name": "demo",
            "branch": "main",
            "repo": "example/demo",
            "serviceDetails": {
                "region": "oregon",
                "runtime": "node",
                "buildCommand": "npm install",
                "startCommand": "npm start",
                "url": "https://demo.onrender.com",
            },
        }
        env_vars = {"NODE_ENV": "production", "API_KEY": "hidden-value"}

        with patch("requests.get", return_value=_response(service)), patch(
            "migrationengine.providers.get_render_env_vars", return_value=env_vars
        ):
            result = adapters.discover("render", "srv_123")

        self.assertEqual(result["secretKeys"], ["API_KEY"])
        self.assertEqual(result["spec"]["services"][0]["secrets"], [{"key": "API_KEY", "sealed": True}])
        self.assertEqual(result["spec"]["services"][0]["environment"], {"NODE_ENV": "production"})
        self.assertNotIn("hidden-value", json.dumps(result))
        hydrated = hydrate_service_secrets(result["discoveryId"])
        self.assertEqual(hydrated["API_KEY"], "hidden-value")

    def test_plan_uses_discovery_vault_for_sealed_secrets(self):
        spec = {
            "appName": "demo",
            "sourceProvider": "render",
            "targetProvider": "railway",
            "services": [
                {
                    "name": "web",
                    "runtime": "node",
                    "startCommand": "npm start",
                    "region": "oregon",
                    "environment": {"NODE_ENV": "production"},
                    "secrets": [{"key": "API_KEY", "sealed": True}],
                }
            ],
            "domains": [{"host": "demo.example.com", "tlsRequired": True}],
            "databases": [],
            "metadata": {
                "requestedBy": "tester",
                "requestedAt": "2026-06-08T12:00:00+00:00",
                "environment": "stage",
                "discoveryId": "disc-123",
            },
        }
        with patch("migrationengine.planner.get_discovery_sealed", return_value={"web::API_KEY": _fake_sealed("vault-secret")}):
            result = planner.generate_plan(spec)

        self.assertIn("web::API_KEY", result["sealedRefs"])


def _response(payload, status_code: int = 200):
    from unittest.mock import Mock

    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.text = str(payload)
    return response


def _fake_sealed(value: str) -> dict[str, str]:
    from core.vault import encrypt_secret

    return encrypt_secret(value).to_dict()
