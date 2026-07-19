"""Secret strength audit for the .env file.

Two tiers of findings:

  * FAIL  — the value contains a known placeholder ("change-me",
            "example", etc.) or is empty. These are never acceptable
            and would also fail the prod settings fail-fast check
            (``config/settings/prod.py``).

  * WARN  — the value is short (< 24 chars) or lacks character diversity.
            The operator may have chosen a deliberately short password.
            Use ``--strict`` to make WARN exit non-zero (matches
            prod-settings behaviour for the canonical secret list).

Exit codes:
  0  no FAIL
  1  one or more FAIL findings (placeholders found)
  2  .env is missing or unreadable

Use ``--json`` to emit machine-readable output suitable for CI.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

# Variables that must be strong. Same set used by
# config/settings/prod.py for the production fail-fast check.
PROD_FAILFAST_SECRETS = [
    "DJANGO_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "RABBITMQ_PASSWORD",
    "MINIO_ROOT_PASSWORD",
    "KEYCLOAK_ADMIN_PASSWORD",
    "BACKUP_ENCRYPTION_KEY",
]

# Heuristic list of "this looks like a secret" substrings.
SECRET_HINTS = ("PASSWORD", "SECRET", "KEY", "TOKEN", "ENCRYPTION")

# Substrings that always FAIL — these are placeholders / shared defaults.
PLACEHOLDER_PATTERNS = [
    "change-me", "change_me", "changeme", "ch@nge",
    "example", "sample", "demo", "your-", "my-",
    "password", "passw0rd",
    "qwerty", "asdf", "zxcv",
    "mhc-mhc", "mhc123", "1234", "12345", "123456", "admin", "root",
]

# Quality rules — these are WARN only, never FAIL on their own.
HAS_UPPER = re.compile(r"[A-Z]")
HAS_LOWER = re.compile(r"[a-z]")
HAS_DIGIT = re.compile(r"\d")
HAS_SYMBOL = re.compile(r"[^A-Za-z0-9]")


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        print(f"[audit] .env not found at {path}", file=sys.stderr)
        sys.exit(2)
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def is_secret(key: str) -> bool:
    upper = key.upper()
    if upper in PROD_FAILFAST_SECRETS:
        return True
    if "PASSWORD" in upper or "_SECRET" in upper or "_TOKEN" in upper:
        return True
    if "_ENCRYPTION_KEY" in upper:
        return True
    # Exclude obvious public config that happens to contain a hint word.
    if upper in {
        "KEYCLOAK_ADMIN", "KEYCLOAK_REALM", "KEYCLOAK_BASE_URL",
        "KEYCLOAK_PUBLIC_URL", "KEYCLOAK_CLIENT_ID", "KEYCLOAK_BOOTSTRAP",
    }:
        return False
    return False


def classify(value: str) -> tuple[str, list[str]]:
    """Return (status, reasons).

    FAIL only on a placeholder substring — short-but-deliberate passwords
    are reported as WARN, never FAIL.
    """
    reasons: list[str] = []
    if not value:
        return "FAIL", ["empty"]
    lowered = value.lower()
    for needle in PLACEHOLDER_PATTERNS:
        if needle in lowered:
            reasons.append(f"contains placeholder '{needle}'")
    if len(value) < 24:
        reasons.append(f"short ({len(value)} chars)")
    if not HAS_UPPER.search(value):
        reasons.append("no uppercase")
    if not HAS_LOWER.search(value):
        reasons.append("no lowercase")
    if not HAS_DIGIT.search(value):
        reasons.append("no digit")
    if not HAS_SYMBOL.search(value):
        reasons.append("no symbol")
    hard = any("placeholder" in r for r in reasons)
    quality = [r for r in reasons if "placeholder" not in r]
    if hard:
        return "FAIL", reasons
    if quality:
        return "WARN", reasons
    return "PASS", []


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit .env secret strength")
    parser.add_argument("--strict", action="store_true", help="Treat WARN as a failure")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    args = parser.parse_args()

    env = load_env(ENV_FILE)
    findings: list[dict] = []
    fail_count = 0
    warn_count = 0
    pass_count = 0
    for key, value in env.items():
        if not is_secret(key):
            continue
        status, reasons = classify(value)
        findings.append({"key": key, "len": len(value), "status": status, "reasons": reasons})
        if status == "FAIL":
            fail_count += 1
        elif status == "WARN":
            warn_count += 1
        else:
            pass_count += 1

    if args.json:
        print(json.dumps({
            "strict": args.strict,
            "summary": {"pass": pass_count, "warn": warn_count, "fail": fail_count},
            "findings": findings,
        }, indent=2))
    else:
        print(f"{'KEY':<32} {'LEN':>4}  {'STATUS':<6}  NOTES")
        print("-" * 90)
        for f in findings:
            note = "; ".join(f["reasons"]) if f["reasons"] else "ok"
            print(f"{f['key']:<32} {f['len']:>4}  {f['status']:<6}  {note}")
        print()
        print(f"summary: {pass_count} pass, {warn_count} warn, {fail_count} fail")

    if fail_count:
        return 1
    if args.strict and warn_count:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
