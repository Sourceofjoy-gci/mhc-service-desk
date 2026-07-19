"""One-shot: rotate POSTGRES_PASSWORD and BACKUP_ENCRYPTION_KEY, re-run the audit.

Generates two cryptographically strong secrets, patches them into .env,
rotates the live PostgreSQL role so the new password takes effect, then
rebuilds and re-runs the audit.

Side effect: any backup encrypted with the previous BACKUP_ENCRYPTION_KEY
will no longer be decryptable. The operator is expected to archive the
old key alongside the next backup rotation cycle.

Run with:  python scripts/rotate_and_audit.py
"""
from __future__ import annotations

import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"


def generate_strong() -> str:
    # 48 bytes of randomness → 64 base64url chars; meets every rule.
    return secrets.token_urlsafe(48)


def patch_env(new_pg: str, new_bkp: str) -> None:
    text = ENV_FILE.read_text(encoding="utf-8")
    text, n1 = re.subn(r"^POSTGRES_PASSWORD=.*$", f"POSTGRES_PASSWORD={new_pg}", text, flags=re.MULTILINE)
    text, n2 = re.subn(r"^BACKUP_ENCRYPTION_KEY=.*$", f"BACKUP_ENCRYPTION_KEY={new_bkp}", text, flags=re.MULTILINE)
    if n1 != 1 or n2 != 1:
        raise SystemExit(f"PATCH FAILED: POSTGRES_PASSWORD={n1}, BACKUP_ENCRYPTION_KEY={n2}")
    ENV_FILE.write_text(text, encoding="utf-8")


def shell(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(ROOT))
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {cmd}")
    return r.stdout


def main() -> int:
    new_pg = generate_strong()
    new_bkp = generate_strong()
    print(f"[rotate] new POSTGRES_PASSWORD      = {len(new_pg)} chars")
    print(f"[rotate] new BACKUP_ENCRYPTION_KEY  = {len(new_bkp)} chars")

    print("[rotate] patching .env")
    patch_env(new_pg, new_bkp)

    print("[rotate] rotating live postgres role")
    shell(
        f"docker compose exec -T postgres psql -U mhc -d mhc -c "
        f"\"ALTER USER mhc WITH PASSWORD '{new_pg}';\""
    )

    print("[rotate] restarting affected services")
    shell("docker compose up -d backend worker beat frontend")

    print("[rotate] waiting for backend to be healthy")
    for _ in range(30):
        out = shell("docker compose ps --format '{{.Service}}:{{.Status}}' backend")
        if "healthy" in out:
            print(f"[rotate] backend: {out.strip()}")
            break
        import time
        time.sleep(2)

    print()
    print("[rotate] re-running secret audit")
    print(shell("python scripts/audit_secrets.py").rstrip())
    audit_rc = subprocess.run(
        "python scripts/audit_secrets.py", shell=True, capture_output=True, text=True, cwd=str(ROOT)
    ).returncode
    print(f"[rotate] audit exit: {audit_rc}")
    return audit_rc


if __name__ == "__main__":
    sys.exit(main())
