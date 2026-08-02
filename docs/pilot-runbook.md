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
   * `EMAIL_WEBHOOK_SECRET`, `WHATSAPP_APP_SECRET`, and
     `WHATSAPP_VERIFY_TOKEN` — generate independently and store only in the
     secret manager. Never reuse provider access tokens as webhook secrets.
5. Mount the TLS certificates into `infrastructure/nginx/ssl/`.
6. Bring the stack up:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```
7. Apply migrations and seed:
   ```bash
   docker compose exec -T backend python manage.py migrate
   docker compose exec -T backend python manage.py migrate --check
   docker compose exec -T backend python /app/scripts/seed_dev.py
   python scripts/seed_keycloak_user.py   # creates 'alice' in the mhc realm
   ```
   If this environment previously applied an earlier revision of the unshipped
   `sla.0004_backfill_paused_remaining_business_seconds` migration, migration
   history will not rerun the revised data operation. Manually reconcile its
   affected paused SLA rows before use. Fresh deployments and the current live
   pilot rows use the corrected semantics.
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
| Email/WhatsApp webhook secrets and verification token | 90 days or immediately after suspected disclosure | Rotate with the provider, redeploy backend, and verify signed challenge/event delivery before retiring the old value |
| `BACKUP_ENCRYPTION_KEY` | 365 days | Re-encrypt existing backups first, then rotate |
| TLS certificates | auto (Let's Encrypt) or 30 days before expiry | `CertificateExpiringSoon` alert fires 14d early |

### 3.4 Access review

* Quarterly: review every `Role` and `UserRole` row; remove ex-staff.
* Quarterly: review Keycloak group memberships (`ops-supervisors`,
  `lead-it`, `system-admins`).
* Quarterly: review `MfaRequired` exemption list.
* Quarterly: review `WhitelistIP` (when added) and `IntegrationToken` set.

### 3.5 Channel webhook operations

* Treat the email and WhatsApp endpoints as public transport, not anonymous
  trust. Configure the required secrets and provider/account identifiers, then
  validate signed challenge/event delivery using
  [`channel-webhook-contract.md`](channel-webhook-contract.md).
* Monitor rejected signature, stale timestamp, replay, unknown account, and
  unknown provider-message outcomes without logging secrets or requester
  message bodies.
* Do not activate outbound WhatsApp in production yet. Provider approval and
  credentials are necessary but not sufficient: the P1 leased idempotent
  dispatch/retry worker and API-retry deduplication must ship first.

### 3.6 Retention and disposal

* Before enabling disposal, record the formally approved table/day mapping in
  the `retention.policy.v1` `ConfigItem`. The values shown by the built-in
  preview schedule are not an approval and are never used for deletion.
* `manage.py apply_retention --dry-run` — previews what would be disposed. If
  no policy is configured, it clearly labels the built-in schedule as an
  unapproved preview. Preview artifacts use the distinct
  `disposal-preview-<timestamp>.json` name and the
  `mhc.retention.preview.v1` schema with `mode=preview`,
  `status=not_executed`, and `rows_selected`; they never claim rows were
  disposed.
* `manage.py apply_retention` — refuses to run without a valid configured
  policy. It preflights raw SQL and ORM candidate queries, locks candidate
  tickets and all hold-bearing message/note rows, revalidates legal holds, and
  applies the complete database run in one transaction. A held ticket, message,
  or note preserves the whole ticket graph. A parent is not selected while a
  cascade or `SET NULL` dependent is still inside its own retention window.
* The committed `DisposalEvent` row is the source of truth. Attachment metadata
  is removed only after an exact bucket/key/version deletion job has been
  enqueued in that same transaction; legacy attachment rows without exact
  version ownership fail closed. The minute-scheduled retention side-effects
  worker retries those jobs idempotently and never falls back to a key-only
  delete.
* A final `mhc.retention.disposal-certificate.v1` certificate is exported only
  after the database commit and all object cleanup jobs complete. Its filename
  includes the committed event UUID. A commit failure therefore cannot publish
  a final certificate. Export/link/`fsync` failures leave the committed event
  retriable with `manage.py apply_retention --retry-event <uuid>` and do not
  repeat deletion.
* The certificate output directory must support same-filesystem hard links and
  `fsync` for both files and directories. A retry accepts an existing file only
  when its canonical contents exactly match the committed event; a mismatched
  path is treated as a hard collision.
* Schedule monthly via cron only after the policy has been formally approved
  and configured.
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

### 5.2 Intake returns 401

* Symptom: a call-centre or walk-in submission returns "Authentication
  credentials were not provided."
* Cause: public intake is disabled for this phase and the staff session or
  access token is missing or expired.
* Fix: sign in through Keycloak and retry the staff intake. Do not expose or
  bypass the intake endpoint for anonymous callers.

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

### 5.6 Keycloak sign-in broken (agents get dead-end / tokens have no claims)

* Symptom: `/login` page either shows a stale "wired in M2" stub, or
  Keycloak issues tokens with no `sub` / `preferred_username` / `groups`,
  or the backend returns 401 `"Token is missing the 'aud' claim"` / 500
  `IntegrityError` on `identity_user_username_key`.
* Cause: the persisted realm has drifted from `infrastructure/keycloak/realm-mhc.json`
  — usually after a manual change via the admin console, an interrupted
  first start, or a botched re-import. The realm file may have changed
  on disk but Keycloak only re-imports when the realm doesn't yet exist.
* Fix: see section 7 below.

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

## 7. Keycloak realm recovery

Use this procedure when the `mhc` realm has drifted from the JSON source
of truth (`infrastructure/keycloak/realm-mhc.json`) and section 5.6 doesn't
resolve with a simple restart. The two recovery scripts
(`scripts/kcclean.py` and `scripts/seed_keycloak_user.py`) are designed
to be safe to re-run.

### 8.1 Symptoms that indicate realm drift

* `/login` page shows a "Sign in" button but clicking it fails
  immediately or returns you to the page logged out.
* Access tokens from Keycloak have `scope: groups` only and **no** `sub`,
  `preferred_username`, `email`, or `groups` claims.
* Backend logs show `psycopg.errors.UniqueViolation: identity_user_username_key`
  the first time a user authenticates.
* Backend logs show `Token verification failed: Token is missing the "aud" claim`.
* `Keycloak admin → Realm mhc → Client scopes` shows `openid`, `profile`,
  or `email` scopes missing entirely, OR the `groups` scope has no
  protocol mappers underneath it.

### 8.2 The fix in three commands

```bash
# 1. Surgically reset the H2 database so Keycloak re-bootstraps from JSON
#    (master admin from .env + realm from realm-mhc.json).
#    Old H2 files are kept as <file>.bak-<timestamp> for forensics.
docker compose stop keycloak
python scripts/kcclean.py
docker compose start keycloak

# 2. Wait for Keycloak to be healthy (~1 min), then re-seed the
#    dev/pilot user. Idempotent — safe to run repeatedly.
python scripts/seed_keycloak_user.py

# 3. Verify the token actually carries the claims the backend needs.
python -c "
import urllib.request, urllib.parse, json, base64
b = urllib.parse.urlencode({'username':'alice','password':'p@ssw0rd','grant_type':'password','client_id':'mhc-frontend'}, quote_via=urllib.parse.quote).encode()
r = json.loads(urllib.request.urlopen(urllib.request.Request('http://localhost:8080/realms/mhc/protocol/openid-connect/token', data=b, method='POST', headers={'Content-Type':'application/x-www-form-urlencoded'})).read())
payload = json.loads(base64.urlsafe_b64decode(r['access_token'].split('.')[1] + '==='))
assert all(k in payload for k in ('sub', 'preferred_username', 'email', 'groups', 'azp')), payload
assert payload['azp'] == 'mhc-frontend', payload
print('OK: token has', sorted(payload.keys()))
"
```

If the assertion passes, sign-in is restored. Update any
operator-Keycloak-only users via the admin console afterwards
(`http://localhost:8080` → realm `mhc` → Users).

### 8.3 Why this works

* Keycloak's `--import-realm` only applies `realm-mhc.json` when the
  realm doesn't yet exist in its database. Once a realm exists, the
  file is ignored on subsequent starts. That means a fix to
  `realm-mhc.json` only takes effect after a clean slate.
* `kcclean.py` moves the live H2 files aside (keeping them as `.bak` for
  forensics) without nuking the whole `keycloak-data` volume. On next
  start, Keycloak re-creates the H2 DB, bootstraps the master admin from
  `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` in `.env`, and re-imports
  the realm from JSON.
* `seed_keycloak_user.py` re-creates the dev/pilot user `alice` in the
  `mhc` realm, joins her to `ops-agents` (which grants `staff` +
  `agent-operational` via the group's `realmRoles` mapping), and sets
  a non-temporary password. Re-running is safe: it looks up by username,
  updates the password and group membership rather than failing on
  duplicate.

### 8.4 Common gotchas

* **Old BACKUP_ENCRYPTION_KEY.** Rotating that key invalidates older
  encrypted backups. Stash the previous key in a secure note if you have
  pre-rotation backups you may need to restore.
* **The master admin password is set from `.env` only on first start.**
  If you re-bootstrap and `.env` has a different value, the persisted
  master admin (from before the reset) is gone and a new one is created
  with the `.env` value. If you can't log in after a re-bootstrap, check
  the latest `.env`.
* **Public SPA clients (like `mhc-frontend`) don't get an `aud` claim on
  their access tokens in Keycloak 26 — only `azp`.** The realm includes
  an `oidc-audience-mapper` on the client that adds `mhc-backend` to
  `aud` so the backend's `verify_aud` check passes. If you re-import
  the realm from a stale or hand-edited JSON that lacks this mapper,
  re-do the recovery.
* **The realm-mhc.json `clientScopes[].protocolMappers[]` field name is
  `protocolMappers` (with the `s`)** — Keycloak silently drops anything
  under `mappers`. Verify with `git grep protocolMappers infrastructure/`
  after any future realm edit.

### 8.5 After recovery

1. Open a brief incident note (what drifted, when, why, and which
   command fixed it).
2. Commit any new scripts or `.env` updates that were needed.
3. If the drift came from a manual change via the admin console, mirror
   that change into `realm-mhc.json` so the next re-import reproduces it.
4. If the drift came from a bad `realm-mhc.json` edit, add a code-review
   note for the next person to look at scope / mapper / audience changes
   carefully.

## 8. Compliance evidence to collect

Every quarter, archive:
* Backup verification drill evidence (`backups/verify-*`).
* Retention disposal certificates (`backups/disposal-*`).
* Access review sign-offs (one PDF per quarter).
* Key rotation log.
* DPIA review notes.
* Incident post-mortems.

This evidence is what you present at the next steering committee.
