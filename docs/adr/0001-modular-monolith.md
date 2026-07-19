# ADR-0001: Modular Monolith on Django 5.2 LTS

- **Status:** Accepted
- **Date:** 2026-07-18
- **Deciders:** Engineering Lead, Architecture Review

## Context

The PRD (§24) compares three stack options: a Django + FastAPI split, a NestJS Node backend, and a single Django backend. P0 needs the smallest deployable surface that still satisfies NFR-001 (99.5% availability), NFR-004 (50 agents / 300 sessions), NFR-005 (1M tickets before re-platforming), and the Operational/IT domain separation in §11.5.

## Decision

We adopt **one Django 5.2 LTS modular monolith** with the apps listed in §25.2 of the PRD, plus DRF for the API. Modules communicate through application services and domain events. Cross-module DB writes are prohibited.

## Consequences

- Single deployment artefact for web + worker + beat, simplifying Docker Compose
- One ORM, one migration graph, one auth/audit stack
- Module boundaries are enforced by code review, lint rules, and integration tests
- Future extraction into separate services is possible without API rewrites; the REST surface is the contract
- We avoid the complexity of microservices for a problem that does not need them yet

## Alternatives considered

- **Django + separate FastAPI gateway.** Duplicated validation, auth and observability. Rejected.
- **NestJS + custom admin.** Forces a full re-implementation of Django admin, ORM, and the Python integration ecosystem. Rejected.
- **Frappe Helpdesk as the core.** Open issues for the required Kanban and WhatsApp behaviours at the time of review (PR §24.3). Rejected for P0; remains a future benchmark.
