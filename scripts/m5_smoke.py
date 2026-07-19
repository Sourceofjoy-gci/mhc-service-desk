"""M5 smoke: WhatsApp mock, knowledge public search, CSAT, automation rules, e-Estate stub."""
import sys
import requests

BASE = "http://localhost:8000/api/v1"


def must(resp, expected, label):
    if resp.status_code != expected:
        print(f"FAIL {label}: HTTP {resp.status_code} — {resp.text[:200]}")
        sys.exit(2)
    print(f"OK   {label}: HTTP {resp.status_code}")


def main():
    # 1. Public knowledge search (no auth)
    r = requests.get(f"{BASE}/public/knowledge/?q=hours")
    must(r, 200, "public knowledge search (no auth)")
    print(f"     {len(r.json().get('results', []))} public articles")

    # 2. Create a knowledge article (auth)
    import uuid
    r = requests.post(
        f"{BASE}/knowledge/articles/",
        headers={"Authorization": "Bearer dev:super:ops-supervisors"},
        json={
            "code": f"OFFICE-HOURS-{uuid.uuid4().hex[:6]}",
            "title": "Office hours",
            "body": "Our offices are open Mon-Fri 08:00-17:00.",
            "audience": "public",
            "status": "published",
            "domain": "operational",
            "language": "en",
            "owner_subject": "dev:super",
        },
    )
    must(r, 201, "create knowledge article (supervisor)")
    print(f"     code={r.json()['code']}")

    # 3. WhatsApp inbound webhook
    r = requests.post(
        f"{BASE}/integrations/whatsapp/webhook/",
        json={
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"display_phone_number": "+26876123456"},
                        "messages": [{
                            "id": "wa-msg-001",
                            "from": "+26878000111",
                            "type": "text",
                            "text": {"body": "What are the office hours?"},
                        }],
                    }
                }]
            }]
        },
    )
    must(r, 201, "WhatsApp inbound webhook")
    print(f"     {r.json()}")

    # 4. WhatsApp idempotency
    r = requests.post(
        f"{BASE}/integrations/whatsapp/webhook/",
        json={
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"display_phone_number": "+26876123456"},
                        "messages": [{
                            "id": "wa-msg-001",
                            "from": "+26878000111",
                            "type": "text",
                            "text": {"body": "What are the office hours?"},
                        }],
                    }
                }]
            }]
        },
    )
    must(r, 200, "WhatsApp duplicate ignored")
    assert r.json()["status"] == "duplicate"

    # 5. WhatsApp templates (mock)
    r = requests.get(f"{BASE}/integrations/whatsapp/templates/")
    must(r, 200, "WhatsApp templates (mock)")
    print(f"     {len(r.json()['templates'])} templates")

    # 6. WhatsApp send (mock)
    r = requests.post(f"{BASE}/integrations/whatsapp/send/", json={"to": "+26878000111", "body": "Reply"})
    must(r, 200, "WhatsApp send (mock)")

    # 7. Automation rule — assign on ticket.created
    r = requests.post(
        f"{BASE}/automation/rules/",
        headers={"Authorization": "Bearer dev:super:ops-supervisors"},
        json={
            "name": f"Auto-assign P1 to alice-{uuid.uuid4().hex[:6]}",
            "trigger": "ticket.created",
            "conditions": {"priority": "P1"},
            "action": "assign_user",
            "action_params": {"username": "alice"},
            "priority": 10,
            "is_active": True,
        },
    )
    must(r, 201, "create automation rule")

    # 8. e-Estate stub — first create a ticket with matter reference
    r = requests.post(
        f"{BASE}/tickets/public/intake/",
        json={
            "request_type_code": "STATUS",
            "service_code": "EST-REG",
            "office_code": "MHC-MBA",
            "title": "Status check for estate",
            "description": "Please confirm status.",
            "requester_name": "Executor",
            "requester_email": "exec@example.com",
            "matter_reference": "EST-2026-000123",
            "consent": True,
        },
    )
    must(r, 201, "create ticket with matter reference")
    matter_ticket = r.json()["ticket_number"]

    r = requests.get(
        f"{BASE}/tickets/{matter_ticket}/validate-matter/",
        headers={"Authorization": "Bearer dev:super:ops-supervisors"},
    )
    must(r, 200, "e-Estate validation (known matter)")
    print(f"     {r.json()}")

    r = requests.get(
        f"{BASE}/tickets/OP-202607-999999/validate-matter/",
        headers={"Authorization": "Bearer dev:super:ops-supervisors"},
    )
    must(r, 404, "e-Estate validation (unknown ticket)")

    print("\nAll M5 smoke checks passed ✅")


if __name__ == "__main__":
    main()
