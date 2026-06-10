# API Transfer Production Runbook

This runbook covers the production worker, alerting, and a single live smoke cycle for the Render to Railway transfer flow.

## Production Checklist

1. Deploy the latest code and ensure the `.env` file includes the transfer policy and alert threshold variables.
2. Install and enable `api-transfer-worker.service` on the production host.
3. Confirm `python manage.py transfer_worker_health --json` returns no active alerts.
4. Route health failures to Slack or PagerDuty.
5. Run one live transfer smoke cycle and capture the artifacts listed below.

## 1. Install and enable the worker service

Copy the systemd unit template onto the host, reload systemd, and start the service:

```bash
sudo cp /path/to/repo/scripts/transfer-worker.service /etc/systemd/system/api-transfer-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now api-transfer-worker.service
sudo systemctl status api-transfer-worker.service
journalctl -u api-transfer-worker.service -n 100 --no-pager
```

## 2. Verify worker health and wire alerting

Use the health command as the alerting source. It exits non-zero when dead-letter, retryable backlog, or stale lease alerts are active.

```bash
cd /opt/api-transfer
python manage.py transfer_worker_health --json
```

Alert routing recommendations:

- Trigger Slack or PagerDuty on a non-zero exit code from `transfer_worker_health`.
- Trigger Slack or PagerDuty when `alerts.deadLetter.active`, `alerts.retryableBacklog.active`, or `alerts.staleLeases.active` is `true` in the JSON payload.
- Poll `GET /api/migrations/transfer/metrics` if you want a shared API signal for dashboards.

## 3. Run one live production transfer smoke cycle

Run one real transfer through the live worker, then re-check health:

```bash
python manage.py transfer_render_to_railway_smoke --limit 1 --verify-timeout 120 --verify-interval 10
python manage.py transfer_worker_health --json
python manage.py transfer_worker_health --json --no-fail-on-alert
```

The smoke command runs a full preflight + transfer + verification + readiness report in one pass.

Reruns now default to failed-only behavior when `--redeploy-existing` is used, so already green services are skipped unless you pass `--include-green`.

### Resume verification for already transferred services

If a prior run transferred services but did not verify them, rerun the command in demand mode with the specific service names or Render service ids and `--redeploy-existing` so Railway returns a fresh deployment id for verification:

```bash
python manage.py transfer_render_to_railway --mode demand --only specwright-api --only specwright-web --redeploy-existing --verify-timeout 240 --verify-interval 10
```

Use one `--only` entry per service that still needs verification. If the service already exists in Railway, `--redeploy-existing` is required for an actual verification pass.

If you need a tighter operator check, also verify the transfer API state:

```bash
curl http://127.0.0.1:8000/api/migrations/transfer/metrics
curl http://127.0.0.1:8000/api/migrations/transfer/history?limit=10
```

### Monorepo/static-site override example

For frontend apps in a subdirectory, use root/build/static overrides:

```bash
python manage.py transfer_render_to_railway --mode demand --only FrontLineDigital --redeploy-existing --verify-timeout 300 --verify-interval 10 --force-static-site --override-root-directory DevCollective/frontend --override-build-command "npm ci && npm run build"
```

### Environment variable source and fallback

By default, the transfer command copies runtime variables from Render (`/env-vars`) into Railway.

If Render is missing required frontend build variables (for example `VITE_` keys), include local environment variables by prefix:

```bash
python manage.py transfer_render_to_railway --mode demand --only FrontLineDigital --redeploy-existing --include-local-env-prefix VITE_ --include-local-env-prefix NEXT_PUBLIC_ --verify-timeout 300 --verify-interval 10
```

Note: local prefix merging uses variables present in the current process environment (or shell-exported `.env`), not arbitrary files.

## 4. Record artifacts

Capture the following after the live cycle:

- `journalctl -u api-transfer-worker.service -n 200 --no-pager`
- `python manage.py transfer_worker_health --json`
- `GET /api/migrations/transfer/metrics`
- `GET /api/migrations/transfer/history?limit=10`
- `scripts/smoke.ps1` output if you also run the API smoke suite against the live host

Suggested filenames:

- `artifacts/worker-status.txt`
- `artifacts/worker-health.json`
- `artifacts/transfer-metrics.json`
- `artifacts/transfer-history.json`
- `artifacts/journalctl-tail.txt`
- `artifacts/smoke-output.txt`

## 5. Configuration knobs

These environment variables control the worker and health thresholds:

- `TRANSFER_WORKER_LIMIT`
- `TRANSFER_WORKER_POLL_INTERVAL_SECONDS`
- `TRANSFER_WORKER_LEASE_TTL_SECONDS`
- `TRANSFER_WORKER_HEARTBEAT_INTERVAL_SECONDS`
- `TRANSFER_WORKSPACE_CONCURRENCY_CAP`
- `TRANSFER_QUEUE_AGING_WINDOW_SECONDS`
- `TRANSFER_QUEUE_MAX_AGING_BOOST`
- `TRANSFER_ALERT_DEAD_LETTER_THRESHOLD`
- `TRANSFER_ALERT_RETRYABLE_THRESHOLD`
- `TRANSFER_ALERT_STALE_LEASE_THRESHOLD`

The defaults are documented in `.env.example`.
