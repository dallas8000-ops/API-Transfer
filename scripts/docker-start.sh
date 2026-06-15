#!/bin/sh
set -e
PORT="${PORT:-8080}"
echo "[api-transfer] PORT=${PORT}"
echo "[api-transfer] loading Django..."
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'apitransfer.settings'); import django; django.setup(); print('[api-transfer] Django OK')"
echo "[api-transfer] running migrations..."
python manage.py migrate --noinput || echo "[api-transfer] WARN: migrate failed (starting anyway)"
echo "[api-transfer] starting gunicorn on 0.0.0.0:${PORT}"
exec gunicorn apitransfer.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
