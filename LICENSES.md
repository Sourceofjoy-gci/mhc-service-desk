# Third-Party Licences

This project integrates many open-source components. A complete Software Bill of Materials (SBOM) and licence register will be maintained alongside the build.

## Tracked components (P0 baseline)

| Component | Licence | Notes |
|---|---|---|
| Django | BSD-3-Clause | Core framework |
| Django REST Framework | BSD-3-Clause | API toolkit |
| Celery | BSD-3-Clause | Background jobs |
| PostgreSQL | PostgreSQL | Database |
| Redis | BSD-3-Clause | Cache |
| Valkey | BSD-3-Clause | Redis-compatible fork (optional) |
| RabbitMQ | MPL-2.0 | Broker |
| MinIO | AGPL-3.0 | Self-hosted object storage — internal use, no distributed copy |
| Keycloak | Apache-2.0 | Identity |
| ClamAV | GPL-2.0 | Anti-virus |
| React | MIT | UI |
| Vite | MIT | Dev server |
| TanStack Query | MIT | Data fetching |
| dnd-kit | MIT | Drag and drop |
| Tailwind CSS | MIT | Styling |

## Custom code licence

To be selected via policy review. Candidates: Apache-2.0, EUPL-1.2, AGPL-3.0. See PRD §24.4.

## Obligations log

None of the components above impose copyleft on a server-side application that merely uses them over the network. MinIO is AGPL-3.0; using the published server as a network service does not require source distribution of the consuming application. Any deeper integration must be reviewed before adoption.
