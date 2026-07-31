"""Backfill authoritative legacy custody history and protect it in PostgreSQL."""
# ruff: noqa: S608 -- dynamic DDL uses a backend-quoted introspected constraint name.

import hashlib
import json
from collections import defaultdict
from datetime import UTC
from uuid import UUID

from django.db import migrations
from django.db.models import Q
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

    context = {}

    def uuid_lookup_key(value):
        try:
            return str(UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            return None

    def valid_uuid_values(values):
        valid = []
        for value in values:
            normalized = uuid_lookup_key(value)
            if normalized is not None:
                valid.append(UUID(normalized))
        return valid

    def ticket_chunks():
        last_pk = None
        while True:
            queryset = Ticket.objects.order_by("pk")
            if last_pk is not None:
                queryset = queryset.filter(pk__gt=last_pk)
            tickets = list(queryset[:200])
            if not tickets:
                return
            last_pk = tickets[-1].pk
            ticket_ids = [ticket.pk for ticket in tickets]
            ticket_id_strings = [str(ticket_id) for ticket_id in ticket_ids]
            audits_by_ticket = defaultdict(list)
            audits = AuditEvent.objects.filter(
                object_type="ticket", object_id__in=ticket_id_strings
            ).order_by("occurred_at", "id")
            for audit in audits:
                audits_by_ticket[audit.object_id].append(audit)
            transitions_by_ticket = defaultdict(list)
            transitions = TransitionHistory.objects.filter(ticket_id__in=ticket_ids).select_related(
                "from_status", "to_status"
            ).order_by("occurred_at", "id")
            for transition in transitions:
                transitions_by_ticket[transition.ticket_id].append(transition)
            actor_subjects = {audit.actor_subject for audit in audits}
            actor_subjects.update(transition.actor_subject for transition in transitions)
            reference_ids = set()
            queue_ids = set()
            for audit in audits:
                payload = audit.payload if isinstance(audit.payload, dict) else {}
                for state in (payload.get("before", {}), payload.get("after", {})):
                    if isinstance(state, dict):
                        if state.get("assignee") not in (None, ""):
                            reference_ids.add(str(state["assignee"]))
                        if state.get("queue") not in (None, ""):
                            queue_ids.add(str(state["queue"]))
            status_ids = {
                str(status_id)
                for transition in transitions
                for status_id in (transition.from_status_id, transition.to_status_id)
                if status_id is not None
            }
            domains = {ticket.domain for ticket in tickets}
            users = User.objects.filter(
                Q(pk__in=valid_uuid_values(reference_ids))
                | Q(keycloak_subject__in=actor_subjects)
            )
            statuses = Status.objects.filter(
                Q(pk__in=status_ids) | Q(domain__in=domains, is_initial=True)
            ).order_by("domain", "order", "id")
            initial_statuses = {}
            statuses_by_id = {}
            for status_row in statuses:
                statuses_by_id[str(status_row.pk)] = status_row
                if status_row.is_initial:
                    initial_statuses.setdefault(status_row.domain, status_row)
            context.clear()
            context.update(
                audits_by_ticket=audits_by_ticket,
                transitions_by_ticket=transitions_by_ticket,
                existing_ticket_ids=set(
                    TicketCustodyEvent.objects.filter(ticket_id__in=ticket_ids).values_list(
                        "ticket_id", flat=True
                    )
                ),
                users_by_id={str(user.pk): user for user in users},
                users_by_subject={user.keycloak_subject: user for user in users},
                queues_by_id={
                    str(queue.pk): queue
                    for queue in ServiceLocation.objects.filter(
                        pk__in=valid_uuid_values(queue_ids)
                    )
                },
                statuses_by_id=statuses_by_id,
                initial_statuses=initial_statuses,
            )
            yield from tickets

    def actor(subject):
        if subject in (None, ""):
            return {
                "kind": "legacy_unknown",
                "subject": "",
                "display_name": "Unknown legacy actor",
            }
        user = context["users_by_subject"].get(subject)
        if user is not None:
            return {
                "kind": "user",
                "subject": user.keycloak_subject,
                "display_name": user.display_name or user.username,
            }
        return {
            "kind": "legacy_unknown",
            "subject": str(subject),
            "display_name": str(subject),
        }

    def owner(value):
        if value in (None, ""):
            return None
        key = uuid_lookup_key(value)
        user = context["users_by_id"].get(key) if key is not None else None
        if user is None:
            stable_id = str(value)
            return {
                "id": stable_id,
                "subject": None,
                "display_name": None,
                "raw_value": stable_id,
                "unresolved": True,
            }
        return {
            "id": str(user.pk),
            "subject": user.keycloak_subject,
            "display_name": user.display_name or user.username,
        }

    def queue(value):
        if value in (None, ""):
            return None
        key = uuid_lookup_key(value)
        location = context["queues_by_id"].get(key) if key is not None else None
        if location is None:
            stable_id = str(value)
            return {
                "id": stable_id,
                "label": None,
                "raw_value": stable_id,
                "unresolved": True,
            }
        return {"id": str(location.pk), "label": location.name}

    def status(value):
        if value in (None, ""):
            return None
        workflow_status = context["statuses_by_id"].get(str(value))
        if workflow_status is None:
            return None
        return {"code": workflow_status.code, "label": workflow_status.name}

    for ticket in ticket_chunks():
        if ticket.pk in context["existing_ticket_ids"]:
            continue

        sources = []
        audits = context["audits_by_ticket"].get(str(ticket.pk), [])
        created_audit = next((audit for audit in audits if audit.action == "ticket.created"), None)
        transitions = context["transitions_by_ticket"].get(ticket.pk, [])
        creation_transition = next(
            (transition for transition in transitions if transition.from_status_id is None),
            None,
        )
        if created_audit is None:
            initial_status = context["initial_statuses"].get(ticket.domain)
            creation_actor = (
                actor(creation_transition.actor_subject)
                if creation_transition is not None
                else {
                    "kind": "system",
                    "subject": "legacy-backfill",
                    "display_name": "Legacy backfill",
                }
            )
            created = _empty_event(
                event_type="created",
                occurred_at=ticket.created_at,
                actor=creation_actor,
                source_process="ticket.legacy_backfill",
                source_record_type=(
                    "workflow_transition" if creation_transition is not None else ""
                ),
                source_record_id=(
                    str(creation_transition.pk) if creation_transition is not None else ""
                ),
            )
            created["new_status"] = (
                status(creation_transition.to_status_id)
                if creation_transition is not None
                else status(initial_status.pk)
                if initial_status
                else None
            )
            sources.append((ticket.created_at, 0, "", created))
        else:
            created = _empty_event(
                event_type="created",
                occurred_at=created_audit.occurred_at,
                actor=actor(created_audit.actor_subject),
                source_process="ticket.create",
                source_record_type=(
                    "workflow_transition" if creation_transition is not None else "audit_event"
                ),
                source_record_id=(
                    str(creation_transition.pk)
                    if creation_transition is not None
                    else str(created_audit.pk)
                ),
            )
            initial_status = context["initial_statuses"].get(ticket.domain)
            created["new_status"] = (
                status(creation_transition.to_status_id)
                if creation_transition is not None
                else status(initial_status.pk)
                if initial_status
                else None
            )
            sources.append((created_audit.occurred_at, 0, str(created_audit.pk), created))

        for audit in audits:
            if created_audit is not None and audit.pk == created_audit.pk:
                continue
            payload = audit.payload if isinstance(audit.payload, dict) else {}
            before = payload.get("before", {}) if isinstance(payload.get("before", {}), dict) else {}
            after = payload.get("after", {}) if isinstance(payload.get("after", {}), dict) else {}
            if audit.action in {
                "ticket.work_state.changed",
                "ticket.assignment.changed",
            } and ("assignee" in before or "assignee" in after):
                previous_assignee = before.get("assignee")
                new_assignee = after.get("assignee")
                previous_owner = owner(previous_assignee)
                new_owner = owner(new_assignee)
                event_type = (
                    "assigned"
                    if previous_assignee in (None, "") and new_assignee not in (None, "")
                    else "unassigned"
                    if previous_assignee not in (None, "") and new_assignee in (None, "")
                    else "reassigned"
                )
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
                sources.append((audit.occurred_at, 2, str(audit.pk), event))
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
                sources.append((audit.occurred_at, 1, str(audit.pk), event))

        for transition in transitions:
            if creation_transition is not None and transition.pk == creation_transition.pk:
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
            sources.append((transition.occurred_at, 3, str(transition.pk), event))

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
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor, "ticket_custody_event"
        )
    constraint_name = next(
        name
        for name, details in constraints.items()
        if details["columns"] == ["ticket_id"]
        and details["foreign_key"] == ("ticket", "id")
    )
    quoted_constraint = schema_editor.quote_name(constraint_name)
    schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    schema_editor.execute(
        f"""
        ALTER TABLE ticket_custody_event DROP CONSTRAINT {quoted_constraint};
        ALTER TABLE ticket_custody_event
        ADD CONSTRAINT {quoted_constraint}
        FOREIGN KEY (ticket_id) REFERENCES ticket(id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED;

        CREATE OR REPLACE FUNCTION reject_ticket_custody_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND NOT EXISTS (
               SELECT 1 FROM ticket WHERE id = OLD.ticket_id
             ) THEN
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
    with schema_editor.connection.cursor() as cursor:
        constraints = schema_editor.connection.introspection.get_constraints(
            cursor, "ticket_custody_event"
        )
    constraint_name = next(
        name
        for name, details in constraints.items()
        if details["columns"] == ["ticket_id"]
        and details["foreign_key"] == ("ticket", "id")
    )
    quoted_constraint = schema_editor.quote_name(constraint_name)
    schema_editor.execute(
        f"""
        DROP TRIGGER IF EXISTS ticket_custody_immutable ON ticket_custody_event;
        DROP FUNCTION IF EXISTS reject_ticket_custody_mutation();
        ALTER TABLE ticket_custody_event DROP CONSTRAINT {quoted_constraint};
        ALTER TABLE ticket_custody_event
        ADD CONSTRAINT {quoted_constraint}
        FOREIGN KEY (ticket_id) REFERENCES ticket(id)
        DEFERRABLE INITIALLY DEFERRED;
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
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS auditevent_ticket_object_lookup_idx "
            "ON auditevent (object_type, object_id) WHERE object_type = 'ticket'",
            "DROP INDEX IF EXISTS auditevent_ticket_object_lookup_idx",
        ),
        migrations.RunPython(backfill_ticket_custody, migrations.RunPython.noop),
        migrations.RunPython(create_ticket_custody_protection, drop_ticket_custody_protection),
    ]
