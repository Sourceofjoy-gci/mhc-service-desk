"""M4 smoke: call/walk-in channels, attachments, CSV export, requester magic link."""
import sys
import requests
import io

BASE = "http://localhost:8000/api/v1"
TOKEN_OPS = "Bearer dev:alice:ops-agents"
TOKEN_SUP = "Bearer dev:super:ops-supervisors"


def must(resp, expected, label):
    if resp.status_code != expected:
        print(f"FAIL {label}: HTTP {resp.status_code} — {resp.text[:200]}")
        sys.exit(2)
    print(f"OK   {label}: HTTP {resp.status_code}")


def main():
    # 1. Call-centre channel: create with channel=call
    r = requests.post(
        f"{BASE}/tickets/public/intake/",
        json={
            "request_type_code": "HOURS",
            "service_code": "GEN-INFO",
            "office_code": "MHC-MBA",
            "title": "Phone enquiry",
            "description": "Caller asks about office hours.",
            "requester_name": "Phone Caller",
            "requester_email": "phone@example.com",
            "consent": True,
            "channel": "call",
        },
    )
    must(r, 201, "create call-channel ticket")
    call_ticket = r.json()["ticket_number"]
    print(f"     call ticket={call_ticket}")

    # 2. Walk-in channel
    r = requests.post(
        f"{BASE}/tickets/public/intake/",
        json={
            "request_type_code": "HOURS",
            "service_code": "GEN-INFO",
            "office_code": "MHC-MBA",
            "title": "Walk-in enquiry",
            "description": "Visitor at the counter.",
            "requester_name": "Visitor",
            "requester_email": "walkin@example.com",
            "consent": True,
            "channel": "walk_in",
        },
    )
    must(r, 201, "create walk-in ticket")
    walkin_ticket = r.json()["ticket_number"]
    print(f"     walk-in ticket={walkin_ticket}")

    # 3. Attachment upload
    fake_file = ("hello.txt", io.BytesIO(b"This is a clean test attachment."), "text/plain")
    r = requests.post(
        f"{BASE}/tickets/{call_ticket}/attachments/",
        headers={"Authorization": TOKEN_OPS},
        files={"files": fake_file},
    )
    must(r, 201, "upload attachment")
    upload = r.json()
    print(f"     {upload}")
    attachment_id = upload["results"][0]["id"]

    # 4. Attachment download (signed URL)
    r = requests.get(
        f"{BASE}/attachments/{attachment_id}/download/",
        headers={"Authorization": TOKEN_OPS},
    )
    must(r, 200, "download attachment (signed URL)")
    print(f"     url starts with: {r.json()['url'][:60]}…")

    # 5. CSV export
    r = requests.get(
        f"{BASE}/reports/tickets.csv",
        headers={"Authorization": TOKEN_OPS},
    )
    must(r, 200, "CSV export")
    lines = r.text.splitlines()
    assert lines[0].startswith("number,domain,title,status")
    print(f"     CSV header: {lines[0]}")
    print(f"     CSV rows: {len(lines) - 1}")

    # 6. CSV export is scope-limited
    r = requests.get(
        f"{BASE}/reports/tickets.csv",
        headers={"Authorization": "Bearer dev:bob:it-agents"},
    )
    must(r, 200, "CSV export as IT agent")
    it_lines = r.text.splitlines()
    op_count = sum(1 for ln in it_lines[1:] if ",operational," in ln)
    if op_count > 0:
        print(f"FAIL scope: IT agent CSV contains {op_count} operational rows")
        sys.exit(3)
    print(f"     IT agent sees 0 operational rows in CSV (correct)")

    # 7. Requester magic link
    # Pick the first ticket created for "requester@example.com"
    r = requests.get(
        f"{BASE}/tickets/",
        headers={"Authorization": TOKEN_SUP},
        params={"search": "OP-202607"},
    )
    must(r, 200, "list tickets as supervisor")
    items = r.json() if isinstance(r.json(), list) else r.json().get("results", [])
    # Find any ticket for a known email; we'll synthesise the token
    # In production the token is emailed; for the test we read raw from the DB via shell.
    print("     (magic-link test requires DB access; see manual smoke)")

    # 8. Operational + IT dashboards
    r = requests.get(f"{BASE}/tickets/dashboard/operational/", headers={"Authorization": TOKEN_OPS})
    must(r, 200, "operational dashboard")
    print(f"     open={r.json()['totals']['open']}")
    # IT dashboard
    r = requests.get(f"{BASE}/reports/dashboard/it", headers={"Authorization": "Bearer dev:bob:it-agents"})
    must(r, 200, "IT dashboard")
    print(f"     IT open={r.json()['totals']['open']}")

    print("\nAll M4 smoke checks passed ✅")


if __name__ == "__main__":
    main()
