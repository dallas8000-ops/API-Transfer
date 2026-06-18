from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from deployments.framework_detector import DetectedFramework
from deployments.stages import _hydrate_deploy_environment


class SecureDeployEnvironmentTests(SimpleTestCase):
    def test_hydrate_deploy_environment_merges_discovery_vault_secrets(self):
        request = {
            "environment": {"NODE_ENV": "production"},
            "discoveryId": "disc-123",
            "secrets": [],
        }
        with patch(
            "deployments.stages.hydrate_service_secrets",
            return_value={"API_KEY": "hidden-value"},
        ):
            env = _hydrate_deploy_environment(request)

        self.assertEqual(env["NODE_ENV"], "production")
        self.assertEqual(env["API_KEY"], "hidden-value")

    @override_settings(
        RAILWAY_API_TOKEN="railway-token",
        RAILWAY_PROJECT_ID="proj_123",
        RAILWAY_API_BASE_URL="https://backboard.railway.test/graphql/v2",
    )
    def test_railway_deploy_uses_hydrated_secrets_without_client_plaintext(self):
        from deployments.stages import stage_deploy_app

        request = {
            "appName": "demo",
            "targetProvider": "railway",
            "repoUrl": "https://github.com/example/demo",
            "branch": "main",
            "environment": {"NODE_ENV": "production"},
            "secrets": [],
            "discoveryId": "disc-123",
        }
        framework = DetectedFramework("express", "node", 3000, 90, "npm install", "node server.js")
        gql_responses = [
            {"project": {"environments": {"edges": [{"node": {"id": "env_123"}}]}}},
            {"serviceCreate": {"id": "svc_123"}},
            {"serviceConnect": {"id": "svc_123"}},
            {},
            {"variables": {}},
            {},
            {"serviceInstanceDeployV2": "dep_123"},
            {"serviceDomainCreate": {"domain": "demo.up.railway.app"}},
        ]

        with patch("deployments.stages.hydrate_service_secrets", return_value={"API_KEY": "hidden-value"}) as hydrate, patch(
            "migrationengine.providers._railway_gql", side_effect=gql_responses
        ) as gql:
            result = stage_deploy_app(request, framework)

        hydrate.assert_called_once_with("disc-123")
        variable_call = gql.call_args_list[5]
        self.assertEqual(variable_call.args[1]["input"]["variables"]["API_KEY"], "hidden-value")
        self.assertEqual(result["data"]["live"], True)
