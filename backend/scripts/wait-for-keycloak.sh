#!/usr/bin/env bash
# Wait for Keycloak to be ready, then seed a service account if requested.
set -euo pipefail

: "${KEYCLOAK_BASE_URL:?KEYCLOAK_BASE_URL is required}"
: "${KEYCLOAK_REALM:?KEYCLOAK_REALM is required}"
: "${KEYCLOAK_ADMIN:?KEYCLOAK_ADMIN is required}"
: "${KEYCLOAK_ADMIN_PASSWORD:?KEYCLOAK_ADMIN_PASSWORD is required}"

echo "[keycloak] Waiting for $KEYCLOAK_BASE_URL ..."
for i in {1..60}; do
  if curl -fsS "$KEYCLOAK_BASE_URL/health/ready" >/dev/null 2>&1; then
    echo "[keycloak] ready"
    exit 0
  fi
  sleep 2
done

echo "[keycloak] not ready after 120s" >&2
exit 1
