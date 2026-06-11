"""Request-scoped demo mode for safe simulation on public demo links only."""
from __future__ import annotations

from django.conf import settings


def is_demo_request(request) -> bool:
    """True when the caller is on a demo link (path, host, header, or env override)."""
    if getattr(settings, "APP_DEMO_MODE", False):
        return True

    header = (request.headers.get("X-Demo-Mode") or "").strip().lower()
    if header in {"1", "true", "yes"}:
        return True

    query_params = getattr(request, "query_params", None)
    query = (
        request.GET.get("demo")
        or (query_params.get("demo") if query_params is not None else "")
        or ""
    ).strip().lower()
    if query in {"1", "true", "yes"}:
        return True

    path = (request.path or "").lower()
    prefix = (getattr(settings, "DEMO_PATH_PREFIX", "/demo") or "/demo").rstrip("/").lower()
    if prefix and (path == prefix or path.startswith(f"{prefix}/")):
        return True

    host = (request.get_host() or "").split(":")[0].lower()
    demo_hosts = {h.lower() for h in getattr(settings, "DEMO_HOSTS", []) if h}
    if host and host in demo_hosts:
        return True

    return False
