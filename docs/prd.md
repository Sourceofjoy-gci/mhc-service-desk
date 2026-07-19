# Product Requirements Document
## MHC Unified Kanban e-Ticketing and Service Desk

**Organisation:** Judiciary of Eswatini — Office of the Master of the High Court  
**Document version:** 2.0 (merged and optimised)  
**Status:** Build-ready baseline for discovery, engineering breakdown and pilot delivery  
**Date:** 18 July 2026  
**Audience:** Product owner, Master’s Office management, Judiciary ICT, business analysts, coding agents, software engineers, QA, information security, data protection, records management and infrastructure teams  
**Delivery posture:** Open-source oriented, self-hosted or sovereign-hosted, modular, API-first, mobile-responsive, accessible and auditable

---

# Part I — Review and Merge Decisions

## 1. Documents Reviewed

This version combines and improves the following two drafts:

1. **MHC Kanban e-Ticketing and Service Desk PRD** — the more comprehensive draft, with detailed service management, privacy, audit, ITSM, integration, testing and coding-agent requirements.
2. **Master of the High Court — Unified Kanban e-Ticketing & Case Query System PRD** — the more concise draft, with clear diagrams, numbered requirements, a two-workspace model, a focused MVP and a practical implementation roadmap.

The merge does not simply append the two documents. It resolves contradictions, removes duplicated or premature components, strengthens unsafe requirements, and places all functionality into explicit delivery priorities.

## 2. Comparative Analysis

| Area | Stronger material in the first PRD | Stronger material in the second PRD | Final merged decision |
|---|---|---|---|
| Product boundary | Explicitly states that ticketing is not formal filing, legal advice or a replacement for e-Estate | Concisely describes a query system linked to an authoritative case reference | Retain the strict boundary and make it a release-blocking requirement |
| Operational and IT separation | Uses a linked IT child ticket with minimum necessary data | Clearly explains two workspaces and provides a useful architecture diagram | Use one platform with two service domains; never expose the whole business ticket to IT |
| Requirements traceability | Detailed, but not consistently numbered | Clear FR/NFR numbering and MVP definition of done | Use numbered requirements with P0/P1/P2 priorities and acceptance tests |
| Service catalogue | More comprehensive and configurable | Easier to understand, but hard-codes functions that may require mandate validation | Seed only confirmed services; keep other functions disabled until approved by the Master’s Office |
| Security, privacy and records | Strong data minimisation, audit, retention, attachment and export controls | Provides a concise RBAC matrix | Combine both; add secure requester verification and remove unsafe public lookup by ID number |
| Kanban design | Strong WIP, aging, blocked-work and flow metrics | Clear board mechanics and alternate list/calendar views | Keep boards and queues; make WIP controls configurable; defer advanced flow analytics until after pilot |
| Channel handling | Strong idempotency, attachment scanning, official WhatsApp and message-thread requirements | Clear channel table and practical call/walk-in flows | Manual call/walk-in, web and email in P0; official WhatsApp in P1 after account approval |
| Architecture | Strong modular-monolith principle, but too many services in the initial stack | Single TypeScript backend is simpler, but adds custom admin and duplicates mature Django capabilities | Use one Django modular monolith plus React; no separate FastAPI or microservices in P0 |
| Background jobs | Durable RabbitMQ/Celery design | Redis/BullMQ is simple for Node | Use Celery and RabbitMQ; persist SLA state in PostgreSQL so queues are not the source of truth |
| Reporting | Detailed operational, IT and Kanban reporting | Metabase accelerator and focused executive KPIs | Build essential in-app dashboards first; add Metabase against a reporting schema when needed |
| Open-source accelerators | Evaluates many mature tools | Explicitly proposes optional Chatwoot | Keep provider adapters; Chatwoot may be piloted for channels, but is not the ticket system of record |
| Delivery | Comprehensive but too broad for a fast MVP | Shorter phased roadmap | Adopt a strict vertical-slice MVP and defer full ITIL, AI, CTI, data warehouse and HA automation |

## 3. Major Corrections Made

### 3.1 Service scope is configurable, not assumed

The public Judiciary description confirms deceased-estate administration, protection of interests such as creditors, debtors, legatees and minors, and registration and safekeeping of wills. The platform must therefore be able to support additional functions, but it shall not hard-code Trusts, Curatorship, Tutorship, Insolvency or Company Liquidation as active services until the responsible authority confirms the exact institutional mandate, ownership and routing rules.

### 3.2 A business ticket is not “moved” into IT

Moving a ticket between workspaces can disclose sensitive estate, beneficiary, identity or financial information. The merged design keeps the operational ticket with its operational owner and creates a sanitised, linked IT child ticket. Only specifically selected technical context is copied.

### 3.3 Requester access uses verified links or one-time codes

A public lookup that accepts a ticket number plus an identity number or telephone number creates enumeration and privacy risks. The final design uses an expiring magic link or one-time code sent to the registered channel. Stronger verification can be configured for sensitive services.

### 3.4 The MVP uses one application backend

The first draft proposed Django plus a separate FastAPI integration gateway; the second proposed NestJS plus custom administration. Both can work, but neither is the fastest combined approach. The selected stack uses Django 5.2 LTS and Django REST Framework for the ticket engine, APIs, webhooks and administration. This avoids duplicated authentication, validation, deployment and observability work.

### 3.5 The platform starts as a modular monolith

Microservices, Kubernetes, OpenSearch, a data warehouse, full configuration-item discovery and autonomous AI are not required to prove the service. The design preserves module and event boundaries so these can be introduced only when scale or risk justifies them.

### 3.6 SLA deadlines are stored in PostgreSQL

RabbitMQ and Celery execute notifications and integration work, but they shall not be the authoritative store for SLA timers. A periodic evaluator reads persisted SLA instances, preventing lost timers during queue restarts or deployments.

### 3.7 Omnichannel is phased

Manual call-centre capture, walk-in capture, public forms and email deliver the essential service quickly. WhatsApp Business Cloud API is added after Meta account, template, consent and webhook arrangements are approved. CTI, call recordings and queue kiosks are later integrations.

### 3.8 Open-source products are accelerators, not constraints

Chatwoot is a mature, self-hosted omnichannel platform and may accelerate WhatsApp or shared-inbox work, but making it a second system of record creates synchronisation and permission risks. Frappe Helpdesk is also capable and open source, but its native Kanban and WhatsApp capabilities were still represented as open feature work during the July 2026 review. The default architecture therefore remains a focused custom core with optional adapters and proof-of-concept gates.

## 4. Final Architecture and Scope Decision

The recommended product is a **single self-hosted application with two strongly separated service domains**:

- **Operational Service Desk:** public and professional queries about authorised services of the Master’s Office.
- **IT Service Desk:** incidents and requests concerning the ticketing platform, e-Estate, identity, integrations, devices, scanning, connectivity and cybersecurity.

The fastest safe path is:

1. Build one vertical operational-ticket flow end to end.
2. Add the separate IT domain and linked child-ticket flow.
3. Add call, walk-in, web and email intake.
4. Pilot with selected teams and real SLA calendars.
5. Add official WhatsApp, requester portal, knowledge and configurable automation.
6. Add advanced ITSM, CTI, integrations and analytics only after the core is stable.

---

# Part II — Merged Product Requirements Document

## 5. Executive Summary

The Office of the Master of the High Court requires a unified e-Ticketing platform to receive, classify, assign, track, communicate, resolve and report on incoming queries and service challenges received through a call centre, email, official WhatsApp Business channels, walk-in visits, public web forms and internal referrals.

Every supported interaction shall become or update a traceable ticket with:

- A unique human-readable reference number;
- an identified service domain and request type;
- an accountable queue, team and owner;
- a controlled workflow status;
- priority and service-level targets;
- requester-visible communications and separate internal notes;
- attachments and linked authoritative references;
- related or child tickets; and
- a complete audit history.

The product shall use Kanban boards to make work and bottlenecks visible, while also providing queue/list views for high-volume triage. It shall support work-in-progress limits, aging indicators, saved filters, escalation and service dashboards.

The Operational and IT service desks share infrastructure but have separate catalogues, workflows, boards, queues, permissions, SLA policies, notifications, knowledge content and reports. IT staff do not receive blanket access to operational ticket content. A technical dependency creates a sanitised IT child ticket while the operational ticket remains accountable to the public requester.

The solution is a service-management and enquiry-tracking platform. It shall not replace e-Estate or another authoritative case-management system, constitute formal filing of a legal document, make legal determinations or provide legal advice.

## 6. Product Vision

> Give every authorised Master’s Office enquiry a secure and visible path from receipt to an accountable response, while enabling staff and ICT teams to manage workload, service commitments and recurring problems from one open, extensible platform.

## 7. Product Goals

1. Capture at least 95% of interactions received through supported channels within three months of each channel’s rollout.
2. Automatically acknowledge valid requests and provide a ticket reference.
3. Route tickets to the correct service domain, office, queue and team.
4. Make backlog, ownership, aging, waiting reasons and SLA risk visible.
5. Keep operational and technical work separate without losing cross-team accountability.
6. Give requesters secure status visibility and a reliable reply path.
7. Preserve a complete communication and audit record.
8. reduce duplicated requests and repeated follow-up contacts.
9. provide management information by service, office, channel, priority, waiting reason and team.
10. support self-hosted or sovereign-hosted deployment without per-agent SaaS licensing.
11. allow administrators to change catalogues, forms, workflows, SLA policies and templates without changing source code.
12. progressively integrate with e-Estate, identity, email, WhatsApp, telephony and monitoring systems.

## 8. Success Measures

The values below are starting targets and must be baselined and approved during the pilot.

| Outcome | Measure | Initial target after stabilisation |
|---|---|---|
| Channel capture | Supported-channel contacts represented by a ticket | At least 95% |
| Ownership | Open tickets with an accountable queue and owner or explicit unassigned escalation | At least 98% |
| First response | Eligible tickets meeting first-response target | At least 90% |
| Update discipline | Tickets receiving the promised next update | At least 90% |
| Duplicate control | New tickets later marked duplicate | Below 5% |
| Reopen quality | Closed tickets reopened within policy | Below 10%, measured by category |
| Separation | Cross-domain access-control test pass rate | 100% |
| Aging | Open tickets older than approved threshold | Reducing month over month |
| Self-service | Eligible requests resolved using approved knowledge without an agent ticket | Baseline in P1, improve thereafter |
| Satisfaction | Completed eligible CSAT responses | Baseline first; target approved after three months |
| IT restoration | P1/P2 IT incidents with recorded restoration time | At least 95% |

Performance measures shall not be used as individual productivity rankings without workload, complexity, waiting time, quality and reassignment context.

## 9. Product Boundary

### 9.1 The platform shall

- Track enquiries, complaints, administrative service requests, follow-ups and technical issues;
- preserve communication and accountability;
- reference authorised estate or matter records;
- provide approved procedural guidance;
- coordinate operational and IT action;
- report service performance.

### 9.2 The platform shall not

- Replace e-Estate or another legal case-management system;
- create, adjudicate or close an estate matter;
- treat an uploaded attachment as a formal filing unless an authorised integration explicitly completes such a transaction;
- determine the validity of a will;
- approve a legal, financial or beneficiary outcome;
- provide automated legal advice;
- expose full case files to service-desk users;
- store call recordings by default;
- use unofficial WhatsApp Web automation.

A banner and acknowledgement notice shall clearly distinguish a service ticket from formal filing.

## 10. Delivery Scope and Priorities

### 10.1 P0 — Pilot MVP

P0 is the smallest safe, operationally useful release:

- Staff authentication and MFA through Keycloak;
- users, teams, offices, roles and permissions;
- separate Operational and IT service domains;
- configurable service catalogue and request types;
- ticket creation from agent call form, walk-in form, internal form, public web form and inbound email;
- unique numbering and acknowledgements;
- contact matching and duplicate suggestions;
- queues, list view and Kanban board;
- assignment, transfer, watchers and internal notes;
- requester-visible email replies;
- configurable statuses and transition rules;
- priority, SLA calendar, warning and breach escalation;
- linked operational-to-IT child tickets;
- attachments in object storage with malware scanning;
- secure requester status and reply through an expiring link or one-time code;
- search using PostgreSQL;
- essential operational and IT dashboards;
- append-only application audit events;
- Docker-based deployment, backup and restore;
- automated unit, integration and end-to-end tests;
- administrator and agent documentation.

### 10.2 P1 — Omnichannel and Self-Service

- Official WhatsApp Business Cloud API;
- requester portal and My Tickets;
- public and internal knowledge bases;
- response templates and multilingual public content;
- configurable trigger-condition-action automation UI;
- CSAT;
- approval steps;
- e-Estate reference validation and deep links;
- scheduled exports;
- optional SMS notifications;
- optional Chatwoot channel-gateway proof of concept;
- improved workload and flow reporting.

### 10.3 P2 — Optimisation and Advanced ITSM

- CTI/PBX screen pop and call metadata;
- major-incident coordination;
- problem and change management;
- configuration-item and asset relationships;
- monitoring alert correlation;
- advanced Kanban flow analytics;
- reporting replica and Metabase;
- high-availability deployment profile;
- automated disaster-recovery procedures;
- approved AI assistance for summarisation, classification and draft responses;
- additional languages or native-mobile requirements where justified.

### 10.4 Explicitly Out of Scope for P0

- Full estate or court case management;
- electronic legal filing;
- payment processing;
- biometric identity verification;
- native mobile applications;
- full IT asset discovery;
- autonomous AI decisions;
- complex visual workflow designer;
- Kafka, microservice orchestration, service mesh, OpenSearch or a data warehouse;
- Kubernetes as a mandatory pilot dependency.

## 11. Service-Domain Model

### 11.1 Shared Platform Capabilities

- Identity and session management;
- contact directory;
- ticket and conversation engine;
- workflow and SLA engine;
- file service;
- search;
- notifications;
- audit;
- reporting;
- administration;
- integration adapters;
- observability and backups.

### 11.2 Operational Service Desk

Handles authorised business and administrative queries relating to the Master’s Office. Access is scoped by service, office, queue, role and confidentiality classification.

### 11.3 IT Service Desk

Handles incidents, access requests, application defects, equipment, scanning, connectivity, integrations and cybersecurity. IT uses separate numbering, queues, workflows, SLAs and reports.

### 11.4 Cross-Domain Child-Ticket Rule

1. An operational agent identifies a technical dependency.
2. The system opens a linked IT child-ticket form.
3. Only selected technical fields and specifically authorised attachments may be copied.
4. The parent remains owned by the operational team.
5. The parent may enter **Waiting for IT** while its operational SLA/OLA rules remain explicit.
6. IT works in the child ticket and records technical notes there.
7. Only a safe status summary is synchronised to the parent.
8. IT resolution does not automatically close the operational ticket.
9. The operational owner verifies the outcome and communicates with the requester.
10. Both tickets audit the relationship and all synchronised changes.

### 11.5 Misclassification Rule

A newly created ticket may be reclassified before sensitive work begins. Once messages, files or restricted data are present, an authorised supervisor shall create a sanitised replacement ticket in the correct domain and retain an audited relationship rather than transferring the full record.

## 12. Service Catalogue

The catalogue shall be fully configurable. The following is the proposed initial seed.

### 12.1 Confirmed or Core Operational Services

- General information, office contact and hours;
- appointment or callback request;
- service complaint or escalation;
- deceased-estate reporting requirements;
- estate registration or reference enquiry;
- appointment of executor or estate representative;
- Letters of Executorship or Authority status;
- inventory, creditor, account, objection, beneficiary or distribution enquiry;
- document requirement or missing-document query;
- will registration, safekeeping, search or authorised access enquiry;
- protection-of-interest enquiry concerning a creditor, debtor, legatee, beneficiary or minor;
- records, certified-copy, fee or receipt enquiry;
- Guardian’s Fund enquiry where confirmed and assigned by the responsible authority.

### 12.2 Optional Operational Services — Disabled Until Mandate Approval

- Insolvent estates and liquidation;
- company liquidation;
- trusts;
- curatorship;
- tutorship;
- guardianship;
- other statutory functions.

Enabling any optional service requires an approved owner, request types, forms, confidentiality rules, SLA policy, queue and escalation path.

### 12.3 IT Service Catalogue

- Identity and access: password, locked account, new account, role change and MFA;
- e-Ticketing: outage, defect, routing, notification, report and performance problem;
- e-Estate: access, workflow, document, data and integration issue;
- end-user computing: workstation, printer, scanner and approved software;
- network and communication: internet, LAN, Wi-Fi, VPN, email and telephony;
- digitisation: scan quality, OCR, storage, print and batch processing;
- cybersecurity: phishing, malware, unauthorised access, data leakage, lost device and vulnerability;
- service request: equipment, software, configuration, report and integration;
- recurring issue or root-cause investigation, activated in P2.

## 13. Users and Personas

- **External requester:** public user, executor, beneficiary, creditor, practitioner, representative or other authorised stakeholder.
- **Call-centre agent:** searches existing contacts and tickets, captures calls, uses scripts and routes work.
- **Walk-in/front-office agent:** provides assisted intake, verifies information where required and issues acknowledgement.
- **Operational agent:** handles tickets in an authorised service or queue.
- **Subject-matter officer:** provides specialist findings, approvals or quality review.
- **Operational supervisor:** manages workload, reassignment, SLA risk, escalation and quality.
- **IT service-desk agent:** handles incidents and service requests.
- **IT specialist/security responder:** handles restricted technical work.
- **Knowledge author/approver:** creates and governs guidance.
- **Reporting analyst:** uses governed, permission-aware data.
- **Auditor, privacy or records officer:** reviews authorised evidence, access and retention actions.
- **System administrator:** manages platform configuration without automatic access to business content.
- **Vendor user:** receives time-bound access only to explicitly shared technical tickets.

## 14. Roles and Access Principles

### 14.1 Principles

- Deny by default;
- server-side enforcement on every query and endpoint;
- least privilege;
- role plus office, service, queue and confidentiality scope;
- MFA for all staff and privileged users;
- no blanket business-data access for IT or system administrators;
- restricted security, complaint, fraud and privacy categories;
- separate export permission;
- automatic expiry of vendor and temporary access;
- full audit of restricted views, downloads and exports.

### 14.2 Starting Permission Matrix

| Role | Operational domain | IT domain | Configuration | Reports |
|---|---|---|---|---|
| Call/walk-in agent | Create; view limited identification and tickets created or authorised | Create own IT request | None | Personal activity only |
| Operational agent | Assigned and authorised queue tickets | Create linked or personal IT ticket | None | Own/team as authorised |
| Operational supervisor | Full authorised service/office access; reassign and escalate | Safe linked-child status only | Catalogue/SLA items delegated to role | Service/office dashboard |
| IT agent | No operational content except approved technical extract | Assigned IT queues | None | IT dashboard |
| IT lead | No operational content by default | Full authorised IT access | IT catalogue and workflow | IT reports |
| Security responder | Only explicitly assigned security cases | Restricted security tickets | Security configuration delegated | Restricted reports |
| System administrator | Metadata needed for support; content reveal only through controlled break-glass | Platform administration | System settings and integrations | System health |
| Executive | Read-only aggregated operational information | Read-only aggregated IT information | None | Executive dashboards |
| Auditor/privacy/records | Read-only evidence within mandate | Read-only evidence within mandate | Audit/retention evidence | Approved audit exports |
| External requester | Own verified tickets and public messages only | Own verified IT tickets only | None | None |

## 15. Ticket Classification

Every ticket shall contain:

- Ticket number and internal UUID;
- service domain;
- work type;
- request type, category and subcategory;
- office and service location;
- source channel and source account;
- requester and authorised participants;
- matter/estate reference where applicable;
- title and description;
- impact, urgency and priority;
- confidentiality classification;
- queue, team and assignee;
- status and waiting reason;
- SLA policy, target dates and health;
- blocked reason and dependencies;
- tags;
- linked tickets;
- resolution code and summary;
- created, updated, resolved, closed and reopened timestamps.

### 15.1 Operational Work Types

- Enquiry;
- administrative service request;
- complaint;
- information or document request;
- appointment/callback;
- escalation;
- follow-up.

### 15.2 IT Work Types

- Incident;
- service request;
- access request;
- security incident;
- task;
- problem and change, introduced in P2.

## 16. Priority Model

Priority is calculated from impact and urgency, with service-specific rules. A supervisor may override it only with a reason.

| Impact | Urgency | Priority |
|---|---|---|
| High | High | P1 Critical |
| High | Medium | P2 High |
| High | Low | P3 Normal |
| Medium | High | P2 High |
| Medium | Medium | P3 Normal |
| Medium | Low | P4 Low |
| Low | High | P3 Normal |
| Low | Medium | P4 Low |
| Low | Low | P4 Low |

Security, privacy, widespread outage or imminent serious harm may trigger restricted elevation rules.

## 17. SLA and OLA Model

### 17.1 Rules

- Automated acknowledgement is not the same as a meaningful first response.
- Operational targets measure acknowledgement, first meaningful response, next update and enquiry action; they do not promise completion of an underlying legal process.
- SLA calendars include business hours, weekends, public holidays and timezone.
- **Waiting for Requester** may pause selected targets.
- Waiting for an internal team or IT shall remain visible and may use an OLA.
- Every pause, extension or due-date override requires a reason and audit event.
- Alerts occur before and at breach.
- SLA state is persisted in PostgreSQL and evaluated by a periodic worker.

### 17.2 Proposed Operational Targets

| Priority | Automated acknowledgement | First meaningful response | Update interval | Target enquiry action |
|---|---:|---:|---:|---:|
| P1 | Immediate | 30 minutes | Every 2 hours | Same business day or approved escalation plan |
| P2 | Immediate | 2 business hours | Daily | 2 business days |
| P3 | Immediate | 1 business day | Every 2 business days | 5 business days |
| P4 | Immediate | 2 business days | Every 5 business days | 10 business days |

### 17.3 Proposed IT Targets

| Priority | Automated acknowledgement | Human response | Restore/workaround | Resolution target |
|---|---:|---:|---:|---:|
| P1 | Immediate | 15 minutes | 2 hours | 4 hours or major-incident plan |
| P2 | Immediate | 30 minutes | 4 hours | 1 business day |
| P3 | Immediate | 4 business hours | 1 business day | 3 business days |
| P4 | Immediate | 1 business day | Scheduled | 5 business days |

### 17.4 Escalation Thresholds

- 75% consumed: notify owner;
- 90% consumed: notify owner and supervisor;
- breach: flag ticket and notify supervisor;
- P1 breach or repeated breach: notify service owner;
- unassigned P1 beyond five minutes: immediate queue escalation;
- no meaningful update by the promised interval: aging alert.

Targets remain draft until approved during service design.

## 18. Kanban and Queue Design

### 18.1 Operational Workflow

`New → Triage → Assigned → In Progress → Waiting for Requester / Waiting for Internal Unit / Waiting for IT → Escalated or Quality Review → Resolved → Closed`

System outcomes also include Duplicate, Merged, Cancelled, Rejected, Spam and Reopened.

### 18.2 IT Workflow

`New → Triage → Assigned → Diagnosing → In Progress → Waiting for User / Vendor / Change → Validation → Resolved → Closed`

### 18.3 Board Requirements

- Card face shows number, title, priority, owner, age, SLA state, office, channel and key tags;
- confidential fields are masked;
- drag-and-drop invokes a valid workflow transition;
- mandatory fields, tasks and approvals cannot be bypassed;
- keyboard and menu alternatives exist;
- saved filters and swimlanes support priority, office, service, assignee and parent incident;
- WIP limits are configurable per column/team;
- a soft limit warns all users; a hard limit may be enabled and overridden only by a supervisor with reason;
- blocked and aging work is visible without opening a card;
- list view is the primary high-volume triage surface;
- board data uses pagination or virtualisation rather than loading all historical tickets;
- P0 may use optimistic updates plus short polling; real-time presence or WebSockets are added only when justified.

### 18.4 Initial Saved Queues

Operational:

- New and unassigned;
- My tickets;
- Team tickets;
- P1/P2;
- SLA at risk;
- breached;
- waiting for requester;
- waiting internally;
- waiting for IT;
- complaints;
- reopened;
- no update;
- quality review.

IT:

- New incidents;
- P1/P2;
- security;
- access requests;
- e-Ticketing;
- e-Estate;
- email/WhatsApp integrations;
- scanner/OCR;
- network;
- waiting for vendor;
- breached;
- my tickets.

## 19. Channel Design

### 19.1 Common Intake Pipeline

Every inbound event shall:

1. Validate its source and channel account.
2. normalise contact data.
3. apply idempotency using provider event/message identifiers.
4. match an existing conversation using authoritative thread identifiers before fuzzy rules.
5. update the correct ticket or create a new one.
6. classify and route using controlled rules.
7. scan and quarantine attachments.
8. issue an acknowledgement.
9. store integration metadata separately from the public message.
10. log processing success or failure and support safe replay.

### 19.2 Call Centre — P0

- Fast search by ticket number, name, phone, email and authorised matter reference;
- recent-ticket and duplicate warning;
- one-screen ticket capture;
- privacy and identity-verification script;
- call reason, relationship, verification result, notes and disposition;
- callback date/time;
- ticket number for verbal confirmation;
- optional email/SMS acknowledgement;
- manual operation independent of PBX integration.

### 19.3 Walk-In — P0

- Assisted intake with office, counter, agent and visit time;
- identity captured only when required;
- relationship to matter;
- optional scan of supporting information;
- clear label that an attachment supports an enquiry and is not necessarily a formal filing;
- printable or electronic acknowledgement with ticket reference and QR code;
- resolved-at-counter, referred or ticket-opened outcome.

### 19.4 Email — P0

- Dedicated operational and IT mailboxes;
- modern authentication where available;
- preserve Message-ID, In-Reply-To and References headers;
- include a ticket token in outbound subjects;
- thread replies to the existing ticket;
- detect bounces, loops and automated replies;
- sanitise HTML and block remote tracking content;
- malware-scan attachments;
- send replies from the platform;
- record delivery failures and retry safely;
- configure SPF, DKIM and DMARC for outbound domains.

### 19.5 Public Web Form — P0

- Separate operational and IT entry points;
- request-type driven fields and conditional help;
- low-bandwidth responsive design;
- accessible validation;
- attachment upload;
- consent/privacy notice;
- abuse protection and rate limiting;
- secure acknowledgement and status link.

### 19.6 WhatsApp Business — P1

- Official WhatsApp Business Cloud API or approved official provider only;
- verified webhooks, signatures, event IDs and replay protection;
- text and approved media types;
- contact matching with safeguards;
- sent, delivered, read and failed statuses where available;
- current Meta template and customer-conversation rules;
- consent, purpose and opt-out recording;
- privacy notice;
- no sensitive content in notification previews;
- adapter interface so the provider can be replaced;
- optional Chatwoot gateway evaluated through a controlled proof of concept.

### 19.7 Requester Status and Reply — P0/P1

P0 provides a secure, expiring link or one-time code sent to the registered channel. P1 adds a full My Tickets portal. Ticket numbers alone shall never authorise access.

### 19.8 Automated Monitoring — P2

IT monitoring integrations may create or update incidents using authenticated, idempotent events. Alert correlation must prevent a single outage from creating excessive independent tickets.

## 20. Functional Requirements

Priority meanings:

- **P0:** required for pilot acceptance;
- **P1:** required for omnichannel and controlled public rollout;
- **P2:** optimisation or advanced capability.

### 20.1 Ticket Intake, Identity and Contacts

| ID | Priority | Requirement |
|---|---|---|
| FR-001 | P0 | Generate a unique, non-reusable, human-readable ticket number, using separate Operational and IT prefixes. |
| FR-002 | P0 | Create a ticket from call-centre, walk-in, internal, public-web and inbound-email intake. |
| FR-003 | P0 | Acknowledge every valid new request through an approved available channel and record the acknowledgement. |
| FR-004 | P0 | Match inbound email using message headers and the ticket token before creating a new ticket. |
| FR-005 | P0 | Use provider event/message IDs and an idempotency key to prevent duplicated channel events. |
| FR-006 | P0 | Normalise telephone numbers and email addresses while preserving their original supplied values. |
| FR-007 | P0 | Suggest possible duplicate contacts and tickets without automatically merging sensitive records. |
| FR-008 | P0 | Permit an authorised agent to create a ticket on behalf of a requester and record the originating agent and channel. |
| FR-009 | P0 | Support anonymous general enquiries where policy permits, while requiring verified access for status or sensitive communication. |
| FR-010 | P0 | Maintain contact communication preferences, language, consent/opt-out state and verification history. |
| FR-011 | P0 | Allow authorised contact merge only after preview, with a reason and audit event. |
| FR-012 | P1 | Allow verified requester participants to be added or removed under category-specific rules. |

### 20.2 Ticket Record and Collaboration

| ID | Priority | Requirement |
|---|---|---|
| FR-013 | P0 | Store all core classification, ownership, priority, SLA, confidentiality, channel and reference fields defined in section 15. |
| FR-014 | P0 | Present a chronological timeline of requester messages, staff replies, internal notes, system events and field changes. |
| FR-015 | P0 | Keep internal notes technically and visually distinct from requester-visible replies. |
| FR-016 | P0 | Require an explicit requester-visible action before any internal note can be sent externally. |
| FR-017 | P0 | Support attachments linked to a ticket or message, with permission checks on every view and download. |
| FR-018 | P0 | Support watchers, mentions and team collaboration without making watchers requester participants. |
| FR-019 | P0 | Support parent, child, related, duplicate, blocked-by, blocks, merged-from and operational-to-IT relationships. |
| FR-020 | P0 | Permit controlled ticket merge with a surviving-ticket preview, preserved history and merge reason. |
| FR-021 | P1 | Permit controlled split of selected messages or work into a new related ticket. |
| FR-022 | P0 | Require a resolution code and concise resolution summary before a ticket can become Resolved. |
| FR-023 | P0 | Support reopen within an approved period and preserve the original SLA and closure history. |
| FR-024 | P1 | Support configurable tasks/checklists with owners and due dates. |
| FR-025 | P1 | Support approval records with approver, decision, time, reason and version of the submitted information. |

### 20.3 Workspaces, Routing and Assignment

| ID | Priority | Requirement |
|---|---|---|
| FR-026 | P0 | Enforce separate Operational and IT catalogues, queues, boards, workflows, permissions, SLA policies and reports. |
| FR-027 | P0 | Prevent IT users from viewing the operational parent’s message body or attachments unless a specific controlled disclosure is approved. |
| FR-028 | P0 | Create a linked IT child ticket using an explicit field-selection screen and no attachment copying by default. |
| FR-029 | P0 | Synchronise only safe child status summaries to the operational parent. |
| FR-030 | P0 | Prevent closure of an IT child from automatically closing the operational parent. |
| FR-031 | P0 | Route a ticket by domain, source account, request type, office and category using ordered rules. |
| FR-032 | P0 | Route an unmatched operational ticket to a named triage queue rather than silently guessing. |
| FR-033 | P0 | Support manual assignment and reassignment with reason. |
| FR-034 | P1 | Support round-robin, workload-aware and skill/category-based assignment. |
| FR-035 | P0 | Escalate tickets that remain unassigned beyond a configurable threshold. |
| FR-036 | P0 | Support out-of-office delegation and prevent new assignment to inactive users. |
| FR-037 | P0 | Show an editing or reply-presence warning when another agent is actively working on the ticket; a lightweight advisory lock is acceptable. |

### 20.4 Workflow, Kanban and Queues

| ID | Priority | Requirement |
|---|---|---|
| FR-038 | P0 | Store configurable statuses, valid transitions, transition permissions and required fields. |
| FR-039 | P0 | Render authorised tickets in queue/list and Kanban views using the same underlying data and filters. |
| FR-040 | P0 | Move a card only through a valid workflow transition and return a clear error when a transition is blocked. |
| FR-041 | P0 | Provide keyboard and menu alternatives to drag-and-drop. |
| FR-042 | P0 | Display number, title, priority, assignee, age, SLA state, office and channel on a card, subject to masking. |
| FR-043 | P0 | Support saved filters and queues by owner, team, status, priority, SLA, office, category and waiting reason. |
| FR-044 | P0 | Configure WIP limits by board/column and provide accessible warnings. |
| FR-045 | P1 | Support a hard WIP limit that only an authorised supervisor can override with a reason. |
| FR-046 | P0 | Display blocked status, blocked reason and ticket age without opening the ticket. |
| FR-047 | P0 | Use server pagination or virtualisation for large queues and boards. |
| FR-048 | P1 | Add calendar view for callbacks, appointments, due dates and planned changes. |
| FR-049 | P1 | Add configurable swimlanes by priority, office, service, assignee or parent incident. |

### 20.5 SLA, Priority and Escalation

| ID | Priority | Requirement |
|---|---|---|
| FR-050 | P0 | Calculate priority from impact and urgency using an administrator-managed matrix. |
| FR-051 | P0 | Permit restricted priority override only with a reason and audit event. |
| FR-052 | P0 | Apply an SLA policy by service domain, request type, priority, office and business calendar. |
| FR-053 | P0 | Calculate first-response, next-update and enquiry-action or resolution targets in business time. |
| FR-054 | P0 | Persist every SLA instance, due time, pause, resume, completion and breach state in PostgreSQL. |
| FR-055 | P0 | Pause only the targets allowed by policy and only for an approved waiting reason. |
| FR-056 | P0 | Resume requester-paused targets when a valid requester reply arrives. |
| FR-057 | P0 | Warn at configurable consumption thresholds and escalate on breach. |
| FR-058 | P0 | Display SLA state on ticket detail, card and queue. |
| FR-059 | P0 | Record breach reason and service owner review outcome. |
| FR-060 | P1 | Support internal OLA targets for operational units, IT teams and vendors. |

### 20.6 Communications and Notifications

| ID | Priority | Requirement |
|---|---|---|
| FR-061 | P0 | Send requester email from approved service addresses and store the final rendered message and delivery result. |
| FR-062 | P0 | Notify staff in-app and/or by email for assignment, mention, requester reply, SLA warning and escalation according to preferences. |
| FR-063 | P0 | Use approved templates with safe variables and record the template version used. |
| FR-064 | P0 | Exclude sensitive content from email subjects, notification previews and general alerts. |
| FR-065 | P0 | Suppress duplicate notifications and retry transient delivery failures without duplicating the timeline. |
| FR-066 | P0 | Record bounces and delivery failures and place failed outbound communication in an exception queue. |
| FR-067 | P1 | Send and receive WhatsApp messages through the official API adapter and record delivery status. |
| FR-068 | P1 | Support optional SMS notification through a replaceable provider adapter. |
| FR-069 | P1 | Support quiet hours for non-urgent messages and immediate override for approved P1 notifications. |
| FR-070 | P1 | Send CSAT after eligible closure and prevent multiple surveys for the same resolution event. |

### 20.7 Requester Self-Service and Knowledge

| ID | Priority | Requirement |
|---|---|---|
| FR-071 | P0 | Give a requester an expiring status/reply link or one-time code sent to the verified registered channel. |
| FR-072 | P0 | Show only safe public status, requester-visible messages and authorised attachments. |
| FR-073 | P0 | Prevent ticket-number enumeration through uniform errors, rate limits and abuse controls. |
| FR-074 | P1 | Provide a My Tickets portal with secure session management and channel verification. |
| FR-075 | P1 | Allow a requester to reply, provide requested information, upload attachments and request reopening. |
| FR-076 | P1 | Provide public, internal-operational, internal-IT and restricted knowledge audiences. |
| FR-077 | P1 | Support article draft, review, approval, publication, review-due, retirement and version history. |
| FR-078 | P1 | Suggest approved knowledge during intake and response and record article usage. |
| FR-079 | P1 | Prevent an expired, unapproved or restricted article from being inserted into a public response. |
| FR-080 | P1 | Support English and siSwati public content through translation keys and versioned templates. |

### 20.8 Search, Reporting and Administration

| ID | Priority | Requirement |
|---|---|---|
| FR-081 | P0 | Provide permission-aware search by ticket number, title, requester, authorised contact fields, matter reference, category, owner and date. |
| FR-082 | P0 | Prevent restricted data leakage through result counts, auto-complete, snippets or exports. |
| FR-083 | P0 | Provide operational and IT dashboards with separate filters and drill-down permissions. |
| FR-084 | P0 | Report ticket volume, backlog age, first response, target compliance, waiting reason, reopened count and workload. |
| FR-085 | P0 | Report IT incidents by service, priority, response, restore and resolution time. |
| FR-086 | P1 | Report throughput, lead time, cycle time, WIP, blocked time and cumulative flow. |
| FR-087 | P0 | Export authorised CSV with a visible classification label and an audit event. |
| FR-088 | P1 | Schedule governed CSV/XLSX/PDF reports and record delivery. |
| FR-089 | P0 | Allow administrators to manage offices, teams, users, roles, catalogue, request types, fields, statuses, workflows, SLA calendars, templates and channel accounts. |
| FR-090 | P0 | Version and audit configuration changes and allow export of non-secret configuration. |
| FR-091 | P1 | Provide a simple trigger-condition-action rule editor with validation, activation state, execution history and safe simulation. |
| FR-092 | P0 | Provide integration-health and failed-job administration without revealing credentials. |

### 20.9 Files, Audit and Retention

| ID | Priority | Requirement |
|---|---|---|
| FR-093 | P0 | Store file content in S3-compatible object storage rather than database blobs. |
| FR-094 | P0 | Validate type and size, calculate checksum, scan for malware and quarantine unsafe files. |
| FR-095 | P0 | Use short-lived signed download URLs and record restricted downloads. |
| FR-096 | P0 | Make audit events append-only through normal application access and export them to protected central logs. |
| FR-097 | P0 | Audit authentication, restricted views, sensitive-field reveal, assignment, transitions, messages, downloads, exports, permissions and configuration. |
| FR-098 | P1 | Support retention classes, legal hold, disposal review and a disposal certificate. |
| FR-099 | P1 | Support authorised correction or redaction while preserving a controlled history. |
| FR-100 | P0 | Prevent secrets, access tokens and unnecessary message bodies from being written to logs. |

## 21. Knowledge Management

Knowledge is introduced in P1 because correct governance matters more than rapid publication.

### 21.1 Content Types

- Public administrative guidance;
- internal procedure;
- call-centre script;
- troubleshooting guide;
- known error;
- standard response;
- escalation guide;
- request-type instructions;
- service notice.

### 21.2 Governance

Each article shall have an owner, audience, service/domain, source authority, language, effective date, review date, approver, version and status. Public content requires authorised human approval. The system shall display the last-reviewed date and identify high-volume request topics that lack approved knowledge.

## 22. Reporting and Analytics

### 22.1 Operational Dashboard

- New, open and unassigned tickets;
- P1/P2 tickets;
- SLA at risk and breached;
- first response and enquiry-action time, including percentile views;
- backlog age;
- waiting reason;
- channel and request-type mix;
- complaints and reopen rate;
- requester satisfaction when available;
- workload by queue/team, not simplistic ticket-count ranking.

### 22.2 IT Dashboard

- Incidents by affected service;
- P1/P2 incident count;
- mean time to acknowledge, restore and resolve;
- recurring incidents;
- e-Ticketing, e-Estate, identity and channel failures;
- security incidents under restricted access;
- vendor wait time;
- failed or delayed integration events.

### 22.3 Metric Governance

- A data dictionary defines each metric, clock, exclusion and timezone.
- Historical assignment and category values are preserved for accurate trend reporting.
- Broad management reports use de-identified or aggregated data where practical.
- Drill-down and exports use the same permission rules as ticket access.

## 23. Security, Privacy, Records and Audit

The product shall be reviewed against applicable Eswatini data-protection, cybercrime, Judiciary security and records-management obligations. The PRD defines technical controls; formal legal and policy approval remains necessary.

### 23.1 Privacy by Design

- Record the purpose and data owner for each request type;
- collect only information needed for service delivery;
- avoid duplicating full estate files;
- display privacy notices at intake;
- record consent where consent is relied on;
- restrict sensitive financial, minor, beneficiary, security and identity data;
- mask national identifiers and account information;
- assess processors and cross-border transfers;
- approve a retention schedule before production;
- complete a data-protection impact assessment before public rollout.

### 23.2 Application Security

- TLS for all traffic;
- encryption at rest for databases, backups and object storage;
- field-level protection for selected identifiers and secrets;
- OIDC authentication through Keycloak;
- MFA for staff;
- short-lived sessions and refresh controls;
- server-side authorization;
- secure cookies and CSRF protection;
- strict input validation and output encoding;
- content security policy and secure headers;
- rate limiting and brute-force protection;
- webhook signature verification and replay prevention;
- dependency, container and source scanning;
- malware scanning and file allow-lists;
- secret management outside source code;
- environment separation;
- incident-response and vulnerability-disclosure processes.

### 23.3 Break-Glass Access

Where production support requires access to restricted content:

1. The user requests break-glass access and states the reason and ticket.
2. An authorised approver grants time-bound access or an emergency policy applies.
3. A prominent session banner is displayed.
4. Every viewed ticket and downloaded file is audited.
5. Access expires automatically and is reviewed.

### 23.4 Records and Retention

Retention is configured by record class for ticket metadata, messages, attachments, call metadata, audit, security logs, knowledge and configuration. The product supports legal hold, scheduled review, approved disposal and an immutable disposal event. Backups do not become an uncontrolled permanent archive; backup expiry follows the approved schedule.

## 24. Recommended Open-Source Technology Stack

Versions shall be pinned to a currently supported security patch at implementation time rather than hard-coded forever.

### 24.1 Selected Core

| Layer | Selected technology | Reason for selection |
|---|---|---|
| Agent/public frontend | React, TypeScript and Vite | One modern UI, strong component ecosystem and no need for Next.js server-side rendering in the pilot |
| UI and accessibility | Tailwind CSS, accessible headless components, React Hook Form and Zod | Rapid consistent forms with typed validation |
| Kanban | dnd-kit | Accessible drag-and-drop with keyboard support |
| Data fetching | TanStack Query | Caching, optimistic updates and controlled polling |
| Core backend | Django 5.2 LTS and Django REST Framework | Mature ORM, migrations, security, administration, ecosystem and long-term support |
| Background processing | Celery and RabbitMQ | Durable jobs for email, notifications, scanning and integrations |
| Cache/locks | Valkey, optional in P0 | Open Redis-compatible cache for sessions, rate limits or advisory locks; not a system of record |
| Database | PostgreSQL 18, current supported patch | Transactional source of truth, JSONB, full-text search, trigram matching and strong indexing |
| Object storage | MinIO or approved S3-compatible storage | Self-hosted, replaceable file storage |
| Malware scanning | ClamAV or approved equivalent | Open-source attachment scanning |
| Identity | Keycloak 26.x, current supported patch | OIDC, MFA, federation, groups and central identity administration |
| Reverse proxy | Nginx or Traefik | TLS termination, routing and rate controls |
| Observability | OpenTelemetry, Prometheus, Grafana, Loki and Alertmanager | Open metrics, traces, logs and alerts |
| Packaging | Docker and Docker Compose | Reproducible development and pilot deployment |
| CI/CD | GitHub Actions, GitLab CI or Woodpecker, selected by hosting policy | Open workflow and self-hosting options |
| Testing | pytest, Django test framework, Playwright, k6 and OWASP ZAP | Unit, integration, end-to-end, load and dynamic security testing |
| Documentation | MkDocs Material, OpenAPI and Mermaid | Maintainable technical and user documentation |

### 24.2 Deliberately Removed from P0

- Separate FastAPI service: duplicates validation, auth and deployment;
- NestJS backend: capable, but would require rebuilding administration and Python-based integration/security utilities;
- OpenSearch or Meilisearch: PostgreSQL search is adequate initially;
- Kubernetes/K3s: Docker Compose is sufficient for pilot; a high-availability profile may use K3s later;
- Metabase: optional after metric definitions and a reporting schema are stable;
- WebSockets: short polling and optimistic updates are sufficient for P0; add SSE/WebSocket only for proven needs;
- visual automation canvas: implement governed configuration first, then add a safe editor;
- full microservices: module boundaries and outbox events provide a future extraction path.

### 24.3 Optional Accelerators

**Chatwoot:** may be tested as an official WhatsApp/email channel gateway because it is open source, self-hosted and omnichannel. It shall not become the authoritative ticket record, and the proof of concept must demonstrate permission mapping, reliable idempotent synchronisation, message ownership, export and failure recovery.

**Frappe Helpdesk:** may be evaluated for a smaller independent helpdesk, but is not the default core. Adopting it for this project would require a governed fork or extensions for the required Kanban, domain isolation, child-ticket privacy model and current channel needs, together with acceptance of AGPL obligations.

### 24.4 Licensing

- Maintain a software bill of materials and third-party licence register.
- Do not incorporate copyleft components into custom distributed code without legal review of obligations.
- Select the licence for custom government-funded code through policy review; Apache-2.0, EUPL-1.2 or AGPL-3.0 are candidates with different reuse and copyleft effects.
- Provider-specific channel credentials and templates remain configuration, not source code.

## 25. Application Architecture

### 25.1 Logical Diagram

```text
Public / Practitioners                       Staff
Call  Walk-in  Web  Email  WhatsApp          Browser
  |      |      |     |       |                 |
  +------+------+-Channel Adapters-------------+
                         |
                  HTTPS / Webhooks
                         |
             +--------------------------+
             | React Agent/Public UI    |
             +------------+-------------+
                          |
                    REST / polling
                          |
       +------------------v--------------------+
       | Django Modular Monolith               |
       | contacts | tickets | conversations    |
       | workflow | SLA | operational | ITSM   |
       | files | knowledge | reports | audit   |
       | integrations | administration         |
       +-------+--------------+----------------+
               |              |
       +-------v------+  +----v----------------+
       | PostgreSQL   |  | Celery + RabbitMQ   |
       | source of    |  | async jobs/retries  |
       | truth/outbox |  +---------------------+
       +-------+------+
               |
       +-------v------+       +----------------+
       | MinIO/S3     |       | Keycloak       |
       | attachments  |       | OIDC/MFA       |
       +--------------+       +----------------+
```

### 25.2 Module Boundaries

- `identity_access`
- `organisations_offices`
- `contacts`
- `catalogue`
- `tickets`
- `conversations`
- `workflow`
- `sla`
- `assignment`
- `operational_service`
- `it_service`
- `knowledge`
- `files`
- `notifications`
- `reporting`
- `audit`
- `integrations`
- `administration`

Modules interact through application services, stable interfaces and domain events. Direct cross-module database writes are prohibited.

### 25.3 Reliability Patterns

- Database transaction wraps every material ticket transition.
- An outbox record is committed in the same transaction as a business event.
- Workers publish notifications or integration calls from the outbox.
- Consumers are idempotent.
- Retries use exponential backoff and a dead-letter state.
- Administrators can replay failed jobs safely.
- External failure does not roll back the authoritative ticket history.

## 26. Data Model

### 26.1 Core Entities

- ServiceDomain;
- Region/Office/ServiceLocation;
- Team/Queue;
- User/Role/PolicyScope;
- Contact/Organisation/ContactMethod/Verification;
- ChannelAccount/Conversation/Message;
- Ticket/RequestType/Category/CustomFieldValue;
- Status/Workflow/Transition;
- Assignment/Participant/Watcher;
- TicketLink/Task/Checklist/Approval;
- Attachment/FileScan;
- SlaPolicy/SlaInstance/BusinessCalendar;
- Escalation;
- Service/AffectedSystem;
- IncidentExtension and later Problem/Change extensions;
- KnowledgeArticle/KnowledgeVersion;
- ResponseTemplate;
- AutomationRule/AutomationExecution;
- Notification/DeliveryAttempt;
- CsatResponse;
- AuditEvent;
- IntegrationEvent/OutboxEvent;
- RetentionClass/LegalHold/DisposalEvent;
- ExportJob.

### 26.2 Data Rules

- Use UUIDs internally and human ticket numbers externally.
- Enforce unique external message IDs per channel account.
- Store sanitised HTML and plain text for messages.
- Keep raw provider payloads only where necessary, encrypted, restricted and time-limited.
- Store files outside PostgreSQL.
- Maintain current ticket state plus immutable history events.
- Use database constraints for valid domain, ownership and relationship invariants.
- Index number, domain, queue, assignee, status, priority, SLA state, requester contact hashes, references and search vectors.
- Use migrations with automated forward and rollback/restore testing.

## 27. API and Integration Contracts

### 27.1 API Standards

- REST/JSON;
- OpenAPI 3;
- `/api/v1` versioning;
- consistent problem-details error format;
- cursor or page pagination;
- filtering and sorting;
- idempotency key on create endpoints used by integrations;
- optimistic concurrency using version/ETag;
- correlation IDs;
- service-account authentication;
- rate limits;
- audited bulk and export actions.

### 27.2 Indicative Endpoints

```text
/api/v1/tickets
/api/v1/tickets/{ticketNumber}
/api/v1/tickets/{ticketNumber}/messages
/api/v1/tickets/{ticketNumber}/notes
/api/v1/tickets/{ticketNumber}/attachments
/api/v1/tickets/{ticketNumber}/transitions
/api/v1/tickets/{ticketNumber}/links
/api/v1/tickets/{ticketNumber}/tasks
/api/v1/tickets/{ticketNumber}/approvals
/api/v1/contacts
/api/v1/catalogue
/api/v1/queues
/api/v1/boards
/api/v1/knowledge
/api/v1/reports
/api/v1/integrations/email/events
/api/v1/integrations/whatsapp/webhook
/api/v1/integrations/telephony/events
/api/v1/integrations/monitoring/events
/api/v1/webhooks
```

### 27.3 e-Estate Integration

P1 begins with:

- validate or search an authorised estate/matter reference;
- display a minimal safe summary;
- deep-link authorised staff to the source record;
- store the external identifier and lookup result time;
- avoid copying case documents or sensitive fields.

Later integrations may create support tickets from e-Estate or show open ticket summaries there, subject to source-of-truth and authorization rules.

## 28. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-001 | **Availability:** target 99.5% monthly availability for production, excluding approved maintenance, with visible degraded-channel status. |
| NFR-002 | **Performance:** ordinary filtered queue, board and ticket-detail requests shall meet p95 under 2 seconds at the approved pilot load, excluding large file transfer. |
| NFR-003 | **Interaction:** a successful Kanban transition shall provide optimistic feedback immediately and server confirmation normally within 2 seconds. |
| NFR-004 | **Pilot capacity:** support at least 50 actively working agents and 300 concurrent authenticated sessions without redesign. |
| NFR-005 | **Data volume:** support at least one million tickets through correct indexing, archiving and pagination before requiring a change of core database technology. |
| NFR-006 | **Webhook response:** acknowledge a valid provider webhook within 2 seconds after basic verification and process it asynchronously. |
| NFR-007 | **Low bandwidth:** public forms and secure status pages shall remain usable on an ordinary mobile connection and avoid unnecessary large assets. |
| NFR-008 | **Accessibility:** target WCAG 2.2 AA for public and staff functions, including keyboard-accessible status changes and no colour-only meaning. |
| NFR-009 | **Localisation:** all public strings and templates shall be externalised; English is initial and siSwati is P1-ready. |
| NFR-010 | **Security:** no critical or high unresolved vulnerability at production release; every endpoint shall enforce server-side authorization. |
| NFR-011 | **Privacy:** restricted fields shall be masked by default and access shall be purpose- and role-limited. |
| NFR-012 | **Auditability:** material business, security, configuration, export and access events shall be attributable, timestamped and tamper-evident. |
| NFR-013 | **Backup:** encrypted automated backups with monitored completion and retention. |
| NFR-014 | **Recovery:** initial RPO of 15 minutes and RTO of 4 hours for the production target, subject to approved infrastructure; pilot may use a formally accepted lower tier. |
| NFR-015 | **Restore testing:** database, object and configuration restore shall be tested before go-live and at least quarterly. |
| NFR-016 | **Portability:** the application shall run from documented containers against standard PostgreSQL, RabbitMQ and S3-compatible storage. |
| NFR-017 | **Maintainability:** typed Python and TypeScript, automated formatting, linting, tests, migrations and architecture decision records. |
| NFR-018 | **Critical-logic coverage:** at least 80% automated coverage for workflow, SLA, permissions, channel idempotency and ticket-link logic; line coverage alone is not acceptance. |
| NFR-019 | **Observability:** structured logs, metrics, traces/correlation IDs and alerts for errors, queue depth, channel failure, SLA evaluator failure, authentication anomalies and backup failure. |
| NFR-020 | **Upgradeability:** dependencies shall be pinned, scanned and updated through a documented process; configuration and data migrations shall be tested on production-like copies. |
| NFR-021 | **Graceful degradation:** email or WhatsApp failure shall queue/retry messages without preventing staff from continuing ticket work. |
| NFR-022 | **Browser support:** current supported versions of major desktop browsers and modern Android mobile browsers; exact matrix approved during discovery. |
| NFR-023 | **Time:** store timestamps in UTC, display the approved Eswatini timezone and use versioned business calendars for SLA calculations. |
| NFR-024 | **Open export:** authorised data and configuration shall be exportable in documented, non-proprietary formats. |

## 29. User Experience Requirements

### 29.1 Agent Navigation

- Home;
- My Work;
- Operational Service Desk;
- IT Service Desk, when authorised;
- Queues;
- Kanban;
- Call Centre;
- Walk-In;
- Knowledge, when enabled;
- Reports;
- Administration, when authorised.

### 29.2 Ticket Workspace

The workspace shall provide:

- Header with number, title, status, priority, SLA and owner;
- clear domain/confidentiality label;
- requester/contact panel with masked values;
- conversation timeline;
- separate reply and internal-note composers;
- details and custom fields;
- related tickets and IT child status;
- tasks/approvals when enabled;
- attachments;
- e-Estate link when authorised;
- next action and blocked reason;
- concise audit/activity view.

### 29.3 Call-Centre Screen

The call screen optimises for fast keyboard operation and includes caller search, recent tickets, guided fields, approved scripts, knowledge suggestions when enabled, disposition, callback and reference confirmation.

### 29.4 Walk-In Screen

The walk-in screen uses a large, guided form with office/counter pre-populated, minimal identity fields, matter search, document-capture label, outcome and print acknowledgement.

### 29.5 Public Experience

Public content uses clear non-legal language. Internal statuses are mapped to understandable public statuses such as Received, Being Reviewed, Assigned, Being Worked On, Waiting for Your Information, Referred Internally, Response Provided, Completed and Closed.

## 30. Automation Model

### 30.1 P0

P0 uses administrator-managed rule records and seed rules. A rule contains:

- trigger;
- optional conditions;
- actions;
- priority/order;
- active date range;
- owner;
- version;
- execution log.

Rules are validated and executed by the application; arbitrary code execution is prohibited.

### 30.2 P1 Rule Editor

P1 provides a guided trigger-condition-action editor rather than a general programming canvas. It shall show a natural-language preview, detect conflicts, support dry-run simulation on sample tickets and require approval for high-impact actions.

### 30.3 Initial Rules

1. Acknowledge a new valid ticket.
2. Route dedicated IT sources to IT triage.
3. Route unmatched operational items to Operational Triage.
4. Warn about a probable duplicate.
5. Notify at SLA 75% and 90%.
6. Escalate unassigned P1 tickets.
7. Resume requester-paused SLA when a requester replies.
8. Require resolution code and summary.
9. Auto-close after the approved confirmation period unless reopened.
10. Create a CSAT invitation for eligible P1 tickets.
11. Notify an operational parent of a safe IT restore/resolution status.
12. Quarantine prohibited attachments.
13. Flag no-update and aging tickets.
14. Prevent duplicate channel event processing.

## 31. Testing and Quality Strategy

### 31.1 Unit Tests

At minimum:

- ticket numbering;
- impact/urgency priority;
- business-calendar calculations;
- SLA pause, resume, completion and breach;
- workflow transition rules;
- permission scopes;
- field masking;
- duplicate suggestions;
- email threading;
- webhook idempotency;
- IT child sanitisation;
- retention eligibility;
- notification suppression.

### 31.2 Integration Tests

- Keycloak OIDC and role mapping;
- inbound and outbound email;
- attachment upload, object storage and malware scan;
- Celery/RabbitMQ processing and retry;
- requester OTP/magic link;
- audit export;
- backup and restore;
- WhatsApp webhook and delivery events in P1;
- e-Estate lookup in P1.

### 31.3 End-to-End Journeys

1. Call agent finds a requester, creates an operational ticket, acknowledges it, assigns it and resolves it.
2. Walk-in officer creates a ticket and prints an acknowledgement.
3. Public form creates a ticket and requester uses a secure link to reply.
4. Email creates a ticket; subsequent replies update the same conversation.
5. Agent moves a card through permitted statuses; an invalid transition is blocked.
6. SLA warns and breaches according to a test calendar.
7. Operational agent creates a sanitised IT child; IT resolves it; operational owner verifies and closes the parent.
8. Restricted complaint or security ticket is invisible to unauthorised users.
9. Attachment is scanned, quarantined or downloaded according to result and permission.
10. Supervisor views dashboard and audited export.

### 31.4 Security Tests

- Authentication and MFA;
- broken access control and IDOR;
- cross-domain data leakage;
- privilege escalation;
- injection and unsafe deserialisation;
- XSS and HTML sanitisation;
- CSRF;
- SSRF;
- malicious file upload;
- webhook forgery and replay;
- brute force and rate limiting;
- ticket enumeration;
- session revocation;
- export control;
- sensitive log leakage;
- dependency and container vulnerabilities.

### 31.5 Performance and Recovery Tests

- Approved concurrent-user profile;
- queue and board filtering;
- email burst and webhook burst;
- SLA evaluator over the target open-ticket volume;
- report export;
- object upload/download;
- worker recovery after outage;
- point-in-time database restore;
- object-store restore;
- full clean-environment deployment.

## 32. Pilot Delivery Plan

The plan is organised as outcome milestones rather than a promise tied to fixed dates. The product owner may run two-week iterations and approve each gate before proceeding.

### Milestone 0 — Service and Governance Baseline

- Confirm active Master’s Office services and owners;
- map offices, queues and routing;
- approve request types and public wording;
- approve priority, SLA and pause rules;
- complete data classification and DPIA draft;
- approve retention categories;
- confirm email, identity, hosting and backup arrangements;
- initiate WhatsApp Business verification for P1;
- create architecture decision records and UAT plan.

**Exit:** signed service-design baseline and seed-data workbook.

### Milestone 1 — Platform Foundation

- Repository, CI and environments;
- Django, React, PostgreSQL, Keycloak and object storage;
- offices, users, roles and scoped authorization;
- audit foundation;
- health, logs and backups.

**Exit:** staff can authenticate; access-control tests pass; clean deployment and restore succeed.

### Milestone 2 — Operational Vertical Slice

- contacts;
- operational ticket creation;
- catalogue and forms;
- queue/list and Kanban;
- assignment, reply, internal note, attachments;
- workflow and basic SLA;
- public web form and acknowledgement;
- essential dashboard.

**Exit:** one approved operational request type works end to end in UAT.

### Milestone 3 — IT Separation and Cross-Domain Flow

- separate IT domain;
- IT queues/workflow/SLA;
- linked sanitised child ticket;
- restricted security category;
- safe status synchronisation.

**Exit:** cross-domain privacy and workflow tests pass.

### Milestone 4 — P0 Channels and Pilot Readiness

- call-centre and walk-in views;
- inbound/outbound email;
- secure requester link/OTP;
- duplicate/thread handling;
- reporting and exports;
- agent/admin guides;
- security, accessibility, load and recovery tests.

**Exit:** P0 definition of done and selected-office UAT are complete.

### Milestone 5 — P1 Omnichannel

- WhatsApp official API;
- requester portal;
- knowledge and templates;
- automation editor;
- CSAT;
- e-Estate reference validation;
- bilingual public content.

**Exit:** controlled public rollout criteria pass.

### Milestone 6 — Optimisation

- advanced ITSM;
- CTI;
- monitoring;
- flow analytics;
- reporting replica/Metabase;
- HA/DR automation;
- approved AI assistance.

## 33. P0 Acceptance Criteria

The pilot MVP is acceptable only when:

1. Call, walk-in, internal, web and email intake create or update tickets reliably.
2. Each valid new ticket receives a unique reference and acknowledgement.
3. Operational and IT domains are separated in catalogue, workflow, queues, permissions and reports.
4. An IT child ticket copies only selected technical data and no attachment by default.
5. A user with only IT permissions cannot search, count, view or export operational content.
6. Queue/list and Kanban views enforce the same permissions and transitions.
7. Drag-and-drop and keyboard transitions both work.
8. SLA calculations pass approved business-calendar test cases, including pause and resume.
9. Email threading passes reply, duplicate-delivery, bounce and loop tests.
10. Requester status/reply access requires a valid expiring link or code and resists enumeration.
11. Public users never see internal notes, internal statuses, restricted attachments or audit data.
12. Attachments are stored outside PostgreSQL and scanned before access.
13. Required audit events are complete and attributable.
14. Essential dashboards reconcile to source tickets.
15. Backup and restore are demonstrated with evidence.
16. Deployment succeeds from a clean documented environment.
17. Critical business logic and access controls have automated tests.
18. No unresolved critical or high security finding remains.
19. Accessibility tests meet the approved P0 target.
20. Administrators can configure catalogue, forms, statuses, SLA calendars and templates without source changes.
21. Agent, administrator, backup, restore and incident runbooks are delivered.
22. Data protection, retention and production-go-live approvals are recorded.

## 34. Definition of Done for Each Feature

A feature is done only when:

- requirement and acceptance criteria are met;
- server-side authorization and masking are implemented;
- relevant audit events are implemented;
- validation and error states are complete;
- unit and integration tests pass;
- end-to-end coverage exists where material;
- accessibility is checked;
- logging and metrics are included;
- migrations and rollback/restore considerations are documented;
- user/admin documentation is updated;
- no secret or real personal test data is committed;
- code review and security checks pass;
- the feature deploys in a clean environment.

## 35. Coding-Agent Execution Instructions

The coding agent shall:

1. Read the full PRD before changing the repository.
2. Produce a requirement-to-epic traceability map.
3. Record architectural decisions and unresolved assumptions.
4. Never invent a legal service, SLA, retention period or disclosure rule.
5. Preserve the Operational/IT boundary in models, authorization, tests and UI.
6. Build the operational vertical slice before broad feature work.
7. Implement one Django modular monolith; do not introduce a second backend or microservice without an approved ADR.
8. Use typed Python and TypeScript with strict linting and validation.
9. Put critical invariants in database constraints and application services.
10. Store SLA state and integration idempotency in PostgreSQL.
11. Use an outbox pattern for external side effects.
12. Keep channel providers behind interfaces and provide local mocks.
13. Never use unofficial WhatsApp automation.
14. Never commit secrets, tokens, production exports or personal test data.
15. Include migrations and reproducible seed data.
16. Build server-side permission tests before exposing each endpoint.
17. Implement audit and observability as part of each feature, not after it.
18. Provide Docker Compose for development/test and a documented production profile.
19. Generate and validate OpenAPI documentation.
20. Run formatting, linting, typing, unit, integration, end-to-end and security checks before claiming completion.
21. Run a clean build, deployment and restore test before release.
22. Document limitations and failed tests honestly.
23. Do not claim legal compliance without formal review.
24. Do not send AI-generated public or legal content without authorised human approval.

## 36. Required Repository Deliverables

```text
/
├── README.md
├── LICENSES.md
├── SECURITY.md
├── CONTRIBUTING.md
├── docker-compose.yml
├── .env.example
├── docs/
│   ├── prd.md
│   ├── traceability.md
│   ├── architecture.md
│   ├── threat-model.md
│   ├── data-model.md
│   ├── api.md
│   ├── deployment.md
│   ├── backup-restore.md
│   ├── disaster-recovery.md
│   ├── administration.md
│   ├── agent-guide.md
│   ├── requester-guide.md
│   ├── integrations/
│   ├── runbooks/
│   └── adr/
├── frontend/
├── backend/
├── infrastructure/
├── tests/
├── scripts/
└── seed/
```

The release package shall include source, migrations, seed configuration, OpenAPI, test evidence, threat model, data-flow diagram, CI pipeline, deployment files, backup/restore tools, runbooks, user guides, release notes and known limitations.

## 37. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Service catalogue reflects an unconfirmed legal mandate | Configurable catalogue; enable optional functions only after written approval |
| Operational and IT data become mixed | Separate domains, central policy enforcement and sanitised child-ticket pattern |
| Ticket is mistaken for formal filing | Prominent notices, controlled integration boundary and source-system links |
| Email creates duplicate tickets | Header threading, subject token, event idempotency and duplicate suggestions |
| WhatsApp policy or provider changes | Official API, adapter boundary, template governance and email/web fallback |
| Staff continue using personal channels | Approved service policy, integrated mailboxes, simple intake and management reporting |
| Kanban becomes a visual backlog only | Queues, WIP, aging, explicit policies and regular service reviews |
| Over-customisation delays delivery | P0 fixed baseline, configuration governance and change approval |
| Too many infrastructure components | Modular monolith, PostgreSQL search, Compose pilot and deferred optional tools |
| Open-source fork becomes expensive | Prefer stable libraries and adapters; no deep Chatwoot/Frappe fork without lifecycle assessment |
| Sensitive data appears in logs or alerts | Structured redaction, preview rules, secret scanning and audit tests |
| SLA is confused with legal case completion | Separate service-desk targets, public wording and OLA/waiting reason reporting |
| Performance reporting drives harmful behaviour | Balanced measures, quality/wait context and governance |
| Connectivity is unreliable | Lightweight UI, retry queues, channel fallback and documented degraded mode |
| Backup exists but cannot be restored | Mandatory restore evidence before go-live and quarterly testing |

## 38. Open Decisions for Discovery

1. Final product name and branding;
2. confirmed active services and legal owners;
3. offices, regions and routing model;
4. official operational and IT email accounts;
5. official WhatsApp Business number and account owner;
6. whether SMS is required and approved provider;
7. call recording policy and PBX integration method;
8. final request types, forms and confidentiality classes;
9. operational SLA/OLA values and pause rules;
10. closure and reopening period;
11. requester verification methods by service sensitivity;
12. retention and legal-hold schedules;
13. data-residency and production topology;
14. e-Estate integration capability and API owner;
15. siSwati translation and approval process;
16. P0 capacity assumptions based on actual channel volumes;
17. high-availability and disaster-recovery tier;
18. custom-code licence;
19. optional Chatwoot proof-of-concept decision;
20. AI governance, only if later pursued.

## 39. Research-Based Design Rationale

The merged requirements adopt the following proven patterns:

- **monday.com:** board-based work visibility, email-created items/updates and trigger-condition-action automation.
- **Jira Service Management:** focused queues, SLA clocks and impact/urgency priority.
- **Kanban Method:** visualisation, explicit policies, WIP limits and flow metrics.
- **Zammad and Chatwoot:** self-hosted omnichannel conversations, contact history, internal collaboration and channel adapters.
- **GLPI:** separate IT incident/request practices, SLA/OLA and service relationships.
- **Frappe Helpdesk:** open-source ticket portal, SLAs, assignment rules and knowledge; evaluated but not selected as the core because required Kanban/WhatsApp capabilities would still need extension and governance.
- **Official Meta platform:** official Cloud API and provider rules for WhatsApp; no unofficial or discontinued on-premises/browser automation.
- **Django, PostgreSQL and Keycloak:** supported open-source application, database and identity foundations.

## 40. Research Source Register

Sources were reviewed online during July 2026. Product behaviour and versions must be rechecked before implementation.

1. Judiciary of Eswatini, **Master of the High Court**: https://www.judiciary.org.sz/master.php
2. monday.com, **Get started with monday automations**: https://support.monday.com/hc/en-us/articles/360001222900-Get-started-with-monday-automations
3. monday.com, **Email to board**: https://support.monday.com/hc/en-us/articles/115005339645-Email-to-board
4. Atlassian, **How impact and urgency are used to calculate priority**: https://support.atlassian.com/jira-service-management-cloud/docs/how-impact-and-urgency-are-used-to-calculate-priority/
5. Atlassian, **What are queues?**: https://support.atlassian.com/jira-service-management-cloud/docs/what-are-queues/
6. Kanban University, **The Official Guide to the Kanban Method**: https://kanban.university/kanban-guide/
7. Chatwoot source repository and documentation: https://github.com/chatwoot/chatwoot
8. Frappe Helpdesk source repository: https://github.com/frappe/helpdesk
9. Frappe Helpdesk Kanban feature issue reviewed on 18 July 2026: https://github.com/frappe/helpdesk/issues/3391
10. Frappe Helpdesk WhatsApp integration issue reviewed on 18 July 2026: https://github.com/frappe/helpdesk/issues/3379
11. Django, **5.2 release notes / LTS**: https://docs.djangoproject.com/en/6.0/releases/5.2/
12. PostgreSQL, **Versioning Policy**: https://www.postgresql.org/support/versioning/
13. Keycloak documentation: https://www.keycloak.org/documentation
14. Zammad documentation: https://docs.zammad.org/
15. GLPI help and ITSM documentation: https://help.glpi-project.org/
16. Meta for Developers, WhatsApp Business Platform documentation: https://developers.facebook.com/docs/whatsapp/

## 41. Final Product Statement

The MHC Unified Kanban e-Ticketing and Service Desk shall be a secure, open-source-oriented platform that captures supported enquiries, makes ownership and service flow visible, separates operational work from IT support, protects estate and personal information, gives requesters trustworthy feedback and supplies management evidence for continuous improvement.

The selected approach is intentionally smaller than the union of the two source PRDs. It delivers the highest-value and highest-risk controls first, while preserving clear extension paths for WhatsApp, knowledge, e-Estate integration, advanced ITSM, analytics and AI after the core service proves reliable.
