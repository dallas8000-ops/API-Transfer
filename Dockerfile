# Railway production image — API Transfer
# manage.py: manage.py (repo root)
# WSGI: apitransfer.wsgi:application
# Port: ${PORT:-8080}

FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/frontend_dist ./frontend_dist

ENV PYTHONUNBUFFERED=1

RUN DJANGO_SECRET_KEY=build-placeholder-not-used-at-runtime \
    VAULT_MASTER_KEY_BASE64=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= \
    DJANGO_DEBUG=False \
    python manage.py collectstatic --noinput

EXPOSE 8080

CMD ["sh", "-c", "set -e; PORT=${PORT:-8080}; echo \"[api-transfer] migrate...\"; python manage.py migrate --noinput; echo \"[api-transfer] gunicorn on 0.0.0.0:${PORT}\"; exec gunicorn apitransfer.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --timeout 120 --access-logfile - --error-logfile -"]
