#!/usr/bin/env python
"""Seed a Keycloak user in the 'mhc' realm for frontend login.

Idempotent: re-running with the same username updates the password and group
membership rather than failing on a duplicate. Uses the master realm admin
account (admin / KEYCLOAK_ADMIN_PASSWORD) to mint an admin token, then talks
to the Keycloak Admin REST API.

Usage:
    python scripts/seed_keycloak_user.py [--username alice] [--password p@ssw0rd] [--group ops-agents] [--office MBB] [--station Counter-1]
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
import urllib.request
import json

KEYCLOAK_BASE = os.environ.get("KEYCLOAK_BASE_URL", "http://localhost:8080")
REALM = "mhc"


def _http(method: str, url: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            if not raw:
                return r.status, {}
            return r.status, json.loads(raw.decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def get_admin_token(admin_user: str, admin_password: str) -> str:
    body = urllib.parse.urlencode({
        "username": admin_user,
        "password": admin_password,
        "grant_type": "password",
        "client_id": "admin-cli",
    }).encode()
    req = urllib.request.Request(
        f"{KEYCLOAK_BASE}/realms/master/protocol/openid-connect/token",
        data=body, method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["access_token"]


def find_user(token: str, username: str) -> dict | None:
    qs = urllib.parse.urlencode({"username": username, "exact": "true"})
    code, body = _http("GET", f"{KEYCLOAK_BASE}/admin/realms/{REALM}/users?{qs}", token)
    if code != 200:
        raise RuntimeError(f"user lookup failed: HTTP {code} {body}")
    if isinstance(body, list) and body:
        return body[0]
    return None


def create_user(
    token: str,
    username: str,
    first: str,
    last: str,
    email: str,
    attributes: dict | None = None,
) -> dict:
    payload = {
        "username": username,
        "enabled": True,
        "firstName": first,
        "lastName": last,
        "email": email,
        "emailVerified": True,
    }
    if attributes:
        payload["attributes"] = attributes
    code, body = _http("POST", f"{KEYCLOAK_BASE}/admin/realms/{REALM}/users", token, payload)
    if code not in (201, 204):
        raise RuntimeError(f"create user failed: HTTP {code} {body}")
    user = find_user(token, username)
    if not user:
        raise RuntimeError("user create returned no body and lookup failed")
    return user


def set_password(token: str, user_id: str, password: str) -> None:
    payload = {"type": "password", "value": password, "temporary": False}
    code, body = _http("PUT", f"{KEYCLOAK_BASE}/admin/realms/{REALM}/users/{user_id}/reset-password", token, payload)
    if code not in (204,):
        raise RuntimeError(f"set password failed: HTTP {code} {body}")


def update_user_attributes(token: str, user: dict, attributes: dict) -> None:
    """Merge attributes into an existing user and PUT the representation back."""
    if not attributes:
        return
    payload = dict(user)
    merged = dict(payload.get("attributes") or {})
    merged.update(attributes)
    payload["attributes"] = merged
    code, body = _http(
        "PUT",
        f"{KEYCLOAK_BASE}/admin/realms/{REALM}/users/{user['id']}",
        token,
        payload,
    )
    if code not in (204,):
        raise RuntimeError(f"update user attributes failed: HTTP {code} {body}")


def find_group(token: str, group_path: str) -> dict | None:
    code, body = _http("GET", f"{KEYCLOAK_BASE}/admin/realms/{REALM}/groups", token)
    if code != 200:
        raise RuntimeError(f"group list failed: HTTP {code} {body}")
    for g in body or []:
        if g.get("path") == group_path:
            return g
    return None


def join_group(token: str, user_id: str, group_id: str) -> None:
    code, body = _http(
        "PUT",
        f"{KEYCLOAK_BASE}/admin/realms/{REALM}/users/{user_id}/groups/{group_id}",
        token,
    )
    if code not in (204,):
        raise RuntimeError(f"join group failed: HTTP {code} {body}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", default="alice")
    ap.add_argument("--password", default="p@ssw0rd")
    ap.add_argument("--first", default="Alice")
    ap.add_argument("--last", default="Ops")
    ap.add_argument("--email", default="alice@mhc.local")
    ap.add_argument("--group", default="ops-agents",
                    help="Realm group path, e.g. ops-agents, it-agents, system-admins")
    ap.add_argument("--office", default="", help="Office code, e.g. MBB")
    ap.add_argument("--station", default="", help="Station name within the office")
    ap.add_argument("--admin-user", default=os.environ.get("KEYCLOAK_ADMIN", "admin"))
    ap.add_argument("--admin-password", default=os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "p@ssw0rd"))
    args = ap.parse_args()

    print(f"== Keycloak user seed ({REALM} realm) ==")
    print(f"   keycloak={KEYCLOAK_BASE}  username={args.username}  group=/{args.group}")

    token = get_admin_token(args.admin_user, args.admin_password)
    print(f"   master admin token: ok")

    attributes: dict[str, list[str]] = {}
    if args.office:
        attributes["office"] = [args.office]
    if args.station:
        attributes["station"] = [args.station]

    existing = find_user(token, args.username)
    if existing:
        user = existing
        print(f"   user exists: id={user['id']} — updating password, group & attributes")
        update_user_attributes(token, user, attributes)
    else:
        user = create_user(
            token, args.username, args.first, args.last, args.email, attributes
        )
        print(f"   user created: id={user['id']}")

    set_password(token, user["id"], args.password)
    print(f"   password set: ok (non-temporary)")

    group_path = f"/{args.group}"
    grp = find_group(token, group_path)
    if not grp:
        print(f"   WARN: group {group_path} not found in realm — skipping group join")
    else:
        join_group(token, user["id"], grp["id"])
        print(f"   group join: ok ({group_path} -> {', '.join(grp.get('realmRoles', []))})")

    print("\nSeed complete.")
    print(f"   Sign in at http://localhost:5173/login -> {args.username} / {args.password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
