"""Backfill authoritative legacy custody history and protect it in PostgreSQL."""

import hashlib
import json
from datetime import UTC

from django.db import migrations
from django.utils import timezone


def _utc_timestamp(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(value, UTC)
    else:
        value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _event_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _chain_payload(*, ticket_id, sequence, event, previous_hash):
    return {
        "ticket_id": str(ticket_id),
        "sequence": sequence,
        "event_type": event["event_type"],
        "occurred_at": _utc_timestamp(event["occurred_at"]),
        "actor_kind": event["actor_kind"],
        "actor_subject": event["actor_subject"],
        "actor_display_name": event["actor_display_name"],
        "source_process": event["source_process"],
        "source_record_type": event["source_record_type"],
        "source_record_id": event["source_record_id"],
        "previous_owner": event["previous_owner"],
        "new_owner": event["new_owner"],
        "previous_queue": event["previous_queue"],
        "new_queue": event["new_queue"],
        "previous_status": event["previous_status"],
        "new_status": event["new_status"],
        "previous_designations": event["previous_designations"],
        "new_designations": event["new_designations"],
        "previous_team_labels": event["previous_team_labels"],
        "new_team_labels": event["new_team_labels"],
        "reason": event["reason"],
        "previous_hash": previous_hash,
    }


def _empty_event(*, event_type, occurred_at, actor, source_process, source_record_type, source_record_id):
    return {
        "event_type": event_type,
        "occurred_at": occurred_at,
        "actor_kind": actor["kind"],
        "actor_subject": actor["subject"],
        "actor_display_name": actor["display_name"],
        "source_process": source_process,
        "source_record_type": source_record_type,
        "source_record_id": source_record_id,
        "previous_owner": None,
        "new_owner": None,
        "previous_queue": None,
        "new_queue": None,
        "previous_status": None,
        "new_status": None,
        "previous_designations": [],
        "new_designations": [],
        "previous_team_labels": [],
        "new_team_labels": [],
        "reason": "",
    }


def backfill_ticket_custody(apps, schema_editor):
    Ticket = apps.get_model("tickets", "Ticket")
    TicketCustodyEvent = apps.get_model("tickets", "TicketCustodyEvent")
    AuditEvent = apps.get_model("audit", "AuditEvent")
    TransitionHistory = apps.get_model("workflow", "TransitionHistory")
    Status = apps.get_model("workflow", "Status")
    User = apps.get_model("identity_access", "User")
    ServiceLocation = apps.get_model("organisations", "ServiceLocation")

    users_by_id = {str(user.pk): user for user in User.objects.all()}
    users_by_subject = {user.keycloak_subject: user for user in User.objects.all()}
    queues_by_id = {str(queue.pk): queue for queue in ServiceLocation.objects.all()}
    statuses_by_id = {str(status.pk): status for status in Status.objects.all()}

    def actor(subject):
        user = users_by_subject.get(subject)
        if user is not None:
            return {
                "kind": "user",
                "subject": user.keycloak_subject,
                "display_name": user.display_name or user.username,
            }
        return {"kind": "system", "subject": subject or "legacy-backfill", "display_name": subject or "Legacy backfill"}

    def owner(value):
        if value in (None, ""):
            return None
        user = users_by_id.get(str(value))
        if user is None:
            return None
        return {
            "id": str(user.pk),
            "subject": user.keycloak_subject,
            "display_name": user.display_name or user.username,
        }

    def queue(value):
        if value in (None, ""):
            return None
        location = queues_by_id.get(str(value))
        if location is None:
            return None
        return {"id": str(location.pk), "label": location.name}

    def status(value):
        if value in (None, ""):
            return None
        workflow_status = statuses_by_id.get(str(value))
        if workflow_status is None:
            return None
        return {"code": workflow_status.code, "label": workflow_status.name}

    for ticket in Ticket.objects.all().iterator():
        if TicketCustodyEvent.objects.filter(ticket_id=ticket.pk).exists():
            continue

        sources = []
        audits = AuditEvent.objects.filter(object_type="ticket", object_id=str(ticket.pk))
        created_audit = audits.filter(action="ticket.created").order_by("occurred_at", "id").first()
        if created_audit is None:
            initial_status = Status.objects.filter(domain=ticket.domain, is_initial=True).first()
            created = _empty_event(
                event_type="created",
                occurred_at=ticket.created_at,
                actor={"kind": "system", "subject": "legacy-backfill", "display_name": "Legacy backfill"},
                source_process="ticket.legacy_backfill",
                source_record_type="",
                source_record_id="",
            )
            created["new_status"] = status(initial_status.pk) if initial_status else None
            sources.append((ticket.created_at, "created", "", created))
        else:
            created = _empty_event(
                event_type="created",
                occurred_at=created_audit.occurred_at,
                actor=actor(created_audit.actor_subject),
                source_process="ticket.create",
                source_record_type="audit_event",
                source_record_id=str(created_audit.pk),
            )
            initial_status = Status.objects.filter(domain=ticket.domain, is_initial=True).first()
            created["new_status"] = status(initial_status.pk) if initial_status else None
            sources.append((created_audit.occurred_at, "created", str(created_audit.pk), created))

        for audit in audits.exclude(pk=created_audit.pk if created_audit else None):
            payload = audit.payload if isinstance(audit.payload, dict) else {}
            before = payload.get("before", {}) if isinstance(payload.get("before", {}), dict) else {}
            after = payload.get("after", {}) if isinstance(payload.get("after", {}), dict) else {}
            if audit.action in {
                "ticket.work_state.changed",
                "ticket.assignment.changed",
            } and ("assignee" in before or "assignee" in after):
                previous_owner = owner(before.get("assignee"))
                new_owner = owner(after.get("assignee"))
                event_type = "assigned" if previous_owner is None and new_owner is not None else "unassigned" if previous_owner is not None and new_owner is None else "reassigned"
                event = _empty_event(
                    event_type=event_type,
                    occurred_at=audit.occurred_at,
                    actor=actor(audit.actor_subject),
                    source_process="ticket.assignment",
                    source_record_type="audit_event",
                    source_record_id=str(audit.pk),
                )
                event["previous_owner"] = previous_owner
                event["new_owner"] = new_owner
                sources.append((audit.occurred_at, "assignment", str(audit.pk), event))
            if "queue" in before or "queue" in after:
                event = _empty_event(
                    event_type="queue_changed",
                    occurred_at=audit.occurred_at,
                    actor=actor(audit.actor_subject),
                    source_process="ticket.routing",
                    source_record_type="audit_event",
                    source_record_id=str(audit.pk),
                )
                event["previous_queue"] = queue(before.get("queue"))
                event["new_queue"] = queue(after.get("queue"))
                sources.append((audit.occurred_at, "queue", str(audit.pk), event))

        transitions = TransitionHistory.objects.filter(ticket_id=ticket.pk).select_related("from_status", "to_status")
        for transition in transitions:
            if transition.to_status.is_initial:
                continue
            event = _empty_event(
                event_type="reopened" if transition.to_status.code == "reopened" else "closed" if transition.to_status.code == "closed" else "status_changed",
                occurred_at=transition.occurred_at,
                actor=actor(transition.actor_subject),
                source_process="ticket.transition",
                source_record_type="workflow_transition",
                source_record_id=str(transition.pk),
            )
            event["previous_status"] = status(transition.from_status_id)
            event["new_status"] = status(transition.to_status_id)
            event["reason"] = transition.reason
            sources.append((transition.occurred_at, "transition", str(transition.pk), event))

        previous_hash = ""
        for sequence, (_occurred_at, _source_type, _source_id, event) in enumerate(sorted(sources, key=lambda source: source[:3]), start=1):
            payload = _chain_payload(ticket_id=ticket.pk, sequence=sequence, event=event, previous_hash=previous_hash)
            event_hash = _event_hash(payload)
            TicketCustodyEvent.objects.create(
                ticket_id=ticket.pk,
                sequence=sequence,
                event_type=event["event_type"],
                occurred_at=event["occurred_at"],
                actor_kind=event["actor_kind"],
                actor_subject=event["actor_subject"],
                actor_display_name=event["actor_display_name"],
                source_process=event["source_process"],
                source_record_type=event["source_record_type"],
                source_record_id=event["source_record_id"],
                previous_owner=event["previous_owner"],
                new_owner=event["new_owner"],
                previous_queue=event["previous_queue"],
                new_queue=event["new_queue"],
                previous_status=event["previous_status"],
                new_status=event["new_status"],
                previous_designations=event["previous_designations"],
                new_designations=event["new_designations"],
                previous_team_labels=event["previous_team_labels"],
                new_team_labels=event["new_team_labels"],
                reason=event["reason"],
                previous_hash=previous_hash,
                event_hash=event_hash,
            )
            previous_hash = event_hash


def create_ticket_custody_protection(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        CREATE OR REPLACE FUNCTION reject_ticket_custody_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND current_setting('mhc.allow_ticket_custody_delete', true) = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'ticket custody events are immutable';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER ticket_custody_immutable
        BEFORE UPDATE OR DELETE ON ticket_custody_event
        FOR EACH ROW EXECUTE FUNCTION reject_ticket_custody_mutation();
        """
    )


def drop_ticket_custody_protection(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        """
        DROP TRIGGER IF EXISTS ticket_custody_immutable ON ticket_custody_event;
        DROP FUNCTION IF EXISTS reject_ticket_custody_mutation();
        """
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0005_ticketcustodyevent"),
        ("audit", "0002_auditevent_payload"),
        ("workflow", "0001_initial"),
        ("identity_access", "0002_user_groups"),
        ("organisations", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_ticket_custody, migrations.RunPython.noop),
        migrations.RunPython(create_ticket_custody_protection, drop_ticket_custody_protection),
    ]
