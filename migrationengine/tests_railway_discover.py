from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from migrationengine import adapters


class RailwayDiscoverResolveTests(SimpleTestCase):
    @override_settings(RAILWAY_API_TOKEN="token", RAILWAY_PROJECT_ID="proj-1")
    def test_discover_resolves_service_name_to_id(self):
        with patch(
            "migrationengine.providers.get_railway_service_id_by_name",
            return_value="00000000-0000-4000-8000-000000000001",
        ), patch(
            "migrationengine.adapters._railway_live_snapshot",
            return_value={
                "provider": "railway",
                "appIdentifier": "00000000-0000-4000-8000-000000000001",
                "live": True,
                "raw": {"live": True, "name": "stripe-installer", "environment": {}, "secretKeys": []},
            },
        ):
            result = adapters.discover("railway", "stripe-installer")

        self.assertEqual(result["snapshot"]["appIdentifier"], "00000000-0000-4000-8000-000000000001")
