# MHC Unified e-Ticketing and Service Desk

A secure, open-source-oriented service management platform for the Office of the Master of the High Court, Judiciary of Eswatini. Captures enquiries across call, walk-in, web, email (and later WhatsApp), routes them through Kanban and queue workflows, enforces strict separation between Operational and IT service desks, and gives requesters trustworthy status.

> Source of truth: [`docs/prd.md`](docs/prd.md) (the merged PRD v2.0, 18 July 2026).

## Stack (P0)

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind, TanStack Query, dnd-kit, React Hook Form + Zod |
| Backend | Django 5.2 LTS, Django REST Framework, modular monolith |
| Background jobs | Celery + RabbitMQ |
| Database | PostgreSQL 18 |
| Cache / locks | Redis 7 (Valkey-compatible) |
| Object storage | MinIO (S3-compatible) |
| Identity | Keycloak 26 (OIDC, MFA) |
| Malware scan | ClamAV |
| Reverse proxy | Nginx (production) / Vite dev server (local) |
| Observability | OpenTelemetry, Prometheus, Grafana, Loki |
| Packaging | Docker, Docker Compose |

## Repository layout

```
.
├── backend/                # Django modular monolith
│   ├── config/             # Settings, root urls, asgi/wsgi
│   ├── apps/               # One folder per bounded context (see PRD §25.2)
│   ├── requirements/       # Pinned dependency files
│   └── tests/              # Cross-app integration tests
├── frontend/               # React + Vite + TypeScript SPA
├── infrastructure/
│   ├── keycloak/           # Realm export and bootstrap
│   ├── nginx/              # Production reverse proxy config
│   └── prometheus/         # Scrape configs
├── docs/                   # PRD, ADRs, traceability, threat model, runbooks
├── scripts/                # Backup, restore, dev helpers
├── seed/                   # Reproducible seed data
├── tests/e2e/              # Playwright end-to-end
├── docker-compose.yml
├── Makefile
└── .env.example
```

## Quick start (local development)

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py loaddata seed/initial.json
```

Open:

- Agent SPA: <http://localhost:5173>
- API: <http://localhost:8000/api/v1/health>
- Keycloak admin: <http://localhost:8080> (admin / `${KEYCLOAK_ADMIN_PASSWORD}`)
- MinIO console: <http://localhost:9001>
- Grafana: <http://localhost:3000>

## Current milestone

**M1 — Platform Foundation** (in progress). Exit criteria: staff can authenticate via Keycloak, role/scope checks pass, full stack deploys from clean checkout, health endpoint reports healthy, backups and restore demonstrated.

See [`docs/roadmap.md`](docs/roadmap.md) for the full delivery plan.

## License

TBD (PRD §24.4 — to be approved by the responsible authority).
