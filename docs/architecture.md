# Architecture

The platform follows a **modular monolith** pattern: one Django 5.2 LTS backend, one React SPA, and a small fleet of support services (PostgreSQL, RabbitMQ, Redis, MinIO, Keycloak, ClamAV). The structure mirrors the PRD §25 logical diagram.

## High-level diagram

```
   Public / Practitioners                Staff
   Call  Walk-in  Web  Email             Browser
     |      |      |     |                  |
     +------+------ Channel Adapters--------+
                      |
               HTTPS / Webhooks
                      |
        +-------------v-------------+
        |  React Agent/Public UI    |
        +------------+-------------+
                     |
               REST / polling
                     |
   +-----------------v--------------------+
   |  Django Modular Monolith             |
   |  contacts | tickets | conversations  |
   |  workflow | sla | operational | itsm |
   |  files | knowledge | reports | audit |
   |  integrations | administration       |
   +-------+--------------+---------------+
           |              |
   +-------v------+  +----v----------------+
   | PostgreSQL   |  | Celery + RabbitMQ   |
   | source of    |  | async jobs/retries  |
   | truth/outbox |  +---------------------+
   +-------+------+
           |
   +-------v------+       +----------------+
   | MinIO / S3   |       | Keycloak       |
   | attachments  |       | OIDC + MFA     |
   +--------------+       +----------------+
```

## Modules (PRD §25.2)

| Module | Responsibility | Owns |
|---|---|---|
| `identity_access` | User mirror, JWT auth, scope helpers | `User`, `Role`, `UserRole`, `AuditLogin` |
| `organisations` | Regions, offices, service locations | `Region`, `Office`, `ServiceLocation` |
| `contacts` | Contact directory, normalisation, merge | `Contact` |
| `catalogue` | Services, request types, forms | `Service` (others in M2) |
| `tickets` | Ticket aggregate, numbering, links | `Ticket` |
| `workflow` | Statuses, transitions, automation | `WorkflowDefinition` |
| `sla` | Policies, instances, business calendar | `SlaPolicy` |
| `files` | Object storage, scanning, signed URLs | `Attachment` |
| `audit` | Append-only events, structured logging | `AuditEvent` |
| `notifications` | Channels, templates, delivery | `Notification` |
| `integrations` | Channel adapters, webhooks, outbox | `IntegrationEvent` |
| `reporting` | Dashboards, exports | `Dashboard` |
| `administration` | Config items, versioning | `ConfigItem` |
| `health` | Liveness, readiness | n/a |

## Cross-module rules

1. Modules talk to each other through **application services** or **domain events**, never through direct foreign keys outside their own tables.
2. Every state transition goes through a service function wrapped in a DB transaction.
3. An **outbox** event is written in the same transaction as the state change. Workers publish from the outbox (M2).
4. SLA state and integration idempotency live in PostgreSQL — never in queue memory.
5. Cross-domain access (operational ↔ IT) is governed by `Scope.matches()` and tested in the permission suite.

## Reliability patterns (PRD §25.3)

- DB transaction wraps every material transition
- Outbox + idempotent consumer (introduced in M2)
- Retries with exponential backoff and a dead-letter state
- Admin can replay failed jobs safely
- External failure does not roll back authoritative history

## Deployment profile (P0)

- `docker compose` brings the full stack on a single host
- Production uses the same images; topology is documented separately in `docs/deployment.md`
- TLS terminates at the reverse proxy (Nginx or Traefik)
