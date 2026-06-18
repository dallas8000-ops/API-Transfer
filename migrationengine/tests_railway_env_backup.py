from __future__ import annotations

import json
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from migrationengine.providers import ProviderApiError, backup_railway_env_snapshot


@override_settings(RAILWAY_PROJECT_ID="proj-1")
class BackupRailwayEnvSnapshotTests(SimpleTestCase):
    @patch("migrationengine.providers.Path.write_text")
    @patch("migrationengine.providers.Path.mkdir")
    @patch("migrationengine.providers.get_railway_env_vars")
    @patch("migrationengine.providers._railway_environment_id", return_value="env-1")
    def test_writes_json_backup_with_secret_metadata(
        self,
        _mock_env_id,
        mock_get_vars,
        _mock_mkdir,
        mock_write,
    ):
        mock_get_vars.return_value = {
            "PORT": "8000",
            "STRIPE_SECRET_KEY": "sk_live_test",
            "NODE_ENV": "production",
        }

        result = backup_railway_env_snapshot("svc-123", service_name="stripe-installer", save_to_disk=True)

        self.assertEqual(result["keyCount"], 3)
        self.assertEqual(result["secretKeyCount"], 1)
        self.assertIn("STRIPE_SECRET_KEY", result["secretKeys"])
        self.assertTrue(result["backupPath"])
        mock_write.assert_called_once()
        written = json.loads(mock_write.call_args.args[0])
        self.assertEqual(written["serviceName"], "stripe-installer")
        self.assertEqual(written["variables"]["STRIPE_SECRET_KEY"], "sk_live_test")

    @patch("migrationengine.providers.get_railway_env_vars", return_value={})
    @patch("migrationengine.providers._railway_environment_id", return_value="env-1")
    def test_raises_when_service_has_no_variables(self, _mock_env_id, _mock_get_vars):
        with self.assertRaises(ProviderApiError):
            backup_railway_env_snapshot("svc-empty", save_to_disk=False)
