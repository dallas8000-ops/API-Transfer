/** East Africa .env template — bundled so copy works without API permissions. */
export const EAST_AFRICA_ENV_TEMPLATE = `# =============================================================================
# API Transfer — East Africa preparation template
# =============================================================================
# WHERE: Copy into your project .env file (same folder as manage.py)
# WHEN:  Before your first client — no clients required
# AFTER: Restart Django → http://localhost:8000/console
# =============================================================================

# --- Core (required) ---------------------------------------------------------
DJANGO_SECRET_KEY=
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
VAULT_MASTER_KEY_BASE64=
DATABASE_URL=sqlite:///db.sqlite3

# --- East Africa regional defaults -------------------------------------------
DEFAULT_EAST_AFRICA_PROVIDER=orena
DEFAULT_EAST_AFRICA_REGION=ke-1

# --- Paystack (KES + M-Pesa) — dashboard.paystack.com (TEST mode first) -------
PAYSTACK_SECRET_KEY=sk_test_
PAYSTACK_PUBLIC_KEY=pk_test_
PAYSTACK_CURRENCY=KES
PAYSTACK_PLAN_PRO=PLN_
PAYSTACK_PLAN_SCALE=PLN_
PAYSTACK_CALLBACK_URL=http://localhost:8000/billing/success?reference={reference}
PAYSTACK_API_BASE_URL=https://api.paystack.co

# --- Orena Cloud (Nairobi) — orenacloud.com ---------------------------------
ORENA_API_TOKEN=
ORENA_API_BASE_URL=https://api.orenacloud.com/v1
ORENA_PROJECT_ID=
ORENA_DEFAULT_REGION=ke-1

# --- Stripe USD (optional) — dashboard.stripe.com -----------------------------
STRIPE_SECRET_KEY=sk_test_
STRIPE_PUBLISHABLE_KEY=pk_test_
STRIPE_WEBHOOK_SECRET=whsec_
STRIPE_PRICE_PRO=price_
STRIPE_PRICE_SCALE=price_
BILLING_CURRENCY=usd
BILLING_SUCCESS_URL=http://localhost:8000/billing/success?session_id={CHECKOUT_SESSION_ID}
BILLING_CANCEL_URL=http://localhost:8000/pricing

# --- Source hosts (optional — migrating FROM US PaaS) -------------------------
RAILWAY_API_TOKEN=
RAILWAY_PROJECT_ID=
RENDER_API_TOKEN=
RENDER_OWNER_ID=

# --- RBAC (leave empty for local dev — no API key required) -----------------
RBAC_ADMIN_KEYS=
RBAC_OPERATOR_KEYS=
RBAC_VIEWER_KEYS=
`;
