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
ENV DJANGO_DEBUG=False
ENV DJANGO_SECRET_KEY=build-placeholder-not-used-at-runtime
ENV VAULT_MASTER_KEY_BASE64=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=

RUN python manage.py collectstatic --noinput

RUN chmod +x scripts/docker-start.sh

EXPOSE 8080

CMD ["/app/scripts/docker-start.sh"]
