from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from core.platform_setup import audit_platform, prewire_client, run_setup_action


class PlatformSetupAuditTests(TestCase):
    def test_audit_lists_core_services(self):
        audit = audit_platform()
        task_ids = {t["id"] for t in audit["tasks"]}
        self.assertIn("stripe_billing", task_ids)
        self.assertIn("paystack_billing", task_ids)
        self.assertIn("orena", task_ids)
        self.assertIn("railway", task_ids)
        self.assertIn("render", task_ids)
        self.assertIn("fly", task_ids)
        self.assertIn("vault", task_ids)
        self.assertIn(audit["summary"]["migrationTotal"], (7, 8))

    def test_unknown_action_returns_error(self):
        result = run_setup_action("not_a_real_action")
        self.assertFalse(result["ok"])


class PlatformSetupDetectTests(TestCase):
    @override_settings(
        RAILWAY_API_TOKEN="token",
        RAILWAY_PROJECT_ID="proj-1",
        STRIPE_SECRET_KEY="",
    )
    @patch("migrationengine.providers.list_railway_services")
    @patch("migrationengine.providers.get_railway_env_vars")
    @patch("migrationengine.providers.get_railway_service_source")
    def test_detect_stripe_installer_on_railway(self, mock_source, mock_env, mock_list):
        mock_list.return_value = [{"id": "svc-1", "name": "stripe-installer", "projectId": "proj-1", "environmentId": "env-1"}]
        mock_env.return_value = {"STRIPE_SECRET_KEY": "sk_test_abc", "STRIPE_PUBLISHABLE_KEY": "pk_test_abc"}
        mock_source.return_value = {"repoUrl": "https://github.com/org/stripe-installer", "branch": "main"}
        from core.platform_setup import detect_stripe_installer_sources

        sources = detect_stripe_installer_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["serviceName"], "stripe-installer")
        self.assertTrue(sources[0]["hasStripeSecret"])

    @override_settings(RAILWAY_API_TOKEN="token", RAILWAY_PROJECT_ID="proj-1")
    @patch("migrationengine.providers.list_railway_services")
    @patch("migrationengine.providers._railway_environment_id", return_value="env-1")
    @patch("core.platform_setup.detect_stripe_installer_sources")
    @patch("migrationengine.providers.get_railway_env_vars")
    def test_sync_stripe_from_railway_action(self, mock_env, mock_detect, _mock_env_id, mock_list):
        mock_detect.return_value = [
            {
                "serviceName": "stripe-installer",
                "serviceId": "svc-1",
                "projectId": "proj-1",
            }
        ]
        mock_list.return_value = [{"id": "svc-1", "name": "stripe-installer"}]
        mock_env.return_value = {
            "STRIPE_SECRET_KEY": "sk_test_sync",
            "STRIPE_PUBLISHABLE_KEY": "pk_test_sync",
            "STRIPE_PRICE_PRO": "price_123",
        }
        result = run_setup_action("sync_stripe_from_railway")
        self.assertTrue(result["ok"])
        self.assertIn("STRIPE_SECRET_KEY=sk_test_sync", result["suggestedEnvText"])

    @override_settings(RAILWAY_API_TOKEN="token", RAILWAY_PROJECT_ID="proj-1", ON_RAILWAY=False, STRIPE_SECRET_KEY="")
    @patch("core.env_file.apply_env_updates", return_value={"applied": True, "path": "/tmp/.env", "keys": ["STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_PRICE_PRO"]})
    @patch("migrationengine.providers.list_railway_services")
    @patch("migrationengine.providers._railway_environment_id", return_value="env-1")
    @patch("core.platform_setup.detect_stripe_installer_sources")
    @patch("migrationengine.providers.get_railway_env_vars")
    def test_sync_stripe_applies_to_env_when_requested(self, mock_env, mock_detect, _mock_env_id, mock_list, mock_apply):
        mock_detect.return_value = [{"serviceName": "stripe-installer", "serviceId": "svc-1", "projectId": "proj-1"}]
        mock_list.return_value = [{"id": "svc-1", "name": "stripe-installer"}]
        mock_env.return_value = {
            "STRIPE_SECRET_KEY": "sk_test_sync",
            "STRIPE_PUBLISHABLE_KEY": "pk_test_sync",
            "STRIPE_PRICE_PRO": "price_123",
        }
        result = run_setup_action("sync_stripe_from_railway", apply_to_env=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["appliedToEnv"])
        mock_apply.assert_called_once()

    @patch("core.platform_setup._load_stripe_from_env_backups", return_value=({}, None))
    @patch("core.platform_setup.detect_stripe_installer_sources")
    @patch("core.platform_setup._collect_stripe_env_from_railway", return_value=({"STRIPE_PUBLISHABLE_KEY": "pk_test"}, ["Stripe-Installer"]))
    def test_sync_stripe_needs_manual_secret_when_sealed(self, mock_collect, mock_detect, _mock_backup):
        mock_detect.return_value = [
            {
                "serviceName": "Stripe-Installer",
                "serviceId": "svc-1",
                "projectId": "proj-1",
                "stripeKeysOnRailway": ["STRIPE_PUBLISHABLE_KEY"],
            }
        ]
        result = run_setup_action("sync_stripe_from_railway")
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("needsManualSecret"))
        self.assertIn("STRIPE_SECRET_KEY", result.get("message", ""))


class ClientPrewireTests(TestCase):
    @override_settings(DEFAULT_EAST_AFRICA_PROVIDER="orena")
    def test_prewire_creates_workspace_and_checklist(self):
        result = prewire_client(
            operator_email="ops@agency.com",
            client_email="client@example.com",
            client_name="Client Co",
            client_domain="app.client.co.ke",
            target_provider="orena",
            target_region="ke-1",
            services=["orena", "paystack"],
            run_discover=False,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["workspace"]["ownerEmail"], "client@example.com")
        self.assertTrue(any(c["service"] == "paystack" for c in result["connections"]))
        self.assertTrue(result["checklist"][1]["done"])

    @override_settings(DEFAULT_EAST_AFRICA_PROVIDER="orena")
    def test_prewire_runs_discover_when_source_given(self):
        with patch("migrationengine.adapters.discover") as discover, patch(
            "migrationengine.planner.generate_plan", return_value={"planId": "p1"}
        ):
            discover.return_value = {"discoveryId": "disc-1", "spec": {"services": [{"region": "oregon"}]}}
            result = prewire_client(
                operator_email="ops@agency.com",
                client_email="client2@example.com",
                client_name="Client 2",
                client_domain="app2.client.co.ke",
                target_provider="orena",
                target_region="ke-1",
                source_provider="railway",
                app_identifier="demo-svc",
                services=["orena"],
                run_discover=True,
            )
        self.assertEqual(result["discoveryId"], "disc-1")
        self.assertEqual(result["migrationPlan"], {"planId": "p1"})
        self.assertTrue(result["checklist"][4]["done"])
