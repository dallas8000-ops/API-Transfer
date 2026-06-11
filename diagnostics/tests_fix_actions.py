from __future__ import annotations

from django.test import SimpleTestCase

from diagnostics.views import _railway_transfer_actions


class RailwayTransferActionsTests(SimpleTestCase):
    def test_defaults_include_queue_and_demand_commands(self):
        project = {"targetProvider": "railway", "appName": "specwright-api"}

        actions = _railway_transfer_actions(project, None)

        self.assertTrue(actions["enabled"])
        self.assertIn("--mode queue", actions["commands"]["queue"])
        self.assertIn("--mode demand", actions["commands"]["demand"])
        self.assertIn("--only specwright-api", actions["commands"]["demand"])

    def test_custom_transfer_options_are_reflected(self):
        project = {"targetProvider": "render", "appName": "demo"}
        transfer = {
            "mode": "demand",
            "only": ["BLOG-2", "dbops-api"],
            "redeployExisting": True,
            "verify": False,
            "verifyTimeout": 90,
            "verifyInterval": 5,
            "serviceTimeout": 60,
            "allowOverlap": True,
            "dryRun": True,
        }

        actions = _railway_transfer_actions(project, transfer)
        demand = actions["commands"]["demand"]

        self.assertEqual(actions["recommendedMode"], "demand")
        self.assertIn("--redeploy-existing", demand)
        self.assertIn("--no-verify", demand)
        self.assertIn("--allow-overlap", demand)
        self.assertIn("--dry-run", demand)
        self.assertIn("--only BLOG-2", demand)
        self.assertIn("--only dbops-api", demand)

    def test_build_only_package_infers_static_site_transfer(self):
        project = {
            "targetProvider": "railway",
            "appName": "FrontLineDigital",
            "packageJson": {"scripts": {"build": "npm run build"}},
        }

        actions = _railway_transfer_actions(project, None)

        self.assertIn("--force-static-site", actions["commands"]["queue"])
        self.assertIn("--force-static-site", actions["commands"]["demand"])
