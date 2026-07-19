#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# MHC e-Ticketing — backup script
# Dumps PostgreSQL, snapshots the MinIO attachments bucket, and writes
# a timestamped, encrypted archive to ./backups/.
# Usage:  ./scripts/backup.sh
# -----------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="$ROOT/backups/$STAMP"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$OUT_DIR"

echo "[backup] dumping postgres"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-mhc}" -Fc "${POSTGRES_DB:-mhc}" \
  > "$TMP_DIR/db.dump"

echo "[backup] syncing attachments from MinIO"
docker run --rm -v mhc-ticketing_minio-data:/data:ro \
    alpine:3.20 \
    sh -c "tar -czf /tmp/objects.tar.gz -C /data ." >/dev/null
docker run --rm \
    -v mhc-ticketing_minio-data:/data:ro \
    -v "$TMP_DIR":/out \
    alpine:3.20 \
    sh -c "tar -czf /out/objects.tar.gz -C /data ."

echo "[backup] writing keycloak realm export"
docker compose exec -T keycloak /opt/keycloak/bin/kc.sh export \
  --realm "${KEYCLOAK_REALM:-mhc}" --file /tmp/realm.json >/dev/null 2>&1 || true
docker compose cp keycloak:/tmp/realm.json "$TMP_DIR/realm.json" 2>/dev/null || true

cp docker-compose.yml "$TMP_DIR/"
cp .env "$TMP_DIR/" 2>/dev/null || true

echo "[backup] creating encrypted archive"
tar -czf - -C "$TMP_DIR" . \
  | openssl enc -aes-256-gcm -salt -pbkdf2 -pass "pass:${BACKUP_ENCRYPTION_KEY}" \
  > "$OUT_DIR/backup.tar.gz.enc"

sha256sum "$OUT_DIR/backup.tar.gz.enc" > "$OUT_DIR/backup.sha256"

echo "[backup] complete: $OUT_DIR"
ls -lh "$OUT_DIR"
