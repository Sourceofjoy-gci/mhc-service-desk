# Security Policy

## Reporting a vulnerability

Please report security issues to **security@mhc-ticketing.local** (replace with the real address before production). Do not file public GitHub issues for suspected vulnerabilities.

We aim to acknowledge within 2 business days and provide a remediation plan within 10 business days, in line with the PRD §23 commitments.

## Supported versions

| Version | Supported |
|---|---|
| main (development) | ✅ |
| latest tagged release | ✅ |
| older tags | ❌ |

## Security baseline (P0)

- TLS for all traffic (terminated at reverse proxy in production)
- OIDC authentication via Keycloak with MFA for staff
- Server-side authorization on every endpoint
- Append-only audit events
- Field-level protection for selected identifiers
- File uploads scanned by ClamAV, stored in MinIO with short-lived signed URLs
- CSRF, CORS, CSP, rate limiting, brute-force protection
- Dependency and container scanning in CI
- Secrets outside source code
- Structured logging with secret redaction
- Backups encrypted, restore tested at least quarterly

See [`docs/threat-model.md`](docs/threat-model.md) for the full STRIDE review.
