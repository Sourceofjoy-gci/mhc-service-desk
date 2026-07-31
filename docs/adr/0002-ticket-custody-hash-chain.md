# ADR-0002: Ticket Custody Hash Chain and Transactional Audit Recording

- **Status:** Accepted
- **Date:** 2026-07-30
- **Deciders:** Engineering Lead, Architecture Review

## Context

PRD FR-014 and FR-015 require a chronological timeline that distinguishes
requester-visible communication from staff-only notes. FR-023 requires a
reopened ticket to preserve its earlier closure history; FR-054 requires SLA
state to survive worker or queue restarts; FR-096 and FR-097 require
append-only audit evidence for material actions; and FR-098 requires controlled
retention, legal hold, and disposal. The PRD also requires Operational and IT
records to remain scope-separated (FR-026 and FR-027).

Canonical audit and outbox records alone do not provide a contiguous,
per-ticket custody history with immutable ownership, queue, status, actor, and
system-process snapshots. A custody-write failure must not leave audit/outbox
evidence that claims a change happened without the matching custody record.

## Decision

The platform records custody as an append-only, per-ticket SHA-256 hash chain
in the same database transaction as the corresponding audit and outbox rows.
Each writer locks the ticket row, assigns the next contiguous sequence, stores
the actor and custody snapshots, and hashes canonical UTF-8 JSON containing the
prescribed fields and prior hash. Timestamps are normalized to aware UTC before
hashing and persistence. The verifier recomputes from sequence one and rejects
sequence gaps, previous-hash mismatches, and content-hash mismatches.

The audit/outbox recorder is the custody write boundary. Callers supply typed,
immutable custody inputs; when source-record metadata is absent it is derived
from the newly created audit event without changing the caller input. Current
Plan 1 writers cover ticket creation, workflow transitions, the approved
IT-child flow, and the first SLA escalation threshold crossing. The SLA
evaluator is a named system actor and records only the first threshold-crossing
event; SLA state remains persisted in PostgreSQL. Existing assignment and queue
writers are not made custody-integrated by this ADR: Plan 2 will introduce the
guarded assignment service and must use this boundary for assignment,
reassignment, unassignment, and queue events.

PostgreSQL rejects direct custody updates and deletes. The `0007` migration is
state-only: Django's collector sees `DO_NOTHING` for the custody foreign key,
while the physical database foreign key remains `ON DELETE CASCADE`. The
`0008` migration makes that cascade fail closed unless the approved retention
command has enabled `mhc.allow_ticket_custody_delete` with `SET LOCAL` inside
the same atomic disposal transaction and the parent ticket is absent as part
of that deletion. The conjunction prevents the setting from authorising a
selective custody-row delete. Normal ORM deletion and direct SQL ticket
deletion therefore cannot use the physical cascade. The setting is not exposed
as an application helper and expires at transaction end. The retention path
remains responsible for legal-hold and candidate checks before enabling an
authorised whole-ticket disposal.

Legacy backfill stores unresolved owner and queue references inside the hashed
custody JSON using their original stable value, a null label/identity, and an
explicit unresolved marker. Activity never recovers those custody facts from a
mutable audit payload; linked audit identifiers are used to suppress duplicate
legacy fields only. A non-empty historical actor subject that no longer
resolves to a user is recorded as `legacy_unknown`, rather than being
misrepresented as a system process. The authoritative null-origin workflow
transition supplies a ticket's creation status when present, even if the
configured initial status changed later. Only that consumed transition is
suppressed from separate timeline output.

The `0006` rollback removes the PostgreSQL trigger and restores the original
non-cascading foreign key while deliberately retaining rows backfilled by that
migration, because they cannot safely be separated from rows created after
deployment. Rolling back `0005` removes the custody table itself. Retention,
disposal certificates, schedule approval, and backup expiry remain governed by
the PRD records policy; this ledger is evidence, not an exemption from it.

## Consequences

- Custody records can be independently verified after reload and retain stable
  historical display values even when users, queues, or statuses later change.
- Ticket mutation, audit, outbox, and custody records commit or roll back
  together.
- Canonical fields, six-fractional-digit UTC timestamps, and ordering are
  compatibility constraints for writers, backfill, and verifiers.
- Equal-time custody activity retains ledger `sequence`; paired queue and owner
  events cannot be reordered by random event UUIDs.
- Per-ticket locking serializes appends and avoids sequence/hash races at the
  cost of short contention on concurrent writes to the same ticket.
- The chain makes accidental or unauthorised changes evident; privileged
  database modification remains an access-control and retention concern.
- The authorised activity endpoint remains the read boundary: scope and
  Restricted-ticket rules apply before custody data is returned, and auditors
  are read-only.

## Alternatives considered

- **Audit and outbox records only.** They do not provide a dedicated,
  contiguous custody history or immutable ownership/routing snapshots.
  Rejected.
- **Database triggers to build the chain.** They obscure domain intent, make
  canonical serialization harder to test and reuse for backfill, and cannot
  naturally derive application actor/source context. Rejected.
- **A global chain across all tickets.** It adds unnecessary contention and
  complicates per-ticket verification. Rejected in favour of independent ticket
  chains.
- **Signing each record with an external key.** This adds key-management and
  operational dependencies beyond the current tamper-evidence requirement.
  Deferred until a non-repudiation requirement exists.
