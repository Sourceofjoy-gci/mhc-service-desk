"""End-to-end smoke test for M2.

Exercises:
  * list  — `/api/v1/tickets/`
  * kanban — `/api/v1/tickets/kanban/`
  * dashboard — `/api/v1/tickets/dashboard/operational/`
  * transition — `/api/v1/tickets/{number}/transition/`
  * scope denial — IT agent should not see operational tickets
"""
import json
import sys

import requests

BASE = "http://localhost:8000/api/v1"


def must(resp, expected=200, label=""):
    if resp.status_code != expected:
        print(f"FAIL {label}: HTTP {resp.status_code} — {resp.text[:300]}")
        sys.exit(2)
    print(f"OK   {label}: HTTP {resp.status_code}")


def main():
    # 1. List
    r = requests.get(f"{BASE}/tickets/", headers={"Authorization": "Bearer dev:alice:ops-agents"})
    must(r, 200, "list operational (alice/ops-agents)")
    data = r.json()
    if isinstance(data, dict):
        items = data.get("results", [])
    else:
        items = data
    print(f"     results={len(items)}")

    # 2. Kanban
    r = requests.get(f"{BASE}/tickets/kanban/?domain=operational", headers={"Authorization": "Bearer dev:alice:ops-agents"})
    must(r, 200, "kanban operational")
    cols = r.json().get("columns", {})
    print(f"     columns: {list(cols.keys())}")
    for code, items in cols.items():
        print(f"       {code}: {len(items)} ticket(s)")

    # 3. Dashboard (no auth required)
    r = requests.get(f"{BASE}/tickets/dashboard/operational/")
    must(r, 200, "dashboard")
    print(f"     {r.text[:200]}")

    # 4. Create a fresh ticket for transition tests
    payload = {
        "request_type_code": "HOURS",
        "service_code": "GEN-INFO",
        "office_code": "MHC-MBA",
        "title": "Smoke transition test",
        "description": "Created by m2_smoke.py for transition assertions.",
        "requester_name": "Smoke Test",
        "requester_email": "smoke-transition@example.com",
        "consent": True,
    }
    r = requests.post(f"{BASE}/tickets/public/intake/", json=payload, timeout=5)
    must(r, 201, "create ticket for transition")
    ticket_number = r.json()["ticket_number"]
    print(f"     ticket={ticket_number}")

    # 5. Transition: new -> triage
    r = requests.post(
        f"{BASE}/tickets/{ticket_number}/transition/",
        headers={"Authorization": "Bearer dev:alice:ops-agents", "Content-Type": "application/json"},
        json={"to_status": "triage", "reason": "smoke test"},
    )
    must(r, 200, "transition new->triage")
    ticket = r.json()
    print(f"     status={ticket['status_code']} number={ticket['number']}")

    # 6. Transition: triage -> in_progress
    r = requests.post(
        f"{BASE}/tickets/{ticket_number}/transition/",
        headers={"Authorization": "Bearer dev:alice:ops-agents", "Content-Type": "application/json"},
        json={"to_status": "in_progress"},
    )
    must(r, 200, "transition triage->in_progress")

    # 7. Invalid transition (should 400)
    r = requests.post(
        f"{BASE}/tickets/{ticket_number}/transition/",
        headers={"Authorization": "Bearer dev:alice:ops-agents", "Content-Type": "application/json"},
        json={"to_status": "new"},
    )
    must(r, 400, "reject invalid transition (in_progress->new)")

    # 7. IT scope denial: an IT agent should not see operational tickets
    r = requests.get(f"{BASE}/tickets/", headers={"Authorization": "Bearer dev:bob:it-agents"})
    must(r, 200, "list as IT agent (bob/it-agents)")
    data = r.json()
    items = data if isinstance(data, list) else data.get("results", [])
    op_count = sum(1 for t in items if t["domain"] == "operational")
    if op_count > 0:
        print(f"FAIL scope: IT agent sees {op_count} operational tickets")
        sys.exit(3)
    print(f"OK   scope: IT agent sees 0 operational tickets (correct)")

    # 8. Add a public reply
    r = requests.post(
        f"{BASE}/tickets/{ticket_number}/messages/",
        headers={"Authorization": "Bearer dev:alice:ops-agents", "Content-Type": "application/json"},
        json={"body_text": "We will get back to you within one business day."},
    )
    must(r, 201, "add reply message")

    # 9. Add an internal note
    r = requests.post(
        f"{BASE}/tickets/{ticket_number}/notes/",
        headers={"Authorization": "Bearer dev:alice:ops-agents", "Content-Type": "application/json"},
        json={"body": "Spoke with requester. They're after business hours for the public holiday."},
    )
    must(r, 201, "add internal note")

    # 10. Detail
    r = requests.get(f"{BASE}/tickets/{ticket_number}/", headers={"Authorization": "Bearer dev:alice:ops-agents"})
    must(r, 200, "detail")
    detail = r.json()
    print(f"     messages={len(detail.get('messages', []))} notes={len(detail.get('notes', []))}")

    print("\nAll M2 smoke checks passed ✅")


if __name__ == "__main__":
    main()
