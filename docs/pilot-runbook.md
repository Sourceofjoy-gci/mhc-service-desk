# Pilot Runbook — MHC e-Ticketing

This runbook is the operator's primary reference during the pilot. It
covers the deployment, the on-call rotation, common incidents and their
mitigations, the key-rotation schedule, and the access-review cadence.

> The pilot target: Office of the Master of the High Court, Mbabane (Main)
> and Manzini. ~50 staff, ~200 tickets/week, single-region.

## 1. Environment topology

```
                 ┌────────────────┐
   Internet ────►│  Nginx (TLS)   │──┐
                 │  rate limits   │  │
                 │  security h.  │  │
                 └─────┬─────────┘  │
                       │            │
            ┌──────────▼──────────┐ │
            │   Django (gunicorn) │ │  static assets served from
            │   workers, beat     │ │  frontend-static volume
            └─────┬───────────────┘ │
                  │                  │
   ┌──────────────┼──────────────┐   │
   │              │              │   │
┌──▼──┐  ┌───────▼──┐  ┌─────────▼─┐ │
│Pg  │  │ RabbitMQ  │  │  Redis    │ │
└────┘  └──────────┘  └───────────┘ │
                                    
   ┌──────────────┐  ┌──────────────┐
   │   MinIO      │  │  Keycloak    │
   │ attachments  │  │  OIDC + MFA  │
   └──────────────┘  └──────────────┘
                                    
   ┌──────────────┐  ┌──────────────┐
   │  Prometheus  │  │ Alertmanager │
   └──────────────┘  └──────────────┘
```

## 2. First-time deployment

1. Provision a Linux host (Ubuntu 22.04 LTS, 4 vCPU / 16 GB RAM / 100 GB SSD).
2. Install Docker Engine 24+ and the Compose plugin.
3. Create the secrets store. Use your platform's secret manager
   (HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, etc.). Never
   commit real secrets to `.env`.
4. Populate `.env` from the secrets store:
   * `DJANGO_SECRET_KEY` — `python manage.py shell -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
   * `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `RABBITMQ_PASSWORD`,
     `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`,
     `BACKUP_ENCRYPTION_KEY` — generate with `openssl rand -base64 32`
5. Mount the TLS certificates into `infrastructure/nginx/ssl/`.
6. Bring the stack up:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```
7. Apply migrations and seed:
   ```bash
   docker compose exec -T backend python manage.py migrate
   docker compose exec -T backend python /app/scripts/seed_dev.py
   ```
8. Configure Keycloak:
   * Sign in to <https://mhc-ticketing.local/admin> with `KEYCLOAK_ADMIN`.
   * Import `infrastructure/keycloak/realm-mhc.json` if not done automatically.
   * Under Realm Settings → Login, enable "User registration" OFF,
     "Remember Me" OFF, "Verify email" ON, "Login with email" ON.
   * Under Authentication → Flows, copy the "browser" flow and require
     OTP for every staff user. Save as `mhc-mfa`.
   * Bind this flow to a new required action `mhc-mfa`.
9. Smoke test the full stack:
   ```bash
   curl -s https://mhc-ticketing.local/api/v1/health | jq
   # expect: { "status": "ok", "checks": { "database": { "ok": true }, ... } }
   ```
10. Run a backup verification drill:
    ```bash
    ./scripts/verify_backup.sh
    ```

## 3. Day-2 operations

### 3.1 Health and metrics

* Health (readiness): `GET /api/v1/health` — checks Postgres, Redis, MinIO, Keycloak.
* Liveness: `GET /api/v1/health/live` — no dependency checks, no auth.
* Metrics: `GET /api/v1/metrics` (Prometheus exposition).
* Dashboards: Grafana at `https://mhc-ticketing.local:3000/grafana/`.

### 3.2 Backups

* Hourly base backups (`scripts/backup.sh`) — encrypted, written to
  `backups/`.
* Daily verification drill (`scripts/verify_backup.sh` or `.ps1`) — runs
  against a side DB, asserts row counts. Run from cron at 04:00 SAST.
* 30-day retention; old archives uploaded to the cold-storage bucket.
* RPO: 1 hour. RTO: 4 hours. Both measured end-to-end by the drill.

### 3.3 Secret rotation

| Secret | Cadence | Procedure |
|---|---|---|
| `DJANGO_SECRET_KEY` | 90 days | `manage.py rotate_secrets --what django`; redeploy; old key discarded after overlap window |
| DB / Redis / Rabbit / MinIO | 180 days | Rotate in the secret store, redeploy worker + beat first, then web |
| Keycloak admin | 90 days | Rotate in Keycloak admin console; redeploy backend |
| `BACKUP_ENCRYPTION_KEY` | 365 days | Re-encrypt existing backups first, then rotate |
| TLS certificates | auto (Let's Encrypt) or 30 days before expiry | `CertificateExpiringSoon` alert fires 14d early |

### 3.4 Access review

* Quarterly: review every `Role` and `UserRole` row; remove ex-staff.
* Quarterly: review Keycloak group memberships (`ops-supervisors`,
  `lead-it`, `system-admins`).
* Quarterly: review `MfaRequired` exemption list.
* Quarterly: review `WhitelistIP` (when added) and `IntegrationToken` set.

### 3.5 Retention and disposal

* `manage.py apply_retention --dry-run` — previews what would be disposed.
* `manage.py apply_retention` — actually disposes expired rows; writes a
  disposal certificate to `backups/disposal-<timestamp>.json`.
* Schedule monthly via cron.
* `manage.py sar_export --email <addr>` — produces a Subject Access
  Request bundle for a requester within their data-subject rights window.

## 4. On-call

* Primary on-call: 7-day rotation, handoff at 09:00 SAST Monday.
* Secondary on-call: shadow, escalates after 15 min no response.
* Communication: #mhc-ticketing-ops Slack; PagerDuty for `severity: critical` alerts.
* During business hours (08:00–17:00 SAST, Mon–Fri), page primary on-call
  for any `critical` alert. After hours, page only for:
  * `BackendDown` (5 min)
  * `HealthCheckDegraded` (10 min)
  * `DiskSpaceLow` (5 min)
  * `AttachmentInfectedDetected` (immediate)
  * any data-loss alert (immediate)

## 5. Common incidents

### 5.1 Backend won't start (prod)

* Symptom: gunicorn exits within 30s, `docker compose ps` shows
  `Restarting`.
* Cause: missing or weak secret.
* Fix: check `docker compose logs backend | grep ImproperlyConfigured`.
  Add the missing env var, redeploy.

### 5.2 Public intake returns 429s to legitimate users

* Symptom: callers see "Too many requests" even when sending 1 per minute.
* Cause: a single IP is behind a NAT; the `public_intake` zone is
  5/min/IP.
* Fix: have the caller authenticate via Keycloak (the rate limit
  switches to per-user). For one-off campaigns, temporarily raise
  `NGINX_intake_rate` in `infrastructure/nginx/conf.d/app.conf` and
  redeploy Nginx.

### 5.3 SLA evaluator stopped

* Symptom: `SlaEvaluatorStalled` alert fires; tickets do not move to
  `breached` automatically.
* Cause: beat container down or database lag.
* Fix: `docker compose ps beat`; if it's Restarting, see backend logs.
  If it's healthy but the evaluator is slow, run it manually:
  `docker compose exec -T backend python -c "from apps.sla.services import evaluate_open_slas; print(evaluate_open_slas())"`.

### 5.4 MinIO full

* Symptom: attachment upload returns 502.
* Cause: `mhc-attachments` bucket out of space.
* Fix: expand the MinIO volume, or move old attachments to the cold
  bucket per the retention policy.

### 5.5 Keycloak unreachable

* Symptom: `HealthCheckDegraded` for the `keycloak` check; agents see
  401s.
* Fix: `docker compose restart keycloak`. If that doesn't help, check
  Keycloak's DB (in our prod profile, Keycloak uses its own internal
  H2 by default; in production you should point it at Postgres).

## 6. Rollback

```bash
# Roll back to the previous image tag
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull backend:<previous-tag>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Database rollback (use the backup you want to restore)
CONFIRM=1 ./scripts/restore.sh backups/<timestamp>/backup.tar.gz.enc
```

After rollback:
1. Smoke test the affected area.
2. Open a post-mortem within 48h.
3. Update the runbook with what you learned.

## 7. Compliance evidence to collect

Every quarter, archive:
* Backup verification drill evidence (`backups/verify-*`).
* Retention disposal certificates (`backups/disposal-*`).
* Access review sign-offs (one PDF per quarter).
* Key rotation log.
* DPIA review notes.
* Incident post-mortems.

This evidence is what you present at the next steering committee.
