from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from core.regional import database_host_outside_africa
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
        db_issue = next(issue for issue in report["issues"] if issue["id"] == "regional-data-residency-db")
        self.assertEqual(db_issue["severity"], "medium")

    def test_railway_hostname_is_not_flagged_as_non_africa_db(self):
        self.assertFalse(database_host_outside_africa("postgres://user:pass@db.railway.app:5432/main"))

    @override_settings(DEFAULT_EAST_AFRICA_PROVIDER="orena", DEFAULT_EAST_AFRICA_REGION="ke-1")
    def test_latency_rule_is_not_auto_fixable(self):
        report = analyze_project(
            DiagnosisRequest(
                app_name="demo",
                target_provider="railway",
                files=["package.json"],
                environment={},
                secrets=[],
                target_environment="prod",
                requested_by="tester",
                region="oregon",
            )
        )
        latency_issue = next(issue for issue in report["issues"] if issue["id"] == "regional-latency-us-eu")
        self.assertFalse(latency_issue["autoFixable"])

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
