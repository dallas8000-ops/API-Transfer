from __future__ import annotations

from io import StringIO
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

    def test_to_candidate_accepts_render_repo_and_rootdir_aliases(self):
        service = {
            "id": "srv_alias",
            "name": "frontend",
            "repoUrl": "https://github.com/example/frontend",
            "branch": "main",
        }
        rendered = {
            "id": "srv_alias",
            "name": "frontend",
            "repoUrl": "https://github.com/example/frontend",
            "branch": "main",
            "serviceDetails": {
                "rootDir": "frontend",
                "buildCommand": "npm ci && npm run build",
                "startCommand": "",
            },
        }

        response = type("Response", (), {"status_code": 200, "json": lambda self: rendered})()

        with patch("migrationengine.management.commands.transfer_render_to_railway.requests.get", return_value=response):
            candidate = self.command._to_candidate(self.command._enrich_render_service(service), source="service")

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.repo, "https://github.com/example/frontend")
        self.assertEqual(candidate.root_directory, "frontend")

    def test_to_candidate_logs_discovered_and_missing_render_fields(self):
        service = {
            "id": "srv_log",
            "name": "frontend",
            "branch": "main",
        }
        rendered = {
            "id": "srv_log",
            "name": "frontend",
            "branch": "main",
            "serviceDetails": {
                "rootDir": "frontend",
                "buildCommand": "npm ci && npm run build",
                "startCommand": "",
            },
        }
        response = type("Response", (), {"status_code": 200, "json": lambda self: rendered})()
        self.command.stdout = StringIO()

        with patch("migrationengine.management.commands.transfer_render_to_railway.requests.get", return_value=response):
            candidate = self.command._to_candidate(self.command._enrich_render_service(service), source="service")

        self.assertIsNone(candidate)
        output = self.command.stdout.getvalue()
        self.assertIn("discovered=", output)
        self.assertIn("rootDirectory", output)
        self.assertIn("buildCommand", output)
        self.assertIn("missing=repo,startCommand", output)

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

        _, start_command, _, _ = self.command._derive_deploy_config(item, {})

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

        _, _, merged_env, _ = self.command._derive_deploy_config(item, {})

        self.assertNotIn("RAILPACK_SPA_OUTPUT_DIR", merged_env)

    def test_derive_deploy_config_applies_overrides(self):
        item = TransferCandidate(
            source="service",
            render_id="srv_override",
            name="override-app",
            repo="https://github.com/a/override-app",
            branch="main",
            build_command="npm run old-build",
            start_command="npm run old-start",
            root_directory="old/path",
            service_type="web_service",
            runtime="node",
        )

        build, start, _, root = self.command._derive_deploy_config(
            item,
            {},
            override_root_directory="new/path",
            override_build_command="npm ci && npm run build",
            override_start_command="npm run serve",
        )

        self.assertEqual(build, "npm ci && npm run build")
        self.assertEqual(start, "npm run serve")
        self.assertEqual(root, "new/path")

    def test_force_static_site_drops_start_command(self):
        item = TransferCandidate(
            source="service",
            render_id="srv_force_static",
            name="force-static",
            repo="https://github.com/a/force-static",
            branch="main",
            build_command="npm ci && npm run build",
            start_command="npm run start",
            root_directory="app",
            service_type="web_service",
            runtime="node",
        )

        build, start, env, root = self.command._derive_deploy_config(item, {}, force_static_site=True)

        self.assertEqual(build, "npm ci && npm run build")
        self.assertIsNone(start)
        self.assertEqual(root, "app")
        self.assertIsNone(env.get("RAILPACK_SPA_OUTPUT_DIR"))

    @patch.dict("os.environ", {"VITE_API_URL": "https://api.example.com", "UNRELATED": "x"}, clear=False)
    def test_merge_local_env_vars_by_prefix(self):
        merged = self.command._merge_local_env_vars({"NODE_ENV": "production"}, ["VITE_"])

        self.assertEqual(merged["NODE_ENV"], "production")
        self.assertEqual(merged["VITE_API_URL"], "https://api.example.com")
        self.assertNotIn("UNRELATED", merged)

    @patch.dict("os.environ", {"DATABASE_URL": "postgres://example", "JWT_SECRET_KEY": "secret"}, clear=False)
    def test_merge_local_env_keys_exact_match(self):
        merged = self.command._merge_local_env_keys({"NODE_ENV": "production"}, ["DATABASE_URL", "MISSING_KEY"])

        self.assertEqual(merged["NODE_ENV"], "production")
        self.assertEqual(merged["DATABASE_URL"], "postgres://example")
        self.assertNotIn("MISSING_KEY", merged)

    def test_normalize_service_kind_maps_static_variants(self):
        service_type, runtime = self.command._normalize_service_kind(
            {
                "name": "dbops-web",
                "type": "Static",
                "runtime": "",
                "buildCommand": "npm ci && npm run build",
                "startCommand": "",
            }
        )

        self.assertEqual(service_type, "static_site")
        self.assertEqual(runtime, "node")

    def test_normalize_service_kind_infers_static_when_build_only_frontend(self):
        service_type, runtime = self.command._normalize_service_kind(
            {
                "name": "frontend",
                "type": "",
                "runtime": "",
                "buildCommand": "vite build",
                "startCommand": "",
            }
        )

        self.assertEqual(service_type, "static_site")
        self.assertEqual(runtime, "node")

    def test_normalize_service_kind_infers_python_runtime_from_commands(self):
        service_type, runtime = self.command._normalize_service_kind(
            {
                "name": "kistie-store",
                "type": "web_service",
                "runtime": "",
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": "gunicorn app:app",
            }
        )

        self.assertEqual(service_type, "web_service")
        self.assertEqual(runtime, "python")

    def test_preflight_rejects_internal_render_database_host(self):
        item = TransferCandidate(
            source="service",
            render_id="srv_db",
            name="db-app",
            repo="https://github.com/a/db-app",
            branch="main",
            build_command=None,
            start_command=None,
            root_directory=None,
            service_type="web_service",
            runtime="python",
        )

        errors = self.command._preflight_validate_candidate(
            item,
            {"DATABASE_URL": "postgresql://u:p@dpg-abc123-a/dbname"},
        )

        self.assertTrue(any("internal render host" in e.lower() for e in errors))

    def test_preflight_rejects_render_url_without_sslmode(self):
        item = TransferCandidate(
            source="service",
            render_id="srv_db",
            name="db-app",
            repo="https://github.com/a/db-app",
            branch="main",
            build_command=None,
            start_command=None,
            root_directory=None,
            service_type="web_service",
            runtime="python",
        )

        errors = self.command._preflight_validate_candidate(
            item,
            {"DATABASE_URL": "postgresql://u:p@my-db.oregon-postgres.render.com/dbname"},
        )

        self.assertTrue(any("sslmode=require" in e.lower() for e in errors))

    def test_preflight_detects_djang_typo_keys(self):
        item = TransferCandidate(
            source="service",
            render_id="srv_django",
            name="django-app",
            repo="https://github.com/a/django-app",
            branch="main",
            build_command=None,
            start_command=None,
            root_directory=None,
            service_type="web_service",
            runtime="python",
        )

        errors = self.command._preflight_validate_candidate(
            item,
            {"DJANG_SECRET_KEY": "x", "DJANG_DEBUG": "true"},
        )

        self.assertTrue(any("typo env keys" in e.lower() for e in errors))

    def test_classify_provider_error_external_blocker(self):
        exc = ProviderApiError("railway", 403, "Attention Required! | Cloudflare")

        category = self.command._classify_provider_error(exc)

        self.assertEqual(category, "external-blocker")

    @patch("migrationengine.management.commands.transfer_render_to_railway.get_railway_latest_service_deployment")
    @patch("migrationengine.management.commands.transfer_render_to_railway.get_railway_service_id_by_name")
    def test_filter_failed_only_candidates_skips_green(self, by_name, latest):
        candidates = [
            TransferCandidate("service", "srv_1", "green-app", "https://github.com/a/green", "main", None, None, None, "web_service", "docker"),
            TransferCandidate("service", "srv_2", "red-app", "https://github.com/a/red", "main", None, None, None, "web_service", "docker"),
        ]
        by_name.side_effect = ["svc_green", "svc_red"]
        latest.side_effect = [{"status": "SUCCESS"}, {"status": "FAILED"}]

        remaining, skipped = self.command._filter_failed_only_candidates(candidates, prefix="")

        self.assertEqual([c.name for c in remaining], ["red-app"])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["reason"], "already-green")
