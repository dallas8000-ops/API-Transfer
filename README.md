# API Transfer (Secure AI-Assisted Migration & Deployment)

A Django + Django REST Framework platform that plans and applies provider
migrations and automated deployments with minimal manual intervention, while
protecting secrets and enforcing integrity end to end. It also includes an
AI-assisted project diagnostics engine that detects and auto-fixes
misconfigurations across multiple runtimes.

The product UI is a **React + Vite + TypeScript** single-page app served by
Django, including a public pricing page and **self-service subscription billing**
powered by Stripe.

> The original Node/TypeScript implementation was removed from the working tree
> and is preserved in git history at the `node-legacy-v1` tag
> (`git checkout node-legacy-v1`).

## Supported Provider Adapters

- Render (account review + live discovery when `RENDER_API_TOKEN` is configured; live deploy also needs `RENDER_OWNER_ID`)
- Railway (account review + live deploy when `RAILWAY_API_TOKEN` and `RAILWAY_PROJECT_ID` are configured)
- Fly.io (live discovery + deploy when credentials are configured)
- Kong Gateway
- Terraform (deterministic plan/apply with drift detection)
- Supabase (live database provisioning when credentials are configured)

## Security + Integrity Built In

- Secrets encrypted with **AES-256-GCM** before plan storage; plaintext is never
  returned or logged.
- Recursive sensitive-field redaction on every response and audit payload.
- SHA-256 plan/result **integrity hashing**, re-verified before apply.
- Tamper-evident **audit hash-chain** (`verify_chain` detects any edit/deletion).
- Policy engine blocks unsafe migrations; apply requires an approval identity.
- **RBAC** via `X-API-Key` header with `viewer < operator < admin` roles.
- Hardened security headers (CSP, X-Frame-Options, COOP/CORP, etc.).

## Quick Start

1. Create and activate a virtual environment, then install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Copy the environment file and set a 32-byte base64 vault key:

```powershell
Copy-Item .env.example .env
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
# paste the value into VAULT_MASTER_KEY_BASE64 in .env
```

3. Apply migrations and run the server:

```powershell
python manage.py migrate
$env:DJANGO_DEBUG="1"; python manage.py runserver 8000
```

4. Open the UI and health check:

- Web UI: `http://localhost:8000/`
- Health: `GET http://localhost:8000/health`

In development, when no RBAC keys are configured, requests default to the
`admin` role for frictionless local iteration. In production, set the RBAC key
variables and an explicit `DJANGO_SECRET_KEY`.

## Frontend (React SPA)

The browser UI lives in `frontend/` (React 18 + Vite + TypeScript) and builds
into `frontend_dist/`, which Django serves as the app shell with hashed assets
under `/static/`. Client-side routes (`/pricing`, `/console`, `/billing/success`)
are handled by a catch-all that returns the SPA shell, so hard refreshes work.

Build the SPA once before running Django so the productized UI is served (until
then, Django falls back to the legacy `public/` UI):

```powershell
npm --prefix frontend install
npm --prefix frontend run build
```

For live frontend development with hot reload, run the Vite dev server (it
proxies `/api` and `/health` to Django on port 8000):

```powershell
npm --prefix frontend run dev   # http://localhost:5173
```

The build output (`frontend_dist/`) is gitignored; rebuild it during deploy.

## API Endpoints

All endpoints are served under `/api/migrations/` so the bundled UI works
unchanged.

| Method | Path | Min role | Purpose |
| ------ | ---- | -------- | ------- |
| POST | `/api/migrations/review` | viewer | Review a Render/Railway account (settings + env key names only; secrets never returned) |
| POST | `/api/migrations/discover` | viewer | Discover a provider app into a canonical spec (secret values sealed server-side) |
| POST | `/api/migrations/plan` | operator | Build a migration plan (risk/confidence, sealed secrets, integrity hash) |
| POST | `/api/migrations/apply` | admin | Apply a plan after re-verifying its integrity hash |
| POST | `/api/migrations/rollback` | admin | Roll back to a captured snapshot |
| POST | `/api/migrations/terraform/plan` | operator | Deterministic Terraform plan with drift detection |
| POST | `/api/migrations/terraform/apply` | admin | Apply a Terraform plan |
| POST | `/api/migrations/deploy/detect` | viewer | Detect framework/runtime from project files |
| POST | `/api/migrations/deploy` | admin | Run the full deployment pipeline (real integrations + fallback) |
| POST | `/api/migrations/diagnose` | viewer | Diagnose project misconfigurations |
| POST | `/api/migrations/diagnose/fix` | operator | Apply safe auto-fixes and return a residual report |
| GET  | `/api/migrations/audit` | viewer | Read the audit log and chain validity |
| POST | `/api/license/validate` | public | Validate an installer license key + domain + instance heartbeat |
| POST | `/api/license/revoke` | admin | Revoke a license key and deactivate all registered instances |

## Subscription Billing

API Transfer bills its own customers through Stripe. Plans are defined in a
single source of truth, `billing/stripe_config.py` (the “stripe.config”): Free,
Pro ($79/mo), Scale ($199/mo), and Enterprise (contact sales). The pricing page
reads this catalog and starts a Stripe Checkout session for paid plans.

The Pro plan is anchored to a managed licensing layer for Stripe Installer:

- Checkout captures the customer's registered production domain.
- Stripe subscription webhooks issue a unique license key, tied to customer,
  subscription ID, registered domain, and max active instance count.
- Deployed installer instances call `POST /api/license/validate` at startup and
  every 24 hours with `{ licenseKey, domain, instanceId }`.
- Validation enforces key status, domain lock, and instance ceiling before
  returning `{ valid, reason, expiresAt }`.

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET  | `/api/billing/plans` | Public plan catalog + publishable key + `billingEnabled` |
| POST | `/api/billing/checkout` | Create a Stripe Checkout session for a plan + registered domain |
| POST | `/api/billing/portal` | Create a Stripe billing-portal session |
| GET  | `/api/billing/subscription?email=` | Current subscription (or `free`) for a customer |
| POST | `/api/billing/webhook` | Stripe webhook receiver (signature-verified) |

Billing is **disabled gracefully** until configured: without `STRIPE_SECRET_KEY`,
`plans` reports `billingEnabled: false` and `checkout` returns `503`. Set the
`STRIPE_*` and `BILLING_*` variables (see `.env.example`) to enable it. Webhooks
are verified using Stripe's signed-payload scheme (HMAC-SHA256, constant-time
compare, 300s tolerance) against `STRIPE_WEBHOOK_SECRET`; handlers are idempotent.

## Deployment Pipeline

`POST /api/migrations/deploy` runs ten stages: create-environment,
provision-database, configure-env-vars, deploy-app, setup-domain,
create-dns-records, enable-ssl, configure-stripe, setup-monitoring,
setup-backups. Each stage calls the real provider API when the relevant
credential is present, and otherwise returns a safe simulated result flagged
`data.live = false`. Secrets produced by a stage are sealed and never returned
in plaintext.

## Smoke Test

With the server running, `scripts/smoke.ps1` exercises every endpoint and
verifies there are no plaintext-secret leaks and that the audit chain is valid.

## Project Layout

- `apitransfer/` — Django project (settings, URLs, WSGI/ASGI)
- `core/` — vault, integrity, redaction, RBAC, security headers
- `migrationengine/` — adapters, planner, providers, terraform, audit, API views
- `diagnostics/` — diagnosis + auto-fix engine and API
- `deployments/` — framework detector, pipeline stages, orchestration
- `billing/` — self-subscription billing (stripe.config, models, checkout, webhooks)
- `licenses/` — license issuance, validation, revocation, and instance registry
- `frontend/` — React + Vite + TypeScript SPA (pricing, console, billing)
- `frontend_dist/` — built SPA served by Django (gitignored; rebuild on deploy)
- `public/` — legacy bundled web UI (fallback before the SPA is built)
