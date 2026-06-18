# Platform Setup Guide — Step by Step

This guide walks you through configuring **every API category** in API Transfer using the **Migration Console** at `http://localhost:8000/console`. You can complete platform prep **before any clients exist**.

---

## Two layers — don't confuse them

| Layer | Providers | Purpose |
| ----- | --------- | ------- |
| **Migration & deploy (core)** | Railway, Render, Fly, Orena, Supabase, Cloudflare, GitHub | Automated API transfer — account review, discover, plan, apply, Render→Railway queue, one-click deploy |
| **Platform billing** | Stripe (USD), Paystack (KES) | Customers pay **you** for API Transfer subscriptions on `/pricing` |
| **Foundation** | Vault | Encrypts secrets in every migration plan |

The **Stripe / Paystack dropdown on `/pricing`** is only for platform checkout. **Railway and Render** are configured in `.env` and verified under **Platform setup automation → Migration & deploy APIs** — then used in **Account review → Discover → Transfer → Deploy** above that section in the console.

---

## What you are setting up

| Category | Purpose | Required for |
| -------- | ------- | ------------ |
| **Encrypted secret vault** | Seals secrets in migration plans | All live migrations |
| **Stripe billing (USD)** | International subscriptions | USD checkout, Stripe Installer |
| **Paystack billing (KES / M-Pesa)** | East Africa subscriptions | KES checkout, M-Pesa |
| **Orena Cloud (ke-1)** | Deploy to Nairobi region | East Africa target host |
| **Railway** | Source/target transfers | US PaaS migrations |
| **Render** | Source inventory & transfers | Render account review |

The console **Platform setup automation** section audits these categories, runs safe auto-fix actions, and tells you exactly what to paste into `.env`.

---

## Phase 0 — One-time local install

### Step 1: Install Python dependencies

```powershell
cd "C:\Software Projects\API Transfer"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Step 2: Build the frontend (required for the console UI)

```powershell
npm --prefix frontend install
npm --prefix frontend run build
```

Django serves the built SPA from `frontend_dist/`. If the page is blank after a rebuild, restart Django (`Ctrl+C`, then `python manage.py runserver 8000`).

### Step 3: Create your `.env` file

**Location:** same folder as `manage.py` — **not inside `manage.py`**.

Option A — copy the East Africa template from the console (see Phase 1).  
Option B — copy from the repo:

```powershell
Copy-Item .env.example .env
# or
Copy-Item env.east-africa.template .env
```

**Minimum to start locally:**

```env
DJANGO_SECRET_KEY=<any-long-random-string>
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3
```

Generate keys if needed:

```powershell
# Django secret
python -c "import secrets; print(secrets.token_urlsafe(50))"

# Vault master key (32 bytes, base64)
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```

Paste outputs into `DJANGO_SECRET_KEY` and `VAULT_MASTER_KEY_BASE64`.

> **Note:** `postgres.railway.internal` URLs only work when Django runs **on Railway**, not from your PC. Use `sqlite:///db.sqlite3` locally.

### Step 4: Apply database migrations and start the server

```powershell
python manage.py migrate
python manage.py runserver 8000
```

Verify:

- Health: `http://localhost:8000/health` → `{"service": "api-transfer"}`
- Console: `http://localhost:8000/console`

---

## Phase 1 — Open the console and paste the template

### Step 1: Open the Migration Console

Go to **http://localhost:8000/console**.

Ensure the header shows **Live** mode (not Demo). Demo mode simulates provider responses and disables setup actions.

### Step 2: Workspace access (top card)

| Field | What to enter |
| ----- | ------------- |
| **Account email** | Your operator email (used for billing/workspace) |
| **API key** | Leave **empty** locally if `RBAC_*` keys are empty in `.env` and `DJANGO_DEBUG=1` |

Local dev hint shown in the UI: empty RBAC + DEBUG = full admin access without a key.

### Step 3: Copy the East Africa `.env` template

Scroll to **East Africa .env template**:

1. Click **Copy template to clipboard**
2. Open `.env` in your editor (File → Open → `.env` in the project root)
3. Merge with your existing values — do not delete keys you already have (Railway, Render, etc.)
4. Save `.env`
5. **Restart Django** — env changes are only read at startup

---

## Phase 2 — Platform setup automation (all categories)

Scroll to **Platform setup automation**. On load, the app runs an audit and shows one card per category with status **Ready**, **Partial**, or **Missing**.

Use **Re-audit platform** after every `.env` change and server restart.

Use **Run all connection tests** to verify every configured provider in one click.

---

### Category 1 — Encrypted secret vault

**What it does:** Encrypts secrets (API keys, DB URLs) before they are stored in migration plans. Plaintext secrets are never returned by the API.

#### Step 1: Get a vault key

```powershell
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
```

#### Step 2: Add to `.env`

```env
VAULT_MASTER_KEY_BASE64=<paste-output-here>
```

#### Step 3: Restart Django and re-audit

Status should change to **Ready**.

> With `DJANGO_DEBUG=1` and no vault key, Django generates a temporary key on each restart. Set `VAULT_MASTER_KEY_BASE64` for a stable vault across restarts.

---

### Category 2 — Stripe billing (USD)

**What it does:** USD subscription checkout, billing portal, webhooks, and license issuance for international clients.

**Dashboard:** https://dashboard.stripe.com (use **Test mode** first)

#### Step 1: Get API keys

1. Stripe Dashboard → **Developers** → **API keys**
2. Copy **Secret key** and **Publishable key**

#### Step 2: Add to `.env`

```env
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
BILLING_CURRENCY=usd
BILLING_SUCCESS_URL=http://localhost:8000/billing/success?session_id={CHECKOUT_SESSION_ID}
BILLING_CANCEL_URL=http://localhost:8000/pricing
```

#### Step 3: Restart Django → Re-audit

The Stripe card should show **Partial** (missing price IDs and/or webhook secret).

#### Step 4: Auto-create Pro & Scale prices (console)

In the **Stripe billing (USD)** task:

1. Click **Create/find Stripe Pro & Scale prices**
2. Copy the **Action output** block (e.g. `STRIPE_PRICE_PRO=price_...`, `STRIPE_PRICE_SCALE=price_...`)
3. Paste into `.env`
4. Restart Django

#### Step 5: Register Stripe webhook (console)

1. Click **Register Stripe billing webhook**
2. Copy `STRIPE_WEBHOOK_SECRET=whsec_...` from the action output
3. Paste into `.env`
4. Restart Django

Webhook URL (for reference): `http://localhost:8000/api/billing/webhook`  
For local webhook delivery from Stripe, use a tunnel (ngrok, Cloudflare Tunnel, etc.) and update the endpoint URL in Stripe Dashboard.

#### Step 6: Test connection

Click **Test Stripe API connection**. Expect: `Stripe API connection verified.`

#### Step 7: Verify in the app

- Open **http://localhost:8000/pricing** — toggle **USD**, start checkout (test card `4242 4242 4242 4242`)

---

### Category 3 — Paystack billing (KES / M-Pesa)

**What it does:** East Africa subscriptions in Kenyan Shillings with M-Pesa and card channels.

**Dashboard:** https://dashboard.paystack.com (use **Test mode** first)

#### Step 1: Get API keys

1. Paystack Dashboard → **Settings** → **API Keys & Webhooks**
2. Copy **Secret key** and **Public key**

#### Step 2: Create subscription plans (Paystack dashboard)

1. **Products** → create monthly plans for **Pro** and **Scale**
2. Use KES amounts aligned with platform pricing (Pro ~ KES 9,900/mo, Scale ~ KES 24,900/mo — see `billing/stripe_config.py`)
3. Note each **Plan code** (starts with `PLN_`)

#### Step 3: Add to `.env`

```env
PAYSTACK_SECRET_KEY=sk_test_...
PAYSTACK_PUBLIC_KEY=pk_test_...
PAYSTACK_CURRENCY=KES
PAYSTACK_PLAN_PRO=PLN_...
PAYSTACK_PLAN_SCALE=PLN_...
PAYSTACK_CALLBACK_URL=http://localhost:8000/billing/success?reference={reference}
```

#### Step 4: Restart Django → Re-audit

#### Step 5: Find plan codes automatically (console)

If plan codes are missing:

1. Click **Find Paystack plan codes** (or **Auto-fix** on the plan issue)
2. Copy suggested `PAYSTACK_PLAN_PRO` / `PAYSTACK_PLAN_SCALE` from action output
3. Paste into `.env` and restart

#### Step 6: Register Paystack webhook (manual — dashboard)

Paystack webhooks are configured in their dashboard (not auto-registered):

| Setting | Value |
| ------- | ----- |
| **URL** | `http://localhost:8000/api/billing/webhook/paystack` |
| **Events** | `charge.success`, `subscription.create`, `subscription.disable` |

For local testing, expose port 8000 with a tunnel and use the public URL.

#### Step 7: Test connection

Click **Test Paystack API connection**. Expect: `Paystack API connection verified.`

#### Step 8: Verify in the app

- Open **http://localhost:8000/pricing** — toggle **KES**, start checkout

---

### Category 4 — Orena Cloud (Nairobi, ke-1)

**What it does:** Discover apps, account review, and deploy to the Nairobi region (`ke-1`) for East Africa clients.

**Console:** https://orenacloud.com

#### Step 1: Get an API token

1. Orena Console → **Access** → **API tokens**
2. Create a token (works even with zero apps — validates connection)

#### Step 2: Add to `.env`

```env
ORENA_API_TOKEN=<your-token>
ORENA_API_BASE_URL=https://api.orenacloud.com/v1
ORENA_DEFAULT_REGION=ke-1
ORENA_PROJECT_ID=          # optional — only if your API is project-scoped
DEFAULT_EAST_AFRICA_PROVIDER=orena
DEFAULT_EAST_AFRICA_REGION=ke-1
```

#### Step 3: Restart Django → Re-audit

#### Step 4: Test connection (console)

Click **Test Orena connection & list apps**. Expect a message like `Orena connected — N app(s) visible.`

#### Step 5: Use in migrations

When you **Discover** a Render/Railway app, the platform suggests **Orena** as the regional target. The **Deploy** pipeline uses Orena when `ORENA_API_TOKEN` is set.

---

### Category 5 — Railway (transfer target / source)

**What it does:** Live service inventory, account review, and Render→Railway transfers.

**Dashboard:** https://railway.app → Account → **Tokens**; project ID from project **Settings**.

#### Step 1: Get credentials

1. **RAILWAY_API_TOKEN** — create a personal/account token
2. **RAILWAY_PROJECT_ID** — UUID from your Railway project settings

#### Step 2: Add to `.env`

```env
RAILWAY_API_TOKEN=<token>
RAILWAY_PROJECT_ID=<uuid>
RAILWAY_API_BASE_URL=https://backboard.railway.app
```

> Having `RAILWAY_PROJECT_ID` in `.env` for local API use does **not** mean you are running on Railway. The app only treats the process as on-Railway when `RAILWAY_ENVIRONMENT` is set by the host.

#### Step 3: Restart Django → Re-audit

#### Step 4: Test connection (console)

Click **Test Railway GraphQL connection**. Expect: `Railway connected — N service(s).`

#### Step 5: See inventory in the console

Scroll to **Account review** — Railway services appear automatically when credentials are valid.

---

### Category 6 — Render (source inventory)

**What it does:** Lists Render services for account review and migration planning.

**Dashboard:** https://dashboard.render.com → Account → **API Keys**; owner ID from team settings.

#### Step 1: Get credentials

1. **RENDER_API_TOKEN** — create an API key
2. **RENDER_OWNER_ID** — team/owner ID (starts with `tea-` or `usr-`)

#### Step 2: Add to `.env`

```env
RENDER_API_TOKEN=rnd_...
RENDER_OWNER_ID=tea_...
RENDER_API_BASE_URL=https://api.render.com
RENDER_DEFAULT_REGION=oregon
```

#### Step 3: Restart Django → Re-audit

#### Step 4: Test connection (console)

Click **Test Render API connection**. Expect: `Render connected — N service(s).`

#### Step 5: Use in migrations

**Account review** → select a Render service → **Discover** → **Plan** → **Apply** → **Deploy**.

---

## Phase 3 — Run all connection tests

When every category has credentials in `.env`:

1. **Platform setup automation** → **Run all connection tests**
2. Review per-provider results in the output panel
3. Fix any failures (wrong token, missing plan code path typo)
4. Click **Re-audit platform**

Goal: **Tasks ready** shows `6/6` (or all categories you care about).

---

## Phase 4 — Prewire a client (optional, after platform is ready)

Use this when onboarding a **new client workspace** — can be done with test data before real production traffic.

Scroll to **Prewire new client**:

| Field | Example |
| ----- | ------- |
| Client email | `client@company.co.ke` |
| Client / workspace name | `Acme Ltd` |
| Licensed domain | `app.client.co.ke` |
| Source provider | `railway` or `render` (optional) |
| Source app ID / name | service UUID or name (optional — triggers discover + plan) |

Click **Prewire client**.

The result shows:

- **Checklist** — platform creds, workspace, domain conflicts, discovery
- **Connections** — orena, paystack, monitoring, backups prewired to the workspace
- **Next steps** — e.g. finish `.env`, review plan, register Paystack webhook, bind license after checkout

---

## Phase 5 — End-to-end migration workflow (after APIs are set up)

Once platform setup is **Ready**, use the rest of the console in order:

```text
Account review  →  Discover  →  Plan  →  Apply  →  Deploy
       ↑              ↑
 GitHub import    (or select app from Railway/Render inventory)
```

| Console section | Action |
| --------------- | ------ |
| **Provider readiness** | Summary of which providers are live vs simulated |
| **GitHub import** | Pull a repo for detect/diagnose/deploy |
| **Account review** | Pick a Railway/Render service |
| **Discover / Plan / Apply** | Build and approve migration plan |
| **Transfer control** | Queue Render→Railway jobs |
| **Railway env backup** | Export all variables from a Railway service before transfer/deploy |
| **Deploy** | Run the 10-stage pipeline (DB, env, app, DNS, SSL, billing hooks, monitoring, backups) |
| **Diagnose** | Scan project for misconfigurations |
| **Audit** | Tamper-evident log of operator actions |

---

## Preserving Railway variables and secret keys

When you transfer or redeploy services to Railway, API Transfer **merges** environment variables by default instead of wiping the target service.

| Behavior | Detail |
| -------- | ------ |
| **Default merge** | Existing Railway variables stay unless the transfer supplies a **non-empty** value for the same key |
| **Empty source values** | If Render (or another source) omits a secret value, the existing Railway secret is **not** overwritten with blank |
| **Pre-transfer backup** | CLI transfer writes a JSON snapshot to `transfer-env-backups/` before updating an existing service |
| **Console backup** | **Railway env backup** card (above Deploy) — one-click export + **Download JSON** before any deploy |
| **Discover first** | Use **Account review → Discover** so secrets are sealed server-side; pass the discovery ID into **Deploy** |

### Safe workflow (recommended)

1. **Account review** — select the source service (Render or Railway).
2. **Discover** — captures env vars and seals secrets in the vault (never sent to the browser).
3. **Transfer** or **Deploy** with the discovery ID attached.
4. For CLI transfers, use `--include-local-env-key STRIPE_SECRET_KEY` (repeat per key) if a secret lives only in your local `.env`.
5. Avoid `--replace-railway-env` unless you intentionally want to drop keys not in the transfer payload.

### Stripe Installer on Railway

If Stripe keys live on a **separate** Railway service (e.g. `stripe-installer`), use **Platform setup → Sync Stripe from Railway** to copy them into this app's `.env` for platform billing. Client app services keep their own keys when you prewire later — transferring one app does not remove variables from sibling services.

---

## Quick reference — `.env` variables by category

| Category | Variables |
| -------- | --------- |
| Core | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL` |
| Vault | `VAULT_MASTER_KEY_BASE64` |
| Stripe | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_SCALE`, `BILLING_*` |
| Paystack | `PAYSTACK_SECRET_KEY`, `PAYSTACK_PUBLIC_KEY`, `PAYSTACK_PLAN_PRO`, `PAYSTACK_PLAN_SCALE`, `PAYSTACK_CURRENCY`, `PAYSTACK_CALLBACK_URL` |
| Orena | `ORENA_API_TOKEN`, `ORENA_PROJECT_ID`, `ORENA_DEFAULT_REGION`, `DEFAULT_EAST_AFRICA_*` |
| Railway | `RAILWAY_API_TOKEN`, `RAILWAY_PROJECT_ID` |
| Render | `RENDER_API_TOKEN`, `RENDER_OWNER_ID` |
| RBAC (production) | `RBAC_ADMIN_KEYS`, `RBAC_OPERATOR_KEYS`, `RBAC_VIEWER_KEYS` |

Full annotated template: `env.east-africa.template` or the console **Copy template to clipboard** button.

---

## Troubleshooting

### Blank console page

- Rebuild frontend: `npm --prefix frontend run build`
- Restart Django
- Hard refresh: `Ctrl+Shift+R`
- DevTools → Network: `/static/assets/index-*.js` must return **200**

### "You do not have permission to perform this action"

- Leave `RBAC_*` keys empty in `.env` for local dev, **or**
- Paste an admin key in **Workspace access → API key**

### Platform audit still shows Missing after adding keys

- Restart Django after every `.env` edit
- Click **Re-audit platform**
- Check for typos (`sk_test_` without the rest of the key counts as empty)

### Database connection errors locally

- Use `DATABASE_URL=sqlite:///db.sqlite3`
- Do not use `postgres.railway.internal` from your PC

### Stripe/Paystack webhooks not firing locally

- Stripe/Paystack need a **public HTTPS URL** to reach your machine
- Use ngrok or similar: `ngrok http 8000` → paste the HTTPS URL into the provider webhook settings

### Suggested env from auto-actions not applied

Auto-actions output values like `STRIPE_PRICE_PRO=price_xxx`. You must:

1. Copy from **Action output — add to .env and restart Django**
2. Paste into `.env`
3. Restart the server

The app does not write to `.env` automatically (by design — avoids overwriting secrets).

---

## Checklist — platform ready before first client

- [ ] Django runs on `http://localhost:8000` with no startup errors
- [ ] Console loads (not a blank page)
- [ ] `.env` saved next to `manage.py` (not in `manage.py`)
- [ ] Vault status **Ready**
- [ ] Paystack **Ready** (if East Africa billing)
- [ ] Orena **Ready** (if Nairobi deploys)
- [ ] Stripe **Ready** (if USD billing)
- [ ] Railway / Render **Ready** (if migrating from those platforms)
- [ ] **Run all connection tests** passed
- [ ] Paystack webhook registered (manual step)
- [ ] Stripe webhook registered (auto or manual)

When all boxes are checked, you are ready to **Prewire new client** or run your first **Discover → Deploy** flow.
