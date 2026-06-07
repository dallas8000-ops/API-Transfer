"""
Django settings for the API Transfer platform.

Security-sensitive values are read from environment variables. In development a
random fallback is generated for the vault master key; in production the
VAULT_MASTER_KEY_BASE64 and DJANGO_SECRET_KEY variables are required.
"""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


# --- Core ------------------------------------------------------------------
DEBUG = _env_bool("DJANGO_DEBUG", default=True)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is false.")
    SECRET_KEY = "dev-insecure-" + secrets.token_urlsafe(32)

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS") or (["*"] if DEBUG else [])

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "core",
    "diagnostics",
    "migrationengine",
    "deployments",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "apitransfer.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "public"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

WSGI_APPLICATION = "apitransfer.wsgi.application"
ASGI_APPLICATION = "apitransfer.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Static / UI -----------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "public"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- DRF -------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["core.rbac.IsViewer"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
}

# --- CORS ------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = _env_list("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_ALL_ORIGINS = DEBUG and not CORS_ALLOWED_ORIGINS

# --- Secret vault ----------------------------------------------------------
def _load_master_key() -> bytes:
    raw = os.environ.get("VAULT_MASTER_KEY_BASE64")
    if raw:
        key = base64.b64decode(raw)
        if len(key) != 32:
            raise RuntimeError("VAULT_MASTER_KEY_BASE64 must decode to exactly 32 bytes.")
        return key
    if not DEBUG:
        raise RuntimeError("VAULT_MASTER_KEY_BASE64 is required in production.")
    return secrets.token_bytes(32)


VAULT_MASTER_KEY = _load_master_key()

# --- RBAC ------------------------------------------------------------------
RBAC_ADMIN_KEYS = _env_list("RBAC_ADMIN_KEYS")
RBAC_OPERATOR_KEYS = _env_list("RBAC_OPERATOR_KEYS")
RBAC_VIEWER_KEYS = _env_list("RBAC_VIEWER_KEYS")

# --- Provider integration credentials --------------------------------------
FLY_API_TOKEN = os.environ.get("FLY_API_TOKEN", "")
FLY_API_BASE_URL = os.environ.get("FLY_API_BASE_URL", "https://api.machines.dev")
FLY_ORG_SLUG = os.environ.get("FLY_ORG_SLUG", "personal")

SUPABASE_ACCESS_TOKEN = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
SUPABASE_API_BASE_URL = os.environ.get("SUPABASE_API_BASE_URL", "https://api.supabase.com")
SUPABASE_ORG_ID = os.environ.get("SUPABASE_ORG_ID", "")
SUPABASE_DEFAULT_REGION = os.environ.get("SUPABASE_DEFAULT_REGION", "us-east-1")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_API_BASE_URL = os.environ.get("STRIPE_API_BASE_URL", "https://api.stripe.com")

CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ZONE_ID = os.environ.get("CLOUDFLARE_ZONE_ID", "")
CLOUDFLARE_API_BASE_URL = os.environ.get(
    "CLOUDFLARE_API_BASE_URL", "https://api.cloudflare.com/client/v4"
)
DEPLOY_DNS_TARGET = os.environ.get("DEPLOY_DNS_TARGET", "203.0.113.10")

# --- Logging ---------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
