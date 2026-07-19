# Deployment

## Local development

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python scripts/seed_dev.py
```

Visit:

- Agent SPA: <http://localhost:5173>
- API health: <http://localhost:8000/api/v1/health>
- Keycloak admin: <http://localhost:8080>
- MinIO console: <http://localhost:9001>
- RabbitMQ management: <http://localhost:15672>

## Production profile (P0)

- Single Docker Compose deployment on a hardened Linux host
- Nginx terminates TLS (Let's Encrypt or organisational CA)
- PostgreSQL runs on the host or a managed instance with backups configured
- MinIO on a separate node with replicated drives
- Daily encrypted backups to object storage; restore tested quarterly (PRD NFR-015)
- Keycloak deployed with external DB; realm exported under version control

A high-availability profile (active/active PostgreSQL, multi-node Keycloak,
separate MinIO cluster) is planned for P2 (PRD §10.3).

## Observability

- Logs: stdout JSON, shipped to Loki via Promtail
- Metrics: Prometheus scrape at `/api/v1/metrics` (django-prometheus)
- Traces: OpenTelemetry OTLP exporter; console exporter for local dev
- Alerts: Grafana / Alertmanager rules (in `infrastructure/prometheus/alerts/`)

## Backup & restore

```bash
./scripts/backup.sh                                    # writes backups/<timestamp>/
CONFIRM=1 ./scripts/restore.sh backups/<timestamp>/...  # overwrites DB + objects
```

Backups include the database dump, MinIO bucket, Keycloak realm export, and
the current `docker-compose.yml` + `.env`. Archives are AES-256-GCM encrypted.
