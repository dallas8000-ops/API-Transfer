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

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# Load `.env` into os.environ so local provider credentials are picked up without
# manually exporting variables before `runserver`.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


# --- Core ------------------------------------------------------------------
DEBUG = _env_bool("DJANGO_DEBUG", default=True)

# Demo / test mode is only for public demo links (`/demo/*`, `X-Demo-Mode`, or DEMO_HOSTS).
# Normal console access always runs live when provider credentials are configured.
APP_DEMO_MODE = _env_bool("APP_DEMO_MODE", default=False)
DEMO_PATH_PREFIX = os.environ.get("DEMO_PATH_PREFIX", "/demo")
DEMO_HOSTS = _env_list("DEMO_HOSTS")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is required.")

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS") or (["*"] if DEBUG else [])

RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
ON_RAILWAY = bool(
    os.environ.get("RAILWAY_ENVIRONMENT")
    or os.environ.get("RAILWAY_PROJECT_ID")
    or RAILWAY_PUBLIC_DOMAIN
)
if ON_RAILWAY:
    for _host in (".railway.app", ".up.railway.app"):
        if _host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_host)
    if RAILWAY_PUBLIC_DOMAIN and RAILWAY_PUBLIC_DOMAIN not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)

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
    "billing",
    "licenses",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "apitransfer.urls"

# The React SPA is built into ``frontend_dist`` (see frontend/vite.config.ts).
# When present, Django serves its index.html as the app shell and its hashed
# assets via the staticfiles finder. The legacy ``public`` UI remains available
# as a fallback when the SPA has not been built yet.
FRONTEND_DIST = BASE_DIR / "frontend_dist"
SPA_INDEX = FRONTEND_DIST / "index.html"
SPA_BUILT = SPA_INDEX.exists()

_template_dirs = [BASE_DIR / "public"]
if SPA_BUILT:
    _template_dirs.insert(0, FRONTEND_DIST)

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": _template_dirs,
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

WSGI_APPLICATION = "apitransfer.wsgi.application"
ASGI_APPLICATION = "apitransfer.asgi.application"

_database_url = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
_database_parse_kwargs: dict = {"conn_max_age": 600}
if not _database_url.startswith("sqlite"):
    if _database_url.startswith("postgres://"):
        _database_url = "postgresql://" + _database_url[len("postgres://") :]
    # Railway private Postgres (*.railway.internal) does not use the same SSL path as public URLs.
    if "railway.internal" in _database_url:
        if "sslmode=" not in _database_url:
            _database_url += "&sslmode=disable" if "?" in _database_url else "?sslmode=disable"
        _database_parse_kwargs["ssl_require"] = False
    elif "railway" in _database_url:
        if "sslmode=" not in _database_url:
            _database_url += "&sslmode=require" if "?" in _database_url else "?sslmode=require"
        _database_parse_kwargs["ssl_require"] = not DEBUG
    else:
        _database_parse_kwargs["ssl_require"] = not DEBUG

DATABASES = {
    "default": dj_database_url.parse(
        _database_url,
        **_database_parse_kwargs,
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Static / UI -----------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "public"]
if SPA_BUILT:
    # Vite is configured with base="/static/", so the built index.html requests
    # assets at /static/assets/*. The files themselves live in frontend_dist/assets,
    # so frontend_dist is registered as a static root to serve them at /static/.
    STATICFILES_DIRS.insert(0, FRONTEND_DIST)
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

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

RENDER_API_TOKEN = os.environ.get("RENDER_API_TOKEN", "")
RENDER_API_BASE_URL = os.environ.get("RENDER_API_BASE_URL", "https://api.render.com")
RENDER_OWNER_ID = os.environ.get("RENDER_OWNER_ID", "")
RENDER_DEFAULT_REGION = os.environ.get("RENDER_DEFAULT_REGION", "oregon")
RENDER_DEFAULT_PLAN = os.environ.get("RENDER_DEFAULT_PLAN", "starter")

RAILWAY_API_TOKEN = os.environ.get("RAILWAY_API_TOKEN", "")
RAILWAY_API_BASE_URL = os.environ.get("RAILWAY_API_BASE_URL", "https://backboard.railway.app")
RAILWAY_PROJECT_ID = os.environ.get("RAILWAY_PROJECT_ID", "")

SUPABASE_ACCESS_TOKEN = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
SUPABASE_API_BASE_URL = os.environ.get("SUPABASE_API_BASE_URL", "https://api.supabase.com")
SUPABASE_ORG_ID = os.environ.get("SUPABASE_ORG_ID", "")
SUPABASE_DEFAULT_REGION = os.environ.get("SUPABASE_DEFAULT_REGION", "us-east-1")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_API_BASE_URL = os.environ.get("STRIPE_API_BASE_URL", "https://api.stripe.com")

# --- Self-subscription billing (the platform's own Stripe billing) ---------
# Publishable key is safe to expose to the browser; the others are secret.
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
# Stripe Price IDs for each paid tier (create them in the Stripe dashboard).
STRIPE_PRICE_PRO = os.environ.get("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_SCALE = os.environ.get("STRIPE_PRICE_SCALE", "")
BILLING_CURRENCY = os.environ.get("BILLING_CURRENCY", "usd")
# Where Stripe Checkout redirects after success/cancel.
BILLING_SUCCESS_URL = os.environ.get(
    "BILLING_SUCCESS_URL", "http://localhost:8000/billing/success?session_id={CHECKOUT_SESSION_ID}"
)
BILLING_CANCEL_URL = os.environ.get("BILLING_CANCEL_URL", "http://localhost:8000/pricing")

CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")
CLOUDFLARE_ZONE_ID = os.environ.get("CLOUDFLARE_ZONE_ID", "")
CLOUDFLARE_API_BASE_URL = os.environ.get(
    "CLOUDFLARE_API_BASE_URL", "https://api.cloudflare.com/client/v4"
)
DEPLOY_DNS_TARGET = os.environ.get("DEPLOY_DNS_TARGET", "203.0.113.10")

GITHUB_API_BASE_URL = os.environ.get("GITHUB_API_BASE_URL", "https://api.github.com")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# --- Transfer queue / worker policy ---------------------------------------
TRANSFER_WORKER_LIMIT = max(1, _env_int("TRANSFER_WORKER_LIMIT", 5))
TRANSFER_WORKER_POLL_INTERVAL_SECONDS = max(1, _env_int("TRANSFER_WORKER_POLL_INTERVAL_SECONDS", 5))
TRANSFER_WORKER_LEASE_TTL_SECONDS = max(30, _env_int("TRANSFER_WORKER_LEASE_TTL_SECONDS", 120))
TRANSFER_WORKER_HEARTBEAT_INTERVAL_SECONDS = max(3, _env_int("TRANSFER_WORKER_HEARTBEAT_INTERVAL_SECONDS", 15))
TRANSFER_WORKSPACE_CONCURRENCY_CAP = max(1, _env_int("TRANSFER_WORKSPACE_CONCURRENCY_CAP", 1))
TRANSFER_QUEUE_AGING_WINDOW_SECONDS = max(1, _env_int("TRANSFER_QUEUE_AGING_WINDOW_SECONDS", 300))
TRANSFER_QUEUE_MAX_AGING_BOOST = max(0, _env_int("TRANSFER_QUEUE_MAX_AGING_BOOST", 10))
TRANSFER_ALERT_DEAD_LETTER_THRESHOLD = max(0, _env_int("TRANSFER_ALERT_DEAD_LETTER_THRESHOLD", 5))
TRANSFER_ALERT_RETRYABLE_THRESHOLD = max(0, _env_int("TRANSFER_ALERT_RETRYABLE_THRESHOLD", 10))
TRANSFER_ALERT_STALE_LEASE_THRESHOLD = max(0, _env_int("TRANSFER_ALERT_STALE_LEASE_THRESHOLD", 1))

# --- Logging ---------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
