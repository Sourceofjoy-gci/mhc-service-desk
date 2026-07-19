"""Post-rotation smoke: list + create + kanban after password rotation."""
import sys
import requests

BASE = "http://localhost:8000/api/v1"
TOKEN = "Bearer dev:alice:ops-agents"


def must(resp, expected, label):
    if resp.status_code != expected:
        print(f"FAIL {label}: HTTP {resp.status_code} — {resp.text[:200]}")
        sys.exit(2)
    print(f"OK   {label}: HTTP {resp.status_code}")


def main():
    r = requests.get(f"{BASE}/tickets/", headers={"Authorization": TOKEN})
    must(r, 200, "list existing tickets")
    items = r.json() if isinstance(r.json(), list) else r.json().get("results", [])
    print(f"     {len(items)} tickets survived rotation")

    r = requests.post(f"{BASE}/tickets/public/intake/", json={
        "request_type_code": "HOURS",
        "service_code": "GEN-INFO",
        "office_code": "MHC-MBA",
        "title": "Post-rotation test",
        "description": "Verifying new env is live.",
        "requester_name": "Rotation Tester",
        "requester_email": "rotation@example.com",
        "consent": True,
    }, timeout=5)
    must(r, 201, "create ticket after rotation")
    print(f"     new={r.json().get('ticket_number')}")

    r = requests.get(f"{BASE}/tickets/kanban/?domain=operational", headers={"Authorization": TOKEN})
    must(r, 200, "kanban after rotation")
    print(f"     columns={list(r.json().get('columns', {}).keys())}")

    r = requests.get(f"{BASE}/tickets/dashboard/operational/")
    must(r, 200, "dashboard after rotation")

    print("\nPost-rotation smoke OK ✅")


if __name__ == "__main__":
    main()
