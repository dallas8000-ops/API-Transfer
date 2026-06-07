"""Role-based access control via the X-API-Key header.

Roles are ordered viewer < operator < admin. Keys are configured per role in
settings (from environment). In development, when no keys are configured at all,
requests default to admin to keep local iteration friction-free; in production an
unconfigured RBAC set denies access.
"""
from __future__ import annotations

from django.conf import settings
from rest_framework import permissions

ROLE_ORDER = {"viewer": 1, "operator": 2, "admin": 3}


def _resolve_role(api_key: str) -> str | None:
    if api_key and api_key in settings.RBAC_ADMIN_KEYS:
        return "admin"
    if api_key and api_key in settings.RBAC_OPERATOR_KEYS:
        return "operator"
    if api_key and api_key in settings.RBAC_VIEWER_KEYS:
        return "viewer"

    any_configured = bool(
        settings.RBAC_ADMIN_KEYS or settings.RBAC_OPERATOR_KEYS or settings.RBAC_VIEWER_KEYS
    )
    if not any_configured and settings.DEBUG:
        return "admin"
    return None


def actor_label(role: str, api_key: str) -> str:
    prefix = api_key[:6] if api_key else "anon"
    return f"{role}:{prefix}"


class _MinimumRole(permissions.BasePermission):
    minimum = "viewer"

    def has_permission(self, request, view) -> bool:
        api_key = request.headers.get("X-API-Key", "")
        role = _resolve_role(api_key)
        if role is None:
            return False
        if ROLE_ORDER[role] < ROLE_ORDER[self.minimum]:
            return False
        request.rbac_role = role
        request.rbac_actor = actor_label(role, api_key)
        return True


class IsViewer(_MinimumRole):
    minimum = "viewer"


class IsOperator(_MinimumRole):
    minimum = "operator"


class IsAdmin(_MinimumRole):
    minimum = "admin"
