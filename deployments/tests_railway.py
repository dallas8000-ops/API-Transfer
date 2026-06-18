from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from deployments.framework_detector import DetectedFramework
from deployments.railway_gql_test_router import railway_gql_test_router
from deployments.stages import stage_deploy_app
from migrationengine.providers import _parse_github_repo, get_railway_deployment


class RailwayDeploymentStageTests(SimpleTestCase):
    @override_settings(RAILWAY_API_TOKEN="", RAILWAY_PROJECT_ID="")
    def test_railway_without_credentials_stays_simulated(self):
        request = {
            "appName": "demo",
            "targetProvider": "railway",
            "environment": {},
        }
        framework = DetectedFramework("express", "node", 3000, 90, "npm install", "node server.js")

        result = stage_deploy_app(request, framework)

        self.assertEqual(result["status"], "succeeded")
        self.assertFalse(result["data"]["live"])
        self.assertEqual(result["data"]["hostname"], "demo.railway.app")

    @override_settings(
        RAILWAY_API_TOKEN="railway-token",
        RAILWAY_PROJECT_ID="proj_123",
        RAILWAY_API_BASE_URL="https://backboard.railway.test/graphql/v2",
    )
    def test_railway_live_deploy_creates_service_connects_repo_and_triggers_deploy(self):
        request = {
            "appName": "demo",
            "targetProvider": "railway",
            "repoUrl": "https://github.com/example/demo",
            "branch": "main",
            "environment": {"NODE_ENV": "production"},
        }
        framework = DetectedFramework("express", "node", 3000, 90, "npm install", "node server.js")

        with patch(
            "migrationengine.providers._railway_gql",
            side_effect=lambda query, variables=None: railway_gql_test_router(query, variables),
        ) as gql:
            result = stage_deploy_app(request, framework)

        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["data"]["live"])
        self.assertEqual(result["data"]["provider"], "railway")
        self.assertEqual(result["data"]["serviceId"], "svc_123")
        self.assertEqual(result["data"]["deployId"], "dep_123")
        self.assertEqual(result["data"]["hostname"], "demo.up.railway.app")
        self.assertGreaterEqual(gql.call_count, 6)

    @override_settings(
        RAILWAY_API_TOKEN="railway-token",
        RAILWAY_PROJECT_ID="proj_123",
        RAILWAY_API_BASE_URL="https://backboard.railway.test/graphql/v2",
    )
    def test_railway_live_deploy_handles_object_deploy_payload(self):
        request = {
            "appName": "demo",
            "targetProvider": "railway",
            "repoUrl": "https://github.com/example/demo",
            "branch": "main",
            "environment": {"NODE_ENV": "production"},
        }
        framework = DetectedFramework("express", "node", 3000, 90, "npm install", "node server.js")

        with patch(
            "migrationengine.providers._railway_gql",
            side_effect=lambda query, variables=None: railway_gql_test_router(
                query, variables, deploy_payload={"id": "dep_123"}
            ),
        ):
            result = stage_deploy_app(request, framework)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["data"]["deployId"], "dep_123")
        self.assertEqual(result["data"]["serviceId"], "svc_123")

    @override_settings(RAILWAY_API_TOKEN="railway-token", RAILWAY_API_BASE_URL="https://backboard.railway.test/graphql/v2")
    def test_get_railway_deployment_returns_status_payload(self):
        with patch(
            "migrationengine.providers._railway_gql",
            side_effect=lambda query, variables=None: railway_gql_test_router(query, variables),
        ) as gql:
            result = get_railway_deployment("dep_123")

        self.assertEqual(result["id"], "dep_123")
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["updatedAt"], "2026-06-07T17:00:00Z")
        gql.assert_called_once()

    def test_parse_github_repo_accepts_url_and_slug(self):
        self.assertEqual(_parse_github_repo("https://github.com/example/demo"), "example/demo")
        self.assertEqual(_parse_github_repo("example/demo"), "example/demo")
