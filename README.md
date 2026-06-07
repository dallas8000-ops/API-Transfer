# API Transfer (Secure AI-Assisted Migration)

A TypeScript service that creates and applies migration plans across providers with minimal manual intervention while protecting secrets and enforcing integrity.

## Supported Provider Adapters (v1 scaffold)

- Render
- Railway
- Fly.io
- Kong Gateway
- Terraform
- Supabase

## Security + Integrity Built In

- Secrets encrypted with AES-256-GCM before plan storage
- Sensitive field redaction in logs
- Plan integrity hashing with SHA-256
- Policy engine to block unsafe migrations
- Apply endpoint requires approval identity

## Quick Start

1. Install dependencies:

```bash
npm install
```

2. Copy environment file:

```bash
copy .env.example .env
```

3. Set a 32-byte base64 key in `.env`:

- `VAULT_MASTER_KEY_BASE64=<base64-of-32-random-bytes>`

4. Run in development:

```bash
npm run dev
```

5. Health check:

```bash
GET http://localhost:4000/health
```

## API Endpoints

- `POST /api/migrations/plan`
  - Input: `{ "spec": CanonicalMigrationSpec }`
  - Output: migration plan with risk/confidence and integrity hash

- `POST /api/migrations/apply`
  - Input: `{ "spec": CanonicalMigrationSpec, "plan": MigrationPlan, "approvedBy": "name" }`
  - Output: provider-specific deployment payload + execution integrity hash

## Notes

- Provider adapters are scaffolded and intentionally conservative.
- Real provider API clients, auth flows, and rollback orchestration are next steps.
