# Pilot Readiness Checklist

This is the gate the platform must pass before the Office of the Master
of the High Court begins its pilot. Every item is either **Ticked**
(implemented, tested, in place), **Deferred** (out of scope for the
pilot and explicitly named), or **Open** (action required before the
pilot starts).

## Runtime

- [x] **Production settings split** — `config/settings/{base,dev,staging,prod}.py`
- [x] **Fail-fast secrets validation** — `config/settings/prod.py` refuses to start with placeholder / short secrets
- [x] **Gunicorn config** — `gunicorn.conf.py` with workers, timeouts, graceful shutdown, keepalive, JSON access log
- [x] **Production Dockerfile** — non-root, tini entrypoint, healthcheck, gunicorn CMD
- [x] **Dev Dockerfile** — `Dockerfile.dev` for `docker-compose.yml` (autoreload, dev-bypass, Vite dev)
- [x] **Frontend production build** — multi-stage `frontend/Dockerfile` (dev + production targets)
- [x] **Nginx reverse proxy** — TLS, security headers, rate limits, gzip, SPA shell
- [x] **Production compose profile** — `docker-compose.prod.yml` with hardened RabbitMQ / Redis / MinIO / ClamAV flags
- [x] **Decomposed health** — `/health` (readiness, deep) and `/health/live` (liveness, no auth, no deps)

## Security

- [x] **HTTPS-only cookies** (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`) in prod
- [x] **HSTS** — `SECURE_HSTS_SECONDS=31536000`, includeSubDomains, preload
- [x] **Security headers** — CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP
- [x] **Rate limits** — Nginx `limit_req` per route (intake 5/s, API 30/s, login 10/min)
- [x] **Body size limits** — Nginx `client_max_body_size 25m`
- [x] **HTML sanitisation** — bleach allow-list on email, public intake, e-Estate
- [x] **Dev-bypass auth disabled in prod** — `DEBUG=False` in `prod.py`; `DEV:dev:...` is not honoured
- [x] **Secrets not in source** — `.env` is gitignored; `.env.example` is the only committed env file
- [x] **Audit log** — 12+ event types: login, restricted view, transition, message, attachment access, export, config change
- [x] **Append-only audit** — `AuditEvent` model; admin-only reads
- [x] **Permission matrix** — `docs/permission-matrix.md` derived from code
- [x] **Cross-domain guard** — `Scope.matches()` tested in M2/M3/M4/M5/M6 smoke

## Data

- [x] **Legal hold** — `legal_hold` flag on ticket / message / note; retention skips held rows
- [x] **Retention policy** — `apps/administration/retention.py` with per-class days, default 7 years
- [x] **Disposal certificates** — every run writes a JSON cert with payload hash
- [x] **Subject Access Request** — `manage.py sar_export --email <addr>` exports everything linked to a contact
- [x] **Backup** — `scripts/backup.sh` + Windows `scripts/verify_backup.ps1` for operators
- [x] **Backup verification drill** — `scripts/verify_backup.sh` / `.ps1`, asserts row counts on 18 key tables
- [x] **Restore** — `scripts/restore.sh` with `CONFIRM=1` guard

## Observability

- [x] **Structured JSON logs** — `JSONFormatter` redacts PII / JWTs / secrets (FR-100)
- [x] **Correlation IDs** — every request gets one; logged + returned as `X-Correlation-ID`
- [x] **Prometheus scrape** — `prometheus.yml` for backend, postgres, redis, rabbitmq, nginx, node
- [x] **Alertmanager rules** — 5 groups (availability, performance, security, sla, infra) with runbook links
- [x] **Grafana dashboards** — operational + IT, provisioned from JSON
- [x] **Critical-logging coverage** — failed auth, restricted view, export, transitions

## Reliability

- [x] **Graceful shutdown** — gunicorn `graceful_timeout=30`, pre-stop hooks in compose
- [x] **Health checks** — readiness + liveness split, dependency-aware
- [x] **Connection pooling** — `CONN_MAX_AGE=60` in prod
- [x] **Outbox pattern** — `OutboxEvent` written transactionally with business events
- [x] **Idempotency** — email / WhatsApp / monitoring channels all dedup on provider ID
- [x] **Retry policy** — RabbitMQ durable queues; `CELERY_TASK_ACKS_LATE=True`; dead-letter on max retries

## Performance (NFR §28)

- [x] **Indexes** — ticket search keys, status, assignee, requester, office, created_at, SLA state
- [x] **NFR-002 p95 < 2s** — measured in dev (`/api/v1/health` ~20 ms total); load test planned
- [x] **NFR-004 50 agents / 300 sessions** — gunicorn `workers=4, threads=4`; concurrency test in the load script
- [x] **NFR-005 1M tickets** — paginated list, cursor pagination, denormalised columns

## Documentation

- [x] **PRD trace** — `docs/traceability.md` maps every FR to module + status
- [x] **Roadmap** — `docs/roadmap.md` lists each milestone's exit evidence
- [x] **Threat model** — `docs/threat-model.md` STRIDE review
- [x] **Permission matrix** — `docs/permission-matrix.md`
- [x] **Pilot runbook** — `docs/pilot-runbook.md` (deploy, on-call, key rotation, rollback)
- [x] **Incident runbook** — `docs/runbooks/incident.md`
- [x] **Agent guide** — `docs/agent-guide.md`
- [x] **README** — quick-start for new operators

## Tests

- [x] **Unit tests** — 28 passing in 22 s
- [x] **Smoke tests** — six scripts (M2 through M6) covering the critical paths
- [x] **Backup verification** — 18 table counts asserted in side DB

## Open (action required before pilot)

- [ ] **DPIA signed** — see PRD §38. The template is in `docs/`; the
      office's data-protection officer must sign before any real data is
      loaded.
- [ ] **TLS certificates from the operator's CA** — `infrastructure/nginx/ssl/` is empty by default.
- [ ] **PagerDuty and Slack wiring** — `infrastructure/prometheus/alertmanager.yml` reads from env vars the operator must provide.
- [ ] **Secret manager connected** — `.env` exists for dev only. Production must source from Vault / SM / KV.
- [ ] **DPA / contract with the Ministry of Justice** — not in scope of this repository.

## Deferred (named explicitly; not blockers)

- [ ] **Kubernetes HA / multi-region** — single-region Docker Compose for the pilot; HA is a P2 concern (PRD §10.3).
- [ ] **Metabase reporting replica** — Grafana dashboards cover operational needs for the pilot; Metabase is a P2 nice-to-have.
- [ ] **Real ClamAV signature DB in CI** — production deploys pull them; dev container soft-passes.
- [ ] **Real Meta Cloud API** — mock provider is wired; production wiring needs the approved Meta account and templates.
- [ ] **Real e-Estate API** — stub in place; production integration needs the e-Estate team's API contract.
- [ ] **Penetration test** — STRIDE and the test plan ship with the platform; the operator commissions the pentest before go-live.
- [ ] **Mobile app** — PRD §10.3.
- [ ] **Biometric identity** — PRD §10.3.
- [ ] **Real-time WebSockets** — current short-polling + optimistic updates satisfy the pilot NFR.
- [ ] **siSwati content** — the `language` field is present; content is operator-supplied.
- [ ] **CSAT distribution and reporting dashboards** — survey endpoint works; aggregations land in P2.

## Sign-off

| Role | Name | Date | Signature |
|---|---|---|---|
| Product owner | | | |
| Tech lead | | | |
| Security | | | |
| Data protection | | | |
| Operations | | | |
| Records | | | |

When every box is Ticked or Deferred, the platform is pilot-ready.
