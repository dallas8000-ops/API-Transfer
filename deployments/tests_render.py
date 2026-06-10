from __future__ import annotations

from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from deployments.framework_detector import DetectedFramework
from deployments.stages import stage_deploy_app
from migrationengine.providers import get_render_deploy


class RenderDeploymentStageTests(SimpleTestCase):
    @override_settings(RENDER_API_TOKEN="", RENDER_OWNER_ID="")
    def test_render_without_credentials_stays_simulated(self):
        request = {
            "appName": "demo",
            "targetProvider": "render",
            "environment": {},
        }
        framework = DetectedFramework("express", "node", 3000, 90, "npm install", "node server.js")

        result = stage_deploy_app(request, framework)

        self.assertEqual(result["status"], "succeeded")
        self.assertFalse(result["data"]["live"])
        self.assertEqual(result["data"]["hostname"], "demo.render.app")

    @override_settings(
        RENDER_API_TOKEN="render-token",
        RENDER_OWNER_ID="owner-id",
        RENDER_API_BASE_URL="https://api.render.test",
        RENDER_DEFAULT_REGION="oregon",
        RENDER_DEFAULT_PLAN="starter",
    )
    def test_render_live_deploy_creates_service_sets_env_and_triggers_deploy(self):
        request = {
            "appName": "demo",
            "targetProvider": "render",
            "repoUrl": "https://github.com/example/demo",
            "branch": "main",
            "environment": {"NODE_ENV": "production"},
            "region": "oregon",
        }
        framework = DetectedFramework("express", "node", 3000, 90, "npm install", "node server.js")
        responses = [
            _response({"id": "srv_123", "serviceDetails": {"url": "https://demo.onrender.com"}}),
            _response([{"key": "NODE_ENV"}]),
            _response({"id": "dep_123"}),
        ]

        with patch("requests.post", side_effect=[responses[0], responses[2]]) as post, patch(
            "requests.put", return_value=responses[1]
        ) as put:
            result = stage_deploy_app(request, framework)

        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["data"]["live"])
        self.assertEqual(result["data"]["provider"], "render")
        self.assertEqual(result["data"]["serviceId"], "srv_123")
        self.assertEqual(result["data"]["deployId"], "dep_123")
        self.assertEqual(result["data"]["hostname"], "demo.onrender.com")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(put.call_count, 1)

    @override_settings(RENDER_API_TOKEN="render-token", RENDER_API_BASE_URL="https://api.render.test")
    def test_get_render_deploy_returns_status_payload(self):
        with patch(
            "requests.get",
            return_value=_response({"id": "dep_123", "status": "live", "finishedAt": "2026-06-07T17:00:00Z"}, 200),
        ) as get:
            result = get_render_deploy("srv_123", "dep_123")

        self.assertEqual(result["id"], "dep_123")
        self.assertEqual(result["status"], "live")
        self.assertEqual(result["finishedAt"], "2026-06-07T17:00:00Z")
        self.assertIn("/v1/services/srv_123/deploys/dep_123", get.call_args.args[0])


def _response(payload, status_code: int = 201):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.text = str(payload)
    return response
