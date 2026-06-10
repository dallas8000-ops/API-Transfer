# API Transfer Production Checklist

Use this as the shortest possible production run order.

## 1. Enable the worker

```bash
sudo cp /path/to/repo/scripts/transfer-worker.service /etc/systemd/system/api-transfer-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now api-transfer-worker.service
sudo systemctl status api-transfer-worker.service
journalctl -u api-transfer-worker.service -n 100 --no-pager
```

## 2. Verify health and alert routing

```bash
cd /opt/api-transfer
python manage.py transfer_worker_health --json
```

Route alerts when any of these are active in the JSON output:

- `alerts.deadLetter.active`
- `alerts.retryableBacklog.active`
- `alerts.staleLeases.active`

## 3. Run one live smoke cycle

```bash
python manage.py transfer_render_to_railway --mode queue --limit 1 --verify-timeout 120 --verify-interval 10
python manage.py transfer_worker_health --json
python manage.py transfer_worker_health --json --no-fail-on-alert
```

## 4. Capture artifacts

Save these outputs after the live cycle:

- `journalctl -u api-transfer-worker.service -n 200 --no-pager`
- `python manage.py transfer_worker_health --json`
- `GET /api/migrations/transfer/metrics`
- `GET /api/migrations/transfer/history?limit=10`
- `scripts/smoke.ps1` output if you also run the API smoke suite

Suggested filenames:

- `artifacts/worker-status.txt`
- `artifacts/worker-health.json`
- `artifacts/transfer-metrics.json`
- `artifacts/transfer-history.json`
- `artifacts/journalctl-tail.txt`
- `artifacts/smoke-output.txt`
