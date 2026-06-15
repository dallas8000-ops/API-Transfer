#!/bin/sh
set -e
cd "$(dirname "$0")/.."
echo "Starting API Transfer (PORT=${PORT:-8080})..."
python manage.py migrate --noinput || {
  echo "[api-transfer] migrate failed — check DATABASE_URL and Postgres service link"
  exit 1
}
exec gunicorn apitransfer.wsgi:application \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers 2 \
  --timeout 120
