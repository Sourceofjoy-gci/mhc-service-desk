#!/usr/bin/env bash
# Local dev entrypoint. Runs migrations, then starts the dev server.
set -euo pipefail

echo "[backend] Waiting for database..."
python - <<'PY'
import os, time, sys
import psycopg
host = os.environ.get("POSTGRES_HOST", "postgres")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
user = os.environ.get("POSTGRES_USER", "mhc")
db   = os.environ.get("POSTGRES_DB", "mhc")
pwd  = os.environ.get("POSTGRES_PASSWORD", "")
dsn  = f"host={host} port={port} user={user} password={pwd} dbname={db}"
for i in range(60):
    try:
        with psycopg.connect(dsn, connect_timeout=2) as _:
            print("[backend] database is ready")
            sys.exit(0)
    except Exception:
        time.sleep(1)
print("[backend] database did not become ready in time", file=sys.stderr)
sys.exit(1)
PY

echo "[backend] Applying migrations..."
python manage.py migrate --noinput

echo "[backend] Collecting static files..."
python manage.py collectstatic --noinput || true

echo "[backend] Starting dev server..."
exec python manage.py runserver 0.0.0.0:8000
