#!/bin/sh
set -e
cd "$(dirname "$0")/.."
PORT="${PORT:-8080}"
echo "[api-transfer] starting gunicorn on 0.0.0.0:${PORT}"
exec gunicorn apitransfer.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
