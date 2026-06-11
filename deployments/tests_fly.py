from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from deployments.framework_detector import DetectedFramework
from deployments.stages import stage_deploy_app
from migrationengine.providers import ProviderApiError


class FlyDeploymentStageTests(SimpleTestCase):
    @override_settings(FLY_API_TOKEN="")
    def test_fly_without_credentials_stays_simulated(self):
        request = {
            "appName": "demo",
            "targetProvider": "fly",
            "environment": {},
        }
        framework = DetectedFramework("express", "node", 3000, 90, "npm install", "node server.js")

        result = stage_deploy_app(request, framework)

        self.assertEqual(result["status"], "succeeded")
        self.assertFalse(result["data"]["live"])
        self.assertEqual(result["data"]["hostname"], "demo.fly.app")

    @override_settings(FLY_API_TOKEN="bad-token", DEBUG=True)
    def test_fly_live_error_falls_back_to_simulated_in_debug(self):
        request = {
            "appName": "demo",
            "targetProvider": "fly",
            "environment": {},
        }
        framework = DetectedFramework("nextjs", "node", 3000, 99, "npm run build", "npm run start")

        with patch("migrationengine.providers.deploy_fly_app", side_effect=ProviderApiError("fly", 401, "bad token")):
            result = stage_deploy_app(request, framework)

        self.assertEqual(result["status"], "succeeded")
        self.assertFalse(result["data"]["live"])
        self.assertEqual(result["data"]["hostname"], "demo.fly.app")
        self.assertIn("after live provider error", result["detail"])