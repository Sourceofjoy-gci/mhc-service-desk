# Threat Model (P0)

Methodology: **STRIDE** per category, scoped to the modules active in the P0 build. Risk = likelihood × impact, on a 1–5 scale. Mitigations reference PRD FR/NFR IDs and concrete code locations.

## Trust boundaries

1. **Public network → reverse proxy** — TLS terminator, rate limits, WAF
2. **Reverse proxy → Django/React** — internal network, mTLS optional
3. **Agent browser → Django API** — Keycloak OIDC + MFA, short-lived JWT
4. **Requester → public web form** — abuse protection, captcha (P1)
5. **Provider webhook → Django** — signed payloads, replay protection (per channel)
6. **Backend → PostgreSQL** — credentials in secrets, TLS optional in P0 docker network
7. **Backend → MinIO** — service account with least privilege
8. **Backend → RabbitMQ** — service account per worker
9. **Staff → production data** — server-side authorisation, audited break-glass

## STRIDE summary (selected)

| Category | Threat | L | I | Risk | Mitigation | Reference |
|---|---|---|---|---|---|---|
| Spoofing | Forged webhook events | 2 | 4 | M | Signature verification + idempotency keys | FR-005, FR-061 |
| Spoofing | Forged staff identity | 1 | 5 | M | Keycloak OIDC, MFA enforced for staff, short access-token TTL | NFR-010 |
| Tampering | Audit log mutation | 2 | 5 | M | Append-only model, write-only DB role, separate log shipper | FR-096 |
| Repudiation | "I never sent that" | 2 | 3 | M | Signed JWTs, request audit middleware, event payload hash | FR-097 |
| Information disclosure | IT agent reads operational ticket body | 3 | 5 | H | `Scope.matches()` enforces domain; child-ticket sanitisation; tested | FR-027, FR-028 |
| Information disclosure | Requester enumerates ticket numbers | 3 | 3 | M | Magic-link or one-time code; uniform errors; rate limits | FR-073 |
| Information disclosure | Sensitive data leaks into logs | 3 | 4 | H | `JSONFormatter` redacts PII/JWTs/keys; review in CI | FR-100 |
| Denial of service | Email flood creates thousands of tickets | 2 | 4 | M | Idempotency, downstream rate limits, correlation, anomaly alert | FR-005, NFR-019 |
| Denial of service | SLA evaluator blocked by slow DB | 2 | 3 | M | Read replica in P2, indexed SLA tables, short timeouts | FR-054 |
| Elevation of privilege | Frontend hides "admin" button | 4 | 5 | H | Server-side authorisation on every endpoint; permission tests in CI | NFR-010 |

## Out-of-scope (P0)

- Mobile native applications
- Biometric identity verification
- Autonomous AI decisioning
- Full data warehouse / BI replica

## Open risks

- **No penetration test has been performed yet.** Schedule pre-pilot.
- **No DPIA signed.** Required before P1 public rollout.
- **No formal threat model review by an external party.** Target after M3.
