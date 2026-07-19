#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# MHC e-Ticketing — restore script
# WARNING: this will overwrite the live database and object store.
# Usage:  CONFIRM=1 ./scripts/restore.sh backups/<stamp>/backup.tar.gz.enc
# -----------------------------------------------------------------------------
set -euo pipefail

if [ "${CONFIRM:-0}" != "1" ]; then
  echo "Refusing to restore without CONFIRM=1" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a; . ./.env; set +a

ARCHIVE="${1:-}"
if [ -z "$ARCHIVE" ] || [ ! -f "$ARCHIVE" ]; then
  echo "Usage: CONFIRM=1 $0 <path-to-encrypted-backup>" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[restore] decrypting $ARCHIVE"
openssl enc -d -aes-256-gcm -pbkdf2 -pass "pass:${BACKUP_ENCRYPTION_KEY}" \
  -in "$ARCHIVE" | tar -xzf - -C "$TMP_DIR"

echo "[restore] restoring postgres"
docker compose exec -T postgres dropdb -U "${POSTGRES_USER:-mhc}" --if-exists "${POSTGRES_DB:-mhc}"
docker compose exec -T postgres createdb -U "${POSTGRES_USER:-mhc}" "${POSTGRES_DB:-mhc}"
cat "$TMP_DIR/db.dump" | docker compose exec -T postgres pg_restore -U "${POSTGRES_USER:-mhc}" -d "${POSTGRES_DB:-mhc}"

echo "[restore] restoring MinIO objects"
docker compose stop minio >/dev/null
docker run --rm \
  -v mhc-ticketing_minio-data:/data \
  -v "$TMP_DIR":/in \
  alpine:3.20 sh -c "rm -rf /data/* && tar -xzf /in/objects.tar.gz -C /data"
docker compose start minio >/dev/null

echo "[restore] complete. Run migrations if schema changed."
