from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from diagnostics.engine import DiagnosisRequest, analyze_project


class RegionalComplianceTests(SimpleTestCase):
    @override_settings(DEFAULT_EAST_AFRICA_PROVIDER="orena", DEFAULT_EAST_AFRICA_REGION="ke-1")
    def test_flags_us_region_for_prod_east_africa_migration(self):
        report = analyze_project(
            DiagnosisRequest(
                app_name="demo",
                target_provider="railway",
                files=["package.json"],
                environment={"DATABASE_URL": "postgres://db.us-east-1.rds.amazonaws.com/main"},
                secrets=[],
                target_environment="prod",
                requested_by="tester",
                region="oregon",
                domains=[{"host": "app.example.com", "tlsRequired": True}],
            )
        )
        issue_ids = {issue["id"] for issue in report["issues"]}
        self.assertIn("regional-latency-us-eu", issue_ids)
        self.assertIn("regional-data-residency-db", issue_ids)

    @override_settings(DEFAULT_EAST_AFRICA_PROVIDER="orena", DEFAULT_EAST_AFRICA_REGION="ke-1")
    def test_orena_ke1_region_passes_latency_check(self):
        report = analyze_project(
            DiagnosisRequest(
                app_name="demo",
                target_provider="orena",
                files=["package.json"],
                environment={},
                secrets=[],
                target_environment="prod",
                requested_by="tester",
                region="ke-1",
            )
        )
        issue_ids = {issue["id"] for issue in report["issues"]}
        self.assertNotIn("regional-latency-us-eu", issue_ids)
        self.assertNotIn("orena-non-africa-region", issue_ids)
