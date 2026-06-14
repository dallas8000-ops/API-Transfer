#!/bin/sh
set -e
cd "$(dirname "$0")/.."
echo "Starting API Transfer (PORT=${PORT:-8080})..."
python manage.py migrate --noinput
exec gunicorn apitransfer.wsgi:application \
  --bind "0.0.0.0:${PORT:-8080}" \
  --workers 2 \
  --timeout 120
