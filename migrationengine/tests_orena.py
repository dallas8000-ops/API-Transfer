from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from migrationengine import adapters


class OrenaAccountReviewTests(SimpleTestCase):
    @override_settings(ORENA_API_TOKEN="orena-token", ORENA_DEFAULT_REGION="ke-1")
    def test_review_account_lists_apps_without_secret_values(self):
        services = [
            {
                "id": "app_1",
                "name": "nairobi-api",
                "region": "ke-1",
                "branch": "main",
                "repoUrl": "https://github.com/example/nairobi-api",
            }
        ]
        env_vars = {"NODE_ENV": "production", "API_KEY": "hidden"}

        with patch("migrationengine.providers.list_orena_apps", return_value=services), patch(
            "migrationengine.providers.get_orena_env_vars", return_value=env_vars
        ):
            result = adapters.review_account("orena")

        self.assertTrue(result["live"])
        self.assertEqual(result["apps"][0]["secretKeys"], ["API_KEY"])
        self.assertNotIn("hidden", str(result))
