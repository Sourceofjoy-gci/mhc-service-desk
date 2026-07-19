"""Seed minimal reference data for local development.

Loads offices, services, roles and a small handful of test users. Idempotent.
Run inside the backend container:

    docker compose exec backend python /app/scripts/seed_dev.py
"""
from __future__ import annotations

import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.organisations.models import Office, Region  # noqa: E402
from apps.catalogue.models import RequestType, Service  # noqa: E402
from apps.identity_access.models import Role, User  # noqa: E402
from apps.contacts.models import Contact  # noqa: E402
from apps.sla.seed_sla import seed_sla  # noqa: E402
from apps.tickets.seed_workflow import seed_workflow  # noqa: E402


def ensure_region(code: str, name: str) -> Region:
    obj, _ = Region.objects.get_or_create(code=code, defaults={"name": name})
    return obj


def ensure_office(region: Region, code: str, name: str) -> Office:
    obj, _ = Office.objects.get_or_create(code=code, defaults={"region": region, "name": name})
    return obj


def ensure_service(code: str, name: str, domain: str) -> Service:
    obj, _ = Service.objects.get_or_create(code=code, defaults={"name": name, "domain": domain})
    return obj


def ensure_request_type(service: Service, code: str, name: str, priority: str = "P3") -> RequestType:
    obj, _ = RequestType.objects.get_or_create(
        service=service, code=code,
        defaults={"name": name, "default_priority": priority},
    )
    return obj


def ensure_role(keycloak_role: str, name: str) -> Role:
    obj, _ = Role.objects.get_or_create(
        keycloak_role=keycloak_role, defaults={"name": name, "scopes": []}
    )
    return obj


def ensure_contact(name: str, email: str, phone: str = "") -> Contact:
    obj, _ = Contact.objects.get_or_create(
        email=email, defaults={"full_name": name, "phone_e164": phone}
    )
    return obj


def main():
    mbabane = ensure_region("Hhohho", "Hhohho Region")
    manzini = ensure_region("Manzini", "Manzini Region")
    ensure_office(mbabane, "MHC-MBA", "Master's Office — Mbabane (Main)")
    ensure_office(manzini, "MHC-MAN", "Master's Office — Manzini")

    gen_info = ensure_service("GEN-INFO", "General information and office contact", "operational")
    est_reg = ensure_service("EST-REG", "Estate registration or reference enquiry", "operational")
    will_reg = ensure_service("WIL-REG", "Will registration or safekeeping enquiry", "operational")
    ensure_service("COMP", "Complaint or escalation", "operational")
    it_access = ensure_service("IT-ACCESS", "Identity and access request", "it")
    it_inc = ensure_service("IT-INC", "IT incident report", "it")

    ensure_request_type(gen_info, "HOURS", "Office hours and contact", "P4")
    ensure_request_type(gen_info, "CALLBACK", "Callback request", "P3")
    ensure_request_type(est_reg, "NEW-EST", "New estate enquiry", "P3")
    ensure_request_type(est_reg, "STATUS", "Estate status check", "P3")
    ensure_request_type(will_reg, "SEARCH", "Will search request", "P3")
    ensure_request_type(it_access, "NEW-USER", "New user account", "P3")
    ensure_request_type(it_access, "RESET", "Password reset", "P3")
    ensure_request_type(it_inc, "OUTAGE", "System outage", "P2")
    ensure_request_type(it_inc, "BUG", "Application bug", "P3")

    ensure_role("agent-operational", "Operational agent")
    ensure_role("supervisor-operational", "Operational supervisor")
    ensure_role("agent-it", "IT service desk agent")
    ensure_role("lead-it", "IT service desk lead")
    ensure_role("admin", "System administrator")
    ensure_role("auditor", "Auditor / privacy / records")

    ensure_contact("Test Requester", "requester@example.com", "+26876123456")
    ensure_contact("Walk-in Visitor", "walkin@example.com")

    if not User.objects.filter(username="local-admin").exists():
        User.objects.create_superuser(
            username="local-admin",
            email="local-admin@mhc.local",
            password="change-me-locally",
            keycloak_subject="local-admin",
        )

    seed_workflow()
    seed_sla()
    print("Seed complete.")


if __name__ == "__main__":
    main()
