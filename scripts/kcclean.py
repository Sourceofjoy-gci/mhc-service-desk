#!/usr/bin/env python
"""Surgical Keycloak H2 reset: move DB files to .bak so a fresh start re-bootstraps admin.

Use this when Keycloak's persisted state has drifted from the realm-mhc.json
source of truth (e.g. missing client scopes / mappers after a botched import)
and you want a clean re-bootstrap from the JSON on next start. Keeps the old
H2 files in <file>.bak-<timestamp> for forensics.
"""
import subprocess, sys, time

stamp = int(time.time())
cmd = [
    "docker", "run", "--rm",
    "-v", "mhc-ticketing_keycloak-data:/data",
    "alpine", "sh", "-c",
    f"cd /data/h2 && ls -la && "
    f"for f in keycloakdb.mv.db keycloakdb.trace.db; do "
    f"  if [ -f \"$f\" ]; then mv \"$f\" \"$f.bak-{stamp}\" && echo \"moved $f\"; fi; "
    f"done && echo DONE && ls -la",
]
r = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:", r.stdout)
print("STDERR:", r.stderr)
print("RC:", r.returncode)
sys.exit(r.returncode)
