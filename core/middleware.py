"""Adds hardened security response headers (parity with the helmet config)."""
from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; base-uri 'self'; font-src 'self' https: data:; "
    "form-action 'self'; frame-ancestors 'self'; img-src 'self' data:; "
    "object-src 'none'; upgrade-insecure-requests"
)


class SecurityHeadersMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response["Content-Security-Policy"] = CSP
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "SAMEORIGIN"
        response["Referrer-Policy"] = "no-referrer"
        response["Cross-Origin-Opener-Policy"] = "same-origin"
        response["Cross-Origin-Resource-Policy"] = "same-origin"
        return response
