from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from core.rbac import IsAdmin, IsOperator, IsViewer, _resolve_role


class ResolveRoleTests(SimpleTestCase):
    @override_settings(DEBUG=True, RBAC_ADMIN_KEYS=[], RBAC_OPERATOR_KEYS=[], RBAC_VIEWER_KEYS=[])
    def test_debug_without_key_grants_admin(self):
        self.assertEqual(_resolve_role(""), "admin")

    @override_settings(DEBUG=False, RBAC_ADMIN_KEYS=[], RBAC_OPERATOR_KEYS=[], RBAC_VIEWER_KEYS=[], ON_RAILWAY=False)
    def test_production_without_keys_denies_unauthenticated(self):
        self.assertIsNone(_resolve_role(""))

    @override_settings(DEBUG=False, RBAC_ADMIN_KEYS=[], RBAC_OPERATOR_KEYS=[], RBAC_VIEWER_KEYS=[], ON_RAILWAY=True)
    def test_railway_production_without_keys_denies_unauthenticated(self):
        self.assertIsNone(_resolve_role(""))

    @override_settings(DEBUG=False, RBAC_ADMIN_KEYS=["secret-admin"], RBAC_OPERATOR_KEYS=[], RBAC_VIEWER_KEYS=[])
    def test_production_admin_key_required(self):
        self.assertIsNone(_resolve_role(""))
        self.assertEqual(_resolve_role("secret-admin"), "admin")
        self.assertIsNone(_resolve_role("wrong-key"))

    @override_settings(DEBUG=False, RBAC_ADMIN_KEYS=[], RBAC_OPERATOR_KEYS=["op-key"], RBAC_VIEWER_KEYS=[])
    def test_operator_key_resolves(self):
        self.assertEqual(_resolve_role("op-key"), "operator")


class PermissionClassTests(SimpleTestCase):
    @override_settings(DEBUG=False, RBAC_ADMIN_KEYS=[], RBAC_OPERATOR_KEYS=[], RBAC_VIEWER_KEYS=[])
    def test_is_operator_denies_when_unconfigured_production(self):
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get("/")
        permission = IsOperator()
        self.assertFalse(permission.has_permission(request, None))

    @override_settings(DEBUG=True, RBAC_ADMIN_KEYS=[], RBAC_OPERATOR_KEYS=[], RBAC_VIEWER_KEYS=[])
    def test_is_admin_allows_debug_local(self):
        from rest_framework.test import APIRequestFactory

        request = APIRequestFactory().get("/")
        permission = IsAdmin()
        self.assertTrue(permission.has_permission(request, None))
        self.assertEqual(request.rbac_role, "admin")
