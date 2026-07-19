# Contributing

Thanks for helping build the MHC Unified e-Ticketing platform. Before contributing, please read the [PRD](docs/prd.md) — it defines the product boundary, priorities, and acceptance criteria for every feature.

## Ground rules

1. **Read the PRD before touching code.** P0 features are mapped in [`docs/traceability.md`](docs/traceability.md). Touch only the requirements you intend to address.
2. **Preserve the Operational/IT separation** in models, authorization, tests and UI. Mixing domains is a release blocker.
3. **Never invent legal services, SLAs, retention periods, or disclosure rules.** These need formal approval.
4. **Never use unofficial WhatsApp automation.** Only the Meta-approved Cloud API.
5. **Never commit secrets, real personal data, or production exports.** Use `.env.example` placeholders.
6. **Server-side authorization first.** A UI guard is decoration; the API must reject.
7. **Audit and observability are part of every feature**, not an afterthought.
8. **Migrations forward and back.** Every schema change ships with a tested rollback.

## Workflow

1. Branch from `main`: `git switch -c feat/<short-name>` or `fix/<short-name>`
2. Keep commits small and Conventional Commit formatted
3. Ensure `make lint type test` pass locally
4. Open a PR with: linked PRD requirement IDs, screenshots for UI, test evidence
5. Wait for code review and security sign-off
6. Squash-merge after CI is green

## Code standards

- **Backend:** Python 3.12, ruff format + ruff check, mypy strict for the `apps/` modules, pytest for tests
- **Frontend:** TypeScript strict, ESLint + Prettier, Vitest for unit, Playwright for E2E
- **API:** OpenAPI 3 generated from DRF, never hand-edited

## Architecture decisions

Material changes require an ADR in `docs/adr/`. Use the template `docs/adr/0000-template.md`.
