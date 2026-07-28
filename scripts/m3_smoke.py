"""M3 smoke: IT child-ticket pattern + email intake + scope guard."""
import importlib
import sys
from pathlib import Path

import requests

REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
if REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, REPOSITORY_ROOT)
pilot_helpers = importlib.import_module("backend.scripts.pilot_foundation_smoke")

BASE = "http://localhost:8000/api/v1"
REQUEST_TIMEOUT = 10
OPS_HEADERS = {"Authorization": "Bearer dev:alice:ops-agents"}
IT_HEADERS = {"Authorization": "Bearer dev:bob:it-agents"}
must = pilot_helpers.legacy_must
email_message_ids = pilot_helpers.email_message_ids
validate_email_update_outcome = pilot_helpers.validate_email_update_outcome


def main():
    session = requests.Session()
    message_ids = email_message_ids()

    # 1. Create an operational ticket
    r = session.post(
        f"{BASE}/tickets/public/intake/",
        json={
            "request_type_code": "HOURS",
            "service_code": "GEN-INFO",
            "office_code": "MHC-MBA",
            "title": "Email not arriving",
            "description": "I sent a follow-up but the agent never received it.",
            "requester_name": "Email Tester",
            "requester_email": "email-tester@example.com",
            "consent": True,
        },
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 201, "create operational ticket")
    parent_number = r.json()["ticket_number"]
    print(f"     parent={parent_number}")

    # 2. Create IT child from the operational parent
    r = session.post(
        f"{BASE}/tickets/{parent_number}/it-child/",
        headers=OPS_HEADERS,
        json={"summary": "Investigate inbound email routing", "technical_priority": "P2"},
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 201, "create IT child from operational parent")
    child_number = r.json()["child_number"]
    print(f"     child={child_number}")

    # 3. The parent should now be in waiting_it
    r = session.get(
        f"{BASE}/tickets/{parent_number}/",
        headers=OPS_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "fetch parent")
    parent = r.json()
    assert parent["status_code"] == "waiting_it", (
        f"expected waiting_it, got {parent['status_code']}"
    )
    print(f"     parent.status={parent['status_code']} (correct)")

    # 4. The operational agent must NOT see the IT child's body
    r = session.get(
        f"{BASE}/tickets/{child_number}/",
        headers=OPS_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 404, "IT child hidden from operational agent")

    # 5. IT agent can see the child and move it through the IT workflow
    r = session.get(
        f"{BASE}/tickets/{child_number}/",
        headers=IT_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "IT agent can see child")
    child = r.json()
    r = session.post(
        f"{BASE}/tickets/{child_number}/transition/",
        headers=IT_HEADERS,
        json={
            "to_status": "triage",
            "updated_at": child["updated_at"],
            "reason": "smoke",
        },
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "child new -> triage")
    child = r.json()
    r = session.post(
        f"{BASE}/tickets/{child_number}/transition/",
        headers=IT_HEADERS,
        json={
            "to_status": "diagnosing",
            "updated_at": child["updated_at"],
            "reason": "smoke",
        },
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "child triage -> diagnosing")
    child = r.json()
    r = session.post(
        f"{BASE}/tickets/{child_number}/transition/",
        headers=IT_HEADERS,
        json={"to_status": "in_progress", "updated_at": child["updated_at"]},
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "child diagnosing -> in_progress")
    child = r.json()
    r = session.post(
        f"{BASE}/tickets/{child_number}/transition/",
        headers=IT_HEADERS,
        json={"to_status": "validation", "updated_at": child["updated_at"]},
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "child in_progress -> validation")
    child = r.json()
    r = session.post(
        f"{BASE}/tickets/{child_number}/transition/",
        headers=IT_HEADERS,
        json={"to_status": "resolved", "resolution_code": "ROUTING_FIXED",
              "resolution_summary": "Mailbox routing rule added.",
              "updated_at": child["updated_at"]},
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "child validation -> resolved")

    # 6. Parent should now be in_progress (synced)
    r = session.get(
        f"{BASE}/tickets/{parent_number}/",
        headers=OPS_HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "fetch parent after child resolved")
    parent_after = r.json()
    assert parent_after["status_code"] == "in_progress", \
        f"expected in_progress, got {parent_after['status_code']}"
    print(f"     parent.status={parent_after['status_code']} (synced correctly)")

    # 7. Email intake — first message creates a new ticket
    r = session.post(
        f"{BASE}/integrations/email/events/",
        json={
            "from": "Public Visitor <public@example.com>",
            "to": "operations@mhc.local",
            "subject": "Need help with my will",
            "body_text": "Hello, I'd like to know the procedure for registering a will.",
            "message_id": message_ids["initial"],
        },
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 201, "email intake creates new ticket")
    created_outcome = r.json()
    email_ticket_number = created_outcome["ticket_number"]
    print(f"     {created_outcome}")

    # 8. Idempotency: same message_id returns duplicate
    r = session.post(
        f"{BASE}/integrations/email/events/",
        json={
            "from": "Public Visitor <public@example.com>",
            "to": "operations@mhc.local",
            "subject": "Need help with my will",
            "body_text": "Hello, I'd like to know the procedure for registering a will.",
            "message_id": message_ids["initial"],
        },
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "duplicate email is ignored")
    assert r.json()["status"] == "duplicate"
    print("     duplicate detection works")

    # 9. Thread reply — In-Reply-To matches the previous email
    r = session.post(
        f"{BASE}/integrations/email/events/",
        json={
            "from": "Public Visitor <public@example.com>",
            "to": "operations@mhc.local",
            "subject": "Re: Need help with my will",
            "body_text": "Any update? Thanks.",
            "message_id": message_ids["reply"],
            "in_reply_to": message_ids["initial"],
        },
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "threaded reply attaches to existing ticket")
    threaded_outcome = r.json()
    validate_email_update_outcome(
        threaded_outcome,
        expected_ticket_number=email_ticket_number,
        label="threaded reply",
    )
    print(f"     {threaded_outcome}")

    # 10. Subject token — manual reference via [OP-...]
    r = session.post(
        f"{BASE}/integrations/email/events/",
        json={
            "from": "Other Person <other@example.com>",
            "to": "operations@mhc.local",
            "subject": f"Re: [{parent_number}] follow up",
            "body_text": "Just checking in.",
            "message_id": message_ids["subject_reply"],
        },
        timeout=REQUEST_TIMEOUT,
    )
    must(r, 200, "subject-token reply attaches to parent")
    subject_outcome = r.json()
    validate_email_update_outcome(
        subject_outcome,
        expected_ticket_number=parent_number,
        label="subject-token reply",
    )
    print(f"     {subject_outcome}")

    print("\nAll M3 smoke checks passed ✅")


if __name__ == "__main__":
    main()
