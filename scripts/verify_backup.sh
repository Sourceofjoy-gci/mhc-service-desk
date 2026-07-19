#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Backup verification drill — actually runs backup, restores to a side DB,
# asserts row counts match the live DB on every key table, and exits non-zero
# on any mismatch. Designed to be run weekly from cron (NFR-015).
#
# Usage:  ./scripts/verify_backup.sh
# Output: exit 0 on success, non-zero with detail on failure
# Side effects: creates a `verify_<timestamp>` database; the side DB is
# dropped on success and on failure.
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

VERIFY_DB="mhc_verify_$(date -u +%Y%m%dT%H%M%SZ)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$ROOT/backups/verify-$TS"
mkdir -p "$OUT_DIR"

# Live row counts
echo "[verify] collecting live row counts"
LIVE_FILE="$OUT_DIR/live_counts.txt"
docker compose exec -T postgres psql -U "${POSTGRES_USER:-mhc}" -d "${POSTGRES_DB:-mhc}" -t -A -F'|' -c "
SELECT 'ticket',                 count(*) FROM ticket
UNION ALL SELECT 'ticket_message',        count(*) FROM ticket_message
UNION ALL SELECT 'ticket_note',           count(*) FROM ticket_note
UNION ALL SELECT 'ticket_link',           count(*) FROM ticket_link
UNION ALL SELECT 'workflow_status',       count(*) FROM workflow_status
UNION ALL SELECT 'workflow_transition',   count(*) FROM workflow_transition
UNION ALL SELECT 'workflow_transition_history', count(*) FROM workflow_transitionhistory
UNION ALL SELECT 'sla_instance',          count(*) FROM sla_instance
UNION ALL SELECT 'sla_policy',            count(*) FROM sla_policy
UNION ALL SELECT 'catalogue_service',     count(*) FROM catalogue_service
UNION ALL SELECT 'catalogue_request_type', count(*) FROM catalogue_request_type
UNION ALL SELECT 'contact',               count(*) FROM contact
UNION ALL SELECT 'org_office',            count(*) FROM org_office
UNION ALL SELECT 'audit_auditlog',        count(*) FROM audit_auditevent
UNION ALL SELECT 'file_attachment',       count(*) FROM file_attachment
UNION ALL SELECT 'integration_integrationevent', count(*) FROM integrationevent
UNION ALL SELECT 'whatsapp_whatsappmessage', count(*) FROM whatsapp_whatsappmessage
UNION ALL SELECT 'knowledge_knowledgearticle', count(*) FROM knowledge_article
" > "$LIVE_FILE"

# Create a fresh backup (re-uses scripts/backup.sh logic)
echo "[verify] creating fresh backup"
TMP_DIR="$(mktemp -d)"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-mhc}" -Fc "${POSTGRES_DB:-mhc}" \
  > "$TMP_DIR/db.dump"

echo "[verify] snapshotting MinIO objects"
docker compose stop minio >/dev/null
docker run --rm \
  -v mhc-ticketing_minio-data:/data:ro \
  -v "$TMP_DIR":/out \
  alpine:3.20 sh -c "tar -czf /out/objects.tar.gz -C /data ."
docker compose start minio >/dev/null

# Provision a side DB
echo "[verify] provisioning side database $VERIFY_DB"
docker compose exec -T postgres psql -U "${POSTGRES_USER:-mhc}" -d postgres -c "DROP DATABASE IF EXISTS $VERIFY_DB" >/dev/null
docker compose exec -T postgres createdb -U "${POSTGRES_USER:-mhc}" "$VERIFY_DB"
cat "$TMP_DIR/db.dump" \
  | docker compose exec -T postgres pg_restore -U "${POSTGRES_USER:-mhc}" -d "$VERIFY_DB" --no-owner --no-privileges
docker compose exec -T postgres psql -U "${POSTGRES_USER:-mhc}" -d "$VERIFY_DB" -c "ANALYZE" >/dev/null

# Restored row counts
echo "[verify] collecting restored row counts"
REST_FILE="$OUT_DIR/restored_counts.txt"
docker compose exec -T postgres psql -U "${POSTGRES_USER:-mhc}" -d "$VERIFY_DB" -t -A -F'|' -c "
SELECT 'ticket',                 count(*) FROM ticket
UNION ALL SELECT 'ticket_message',        count(*) FROM ticket_message
UNION ALL SELECT 'ticket_note',           count(*) FROM ticket_note
UNION ALL SELECT 'ticket_link',           count(*) FROM ticket_link
UNION ALL SELECT 'workflow_status',       count(*) FROM workflow_status
UNION ALL SELECT 'workflow_transition',   count(*) FROM workflow_transition
UNION ALL SELECT 'workflow_transition_history', count(*) FROM workflow_transitionhistory
UNION ALL SELECT 'sla_instance',          count(*) FROM sla_instance
UNION ALL SELECT 'sla_policy',            count(*) FROM sla_policy
UNION ALL SELECT 'catalogue_service',     count(*) FROM catalogue_service
UNION ALL SELECT 'catalogue_request_type', count(*) FROM catalogue_request_type
UNION ALL SELECT 'contact',               count(*) FROM contact
UNION ALL SELECT 'org_office',            count(*) FROM org_office
UNION ALL SELECT 'audit_auditevent',      count(*) FROM audit_auditevent
UNION ALL SELECT 'file_attachment',       count(*) FROM file_attachment
UNION ALL SELECT 'integrationevent',      count(*) FROM integrationevent
UNION ALL SELECT 'whatsapp_whatsappmessage', count(*) FROM whatsapp_whatsappmessage
UNION ALL SELECT 'knowledge_article',     count(*) FROM knowledge_article
" > "$REST_FILE"

# Diff
echo "[verify] diffing counts"
DIFF_FILE="$OUT_DIR/diff.txt"
if diff "$LIVE_FILE" "$REST_FILE" > "$DIFF_FILE"; then
    echo "[verify] PASS: row counts match"
    cat "$OUT_DIR/live_counts.txt" | head -5
    echo "..."
    docker compose exec -T postgres psql -U "${POSTGRES_USER:-mhc}" -d postgres -c "DROP DATABASE $VERIFY_DB" >/dev/null
    rm -rf "$TMP_DIR"
    echo "[verify] evidence in $OUT_DIR"
    exit 0
else
    echo "[verify] FAIL: row counts differ"
    cat "$DIFF_FILE"
    echo "[verify] side DB $VERIFY_DB kept for inspection"
    exit 1
fi
