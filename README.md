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

## Development quality commands

Run these targets from the repository root against the local development
Docker Compose stack. They require GNU Make; on Windows, run them from WSL or
Git Bash with GNU Make installed rather than directly from PowerShell.

- `make test` runs the complete backend and frontend test suites.
- `make lint` runs Ruff for the backend and ESLint for the frontend.
- `make type` runs mypy against `/app/apps` and `/app/config`, then the
  frontend TypeScript check.
- `make verify` checks for Django migration drift, then runs the complete
  backend test and Ruff gates plus the frontend test, type, lint, and build
  gates. The target stops at the first failing command.
- `make pilot-smoke` runs `/app/scripts/pilot_foundation_smoke.py` in the
  backend container. It creates and mutates development-only ticket data, so
  use it only with the local `config.settings.dev` stack.

Each frontend gate rebuilds the current `frontend/` context and runs in a new
one-off container with an isolated anonymous `/app/node_modules` volume. The
volume is seeded from dependencies installed in the freshly built image and
removed with the gate container, so concurrent gates neither share installs
nor modify the development server's dependency volume. Tests normalize only
their API-base environment; type, lint, and build retain the Compose inputs.

## Current milestone

**M1 — Platform Foundation** (in progress). Exit criteria: staff can authenticate via Keycloak, role/scope checks pass, full stack deploys from clean checkout, health endpoint reports healthy, backups and restore demonstrated.

See [`docs/roadmap.md`](docs/roadmap.md) for the full delivery plan.

## License

TBD (PRD §24.4 — to be approved by the responsible authority).
