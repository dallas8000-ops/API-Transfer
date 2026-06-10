from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase

from migrationengine.management.commands.transfer_render_to_railway import Command
from migrationengine.management.commands.transfer_render_to_railway import TransferCandidate
from migrationengine.providers import ProviderApiError


class TransferCommandVerificationTests(SimpleTestCase):
    def setUp(self):
        self.command = Command()

    @patch("migrationengine.management.commands.transfer_render_to_railway.wait_for_railway_deployment")
    def test_verify_marks_failed_for_failed_status(self, wait_for):
        wait_for.return_value = {
            "id": "dep_123",
            "status": "FAILED",
            "diagnosis": "No start command detected",
            "timedOut": False,
            "terminal": True,
        }

        result = self.command._verify_result({"deployId": "dep_123"}, timeout_seconds=60, interval_seconds=5)

        self.assertTrue(result.get("failed"))
        self.assertIn("No start command detected", result.get("error", ""))

    @patch("migrationengine.management.commands.transfer_render_to_railway.wait_for_railway_deployment")
    def test_verify_warns_on_timeout(self, wait_for):
        wait_for.return_value = {
            "id": "dep_123",
            "status": "QUEUED",
            "timedOut": True,
            "terminal": False,
        }

        result = self.command._verify_result({"deployId": "dep_123"}, timeout_seconds=60, interval_seconds=5)

        self.assertIn("timeout", (result.get("warning") or "").lower())

    @patch("migrationengine.management.commands.transfer_render_to_railway.wait_for_railway_deployment")
    def test_verify_warns_when_status_check_errors(self, wait_for):
        wait_for.side_effect = ProviderApiError("railway", 502, "gateway timeout")

        result = self.command._verify_result({"deployId": "dep_123"}, timeout_seconds=60, interval_seconds=5)

        self.assertIn("could not verify", (result.get("warning") or "").lower())

    def test_verify_warns_without_deploy_id(self):
        result = self.command._verify_result({}, timeout_seconds=60, interval_seconds=5)

        self.assertIn("no deployment id", (result.get("warning") or "").lower())

    def test_verify_strict_fails_without_deploy_id(self):
        result = self.command._verify_result({}, timeout_seconds=60, interval_seconds=5, strict=True)

        self.assertTrue(result.get("failed"))
        self.assertIn("no deployment id", (result.get("error") or "").lower())

    @patch("migrationengine.management.commands.transfer_render_to_railway.wait_for_railway_deployment")
    def test_verify_strict_fails_on_timeout(self, wait_for):
        wait_for.return_value = {
            "id": "dep_123",
            "status": "QUEUED",
            "timedOut": True,
            "terminal": False,
        }

        result = self.command._verify_result({"deployId": "dep_123"}, timeout_seconds=60, interval_seconds=5, strict=True)

        self.assertTrue(result.get("failed"))
        self.assertIn("timeout", (result.get("error") or "").lower())

    def test_parse_only_values_supports_repeat_and_csv(self):
        values = self.command._parse_only_values(["specwright-api, BLOG-2", "dbops-api"])

        self.assertEqual(values, {"specwright-api", "blog-2", "dbops-api"})

    def test_filter_candidates_matches_by_name_or_render_id(self):
        candidates = [
            TransferCandidate("service", "srv_1", "specwright-api", "https://github.com/a/b", "main", None, None, None, "web_service", "docker"),
            TransferCandidate("service", "srv_2", "dbops-api", "https://github.com/a/c", "main", None, None, None, "web_service", "docker"),
        ]

        filtered, unmatched = self.command._filter_candidates(candidates, {"specwright-api", "srv_2", "missing"})

        self.assertEqual([c.name for c in filtered], ["specwright-api", "dbops-api"])
        self.assertEqual(unmatched, ["missing"])

    def test_derive_deploy_config_python_fallback_is_broader(self):
        item = TransferCandidate(
            source="service",
            render_id="srv_py",
            name="python-app",
            repo="https://github.com/a/python-app",
            branch="main",
            build_command=None,
            start_command=None,
            root_directory=None,
            service_type="web_service",
            runtime="python",
        )

        _, start_command, _ = self.command._derive_deploy_config(item, {})

        self.assertIn("gunicorn", start_command or "")
        self.assertIn("uvicorn", start_command or "")

    def test_static_output_dir_not_forced_for_unknown_build(self):
        item = TransferCandidate(
            source="service",
            render_id="srv_static",
            name="static-app",
            repo="https://github.com/a/static-app",
            branch="main",
            build_command="npm install && npm run build",
            start_command=None,
            root_directory=None,
            service_type="static_site",
            runtime=None,
        )

        _, _, merged_env = self.command._derive_deploy_config(item, {})

        self.assertNotIn("RAILPACK_SPA_OUTPUT_DIR", merged_env)
