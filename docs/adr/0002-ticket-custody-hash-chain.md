# ADR-0002: Ticket Custody Hash Chain and Transactional Audit Recording

- **Status:** Accepted
- **Date:** 2026-07-30
- **Deciders:** Engineering Lead, Architecture Review

## Context

Ticket ownership, queue, and status changes require an internal, tamper-evident custody history in addition to the platform's canonical audit event and transactional outbox. The history must show the responsible actor and point-in-time ownership snapshots without relying on mutable identity, queue, or workflow records. A custody failure must not leave an audit or outbox row that claims a change occurred without its corresponding custody record.

## Decision

We record ticket custody as an append-only, per-ticket SHA-256 hash chain in the same database transaction as its audit and outbox rows. Each writer locks the ticket row, assigns the next contiguous sequence, snapshots the actor and custody state, and hashes canonical UTF-8 JSON containing the exact prescribed fields plus the preceding hash. Timestamps are normalized to aware UTC before both hashing and persistence. The verifier recomputes every link from sequence one and rejects sequence gaps, previous-hash mismatches, and content-hash mismatches.

The audit/outbox recorder remains the public write boundary. Callers may attach immutable custody inputs; missing source-record metadata is derived from the newly created audit event without mutating caller data. PostgreSQL also rejects every custody update and direct delete. It permits deletion only when the database-owned `ON DELETE CASCADE` runs after removal of the owning ticket row; no session GUC or reusable same-role bypass exists. Ordinary `Ticket.objects` deletion is rejected, while the retention command is the sole reviewed whole-ticket path and uses the base manager only after candidate and hold checks inside its atomic transaction. Migration rollback drops the trigger and restores the non-cascading foreign key but deliberately retains backfilled rows, because they cannot safely be distinguished from post-deployment rows. Equal timestamp sources use explicit creation/assignment/queue/transition precedence and initial-status ties use `(order, id)`.

## Consequences

- Custody records are independently verifiable after database reload and contain stable historical snapshots.
- Audit, outbox, and custody records either commit together or roll back together.
- The canonical JSON fields, six-fractional-digit UTC timestamp representation, and ordering are compatibility constraints for every future writer and migration.
- Per-ticket row locking serializes custody appends for the same ticket and avoids sequence/hash races, at the cost of brief contention on concurrent updates.
- The hash chain makes accidental or unauthorised changes evident; it does not prevent privileged direct database modification, so database access controls and audit retention remain required.
- The cascade exception is constrained to deleting the ticket aggregate; it cannot be enabled by a same-role application session setting.

## Alternatives considered

- **Audit and outbox records only.** They do not provide a dedicated, contiguous custody history or immutable ownership snapshots. Rejected.
- **Database triggers to build the chain.** They obscure domain intent, make canonical serialization harder to test and reuse in the required backfill, and cannot naturally derive the application actor/source context. Rejected.
- **A global chain across all tickets.** It creates unnecessary contention and complicates per-ticket verification. Rejected in favour of independent ticket chains.
- **Signing each record with an external key.** This adds key-management and operational dependencies beyond the current tamper-evidence requirement. Deferred until a non-repudiation requirement exists.
