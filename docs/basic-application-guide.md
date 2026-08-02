# MHC Service Desk: Basic Application Guide

This guide explains the current application roles, the main functions available
to users, and the basic ticket workflow. It is intended as a quick introduction
for staff, supervisors, administrators, auditors, and support teams.

## 1. Application purpose

The MHC Service Desk records and manages enquiries as tickets. It provides two
separate work domains:

- **Operational:** estates, wills, public enquiries, calls, and walk-ins.
- **IT:** internal technical incidents, service requests, monitoring alerts,
  and sanitised work referred by the Operational desk.

Access is role-based. The application may show the same main navigation to
several staff roles, but the backend decides which domains, tickets, fields,
and actions each signed-in user may use.

## 2. Roles and basic permissions

Users are normally assigned to a Keycloak group. Each group supplies the
corresponding realm role shown below.

| Keycloak group | Realm role | Basic access and functions |
|---|---|---|
| None (baseline role) | `staff` | Baseline staff authentication only. This role allows sign-in but does not grant a ticket domain by itself. |
| `ops-agents` | `agent-operational` | View and work on non-restricted Operational tickets. May self-assign eligible tickets, update work state, reply, add internal notes, upload attachments, and use permitted lifecycle transitions. |
| `ops-supervisors` | `supervisor-operational` | All Operational agent functions, plus access to restricted Operational tickets. May reassign eligible Operational tickets and change confidentiality. |
| `it-agents` | `agent-it` | View and work on non-restricted IT tickets. May self-assign eligible tickets, update work state, add messages or notes, upload attachments, and use permitted IT lifecycle transitions. |
| `it-leads` | `lead-it` | All IT agent functions, plus access to restricted IT tickets. May reassign eligible IT tickets and change confidentiality. |
| `security-responders` | `staff` | View restricted tickets in both domains. Does not grant ordinary Operational or IT tickets or domain dashboards. By itself it does not grant the standard work-state, message, note, or upload controls; only lifecycle actions returned by the server are available. |
| `system-admins` | `admin` | Administrative access across both domains, including restricted tickets. May update work state, add content, reassign tickets, change confidentiality, and use permitted lifecycle transitions. |
| `auditors` | `auditor` | Read-only access across both domains, including restricted tickets and reporting. Cannot change tickets, send messages, add notes, upload files, assign work, or run transitions. |

Important access rules:

- Every functional group also receives the baseline `staff` role.
- A user may have more than one group; the resulting access is combined unless
  a persisted assignment narrows it.
- Persisted assignments may restrict a user to a particular office, service,
  or queue and take precedence over the broad Keycloak group fallback.
- Inactive users have no access.
- Out-of-scope tickets normally return **404 Not Found** so another domain
  cannot be enumerated.
- Restricted tickets are available only to supervisors, IT leads, security
  responders, system administrators, auditors, or another explicitly
  authorised assignment.
- A hidden or disabled control means the server has not granted that action.

### Public users

A public requester is not a staff role. Public users may submit an enquiry on
the public form without signing in and may view the public health page. They do
not receive access to staff queues, ticket workspaces, internal notes, or
reports.

## 3. Main application functions

| Area | Route | Basic function |
|---|---|---|
| Public form | `/public` | Submit an enquiry without staff sign-in and receive a ticket number. This records an enquiry; it is not a formal legal filing. |
| Staff sign-in | `/login` | Authenticate through Keycloak and start a role-based staff session. |
| Home | `/` | View platform status and shortcuts to the main work areas. |
| Queue | `/tickets` | View only in-scope tickets. Filter by domain, status, priority, channel, office, search text, and sort order. |
| Track ticket | `/ticket-tracking` | Look up requester-safe progress by immutable reference. Requires staff authentication and authorised ticket scope. |
| Ticket workspace | `/tickets/{number}` | View ticket details, requester information, lifecycle actions, activity, work state, SLA clocks, relationships, and attachments. |
| Kanban | `/kanban` | View active tickets by status and request server-validated status changes by drag-and-drop or keyboard interaction. |
| Dashboard | `/dashboard` | View domain totals, priority breakdowns, SLA breaches, and backlog information. Requires unrestricted access to the selected domain. |
| Call capture | `/intake/call` | Capture a call-centre enquiry on behalf of a requester. |
| Walk-in capture | `/intake/walk-in` | Capture an in-person enquiry and issue a ticket number. |
| Health | `/health` | View the current availability of the application and supporting services. |
| User menu | Header menu | View the signed-in identity, change the display theme, and sign out. |

Other supported intake channels include email, WhatsApp, internal referrals,
and monitoring alerts. These channels create or update tickets through their
configured integrations rather than a dedicated staff capture page.

## 4. Ticket workspace functions

When a user opens a ticket, the workspace provides the following basic tools
when permitted by the server:

- **Ticket summary:** number, title, description, status, priority, channel,
  domain, office, service, request type, requester, and matter reference.
- **Lifecycle actions:** only transitions valid for the current status and
  role are displayed.
- **Operations:** self-assignment, reassignment, team, confidentiality,
  waiting reason, blocked reason, next action, and next-action date.
- **Reply:** sends a requester-visible message.
- **Internal note:** records staff-only information that is never shown to the
  requester.
- **Activity:** shows messages, notes, transitions, work-state changes,
  relationships, and attachment events in server order.
- **SLA clocks:** shows first-response and resolution timing and breach state.
- **Attachments:** uploads files for malware scanning and permits downloads
  only when the scan result is clean.
- **Relationships:** shows authorised parent, child, duplicate, or related
  ticket links.

Supervisors, IT leads, and administrators receive reassignment and
confidentiality controls only for tickets within their authority. Eligible
assignee lists exclude inactive users and auditors.

## 5. End-to-end ticket workflow

The basic flow is:

1. **Intake:** a request arrives from the public form, call centre, walk-in,
   email, WhatsApp, internal referral, or monitoring.
2. **Creation:** the application validates the request, assigns an immutable
   ticket reference, records the source channel, and starts the ticket in **New**.
3. **Scope and queue:** the ticket appears only in queues permitted by the
   user's role, domain, office, service, and queue assignments.
4. **Triage:** staff confirm the classification, priority, requester details,
   confidentiality, and required destination.
5. **Assignment:** an eligible agent self-assigns the ticket, or an authorised
   supervisor, IT lead, or administrator reassigns it.
6. **Work:** the assignee records the next action, communicates with the
   requester, adds internal notes, handles attachments, and moves the ticket
   through server-approved statuses.
7. **Waiting or referral:** the ticket may wait for the requester, another
   internal unit, IT, a vendor, or a scheduled change. Follow-up information
   should be recorded in the work state.
8. **Review:** Operational tickets may enter Quality Review; IT tickets may
   enter Validation.
9. **Resolution:** a resolving transition requires a resolution code and a
   resolution summary. The SLA and activity history are updated.
10. **Closure or reopening:** a resolved ticket may be closed or reopened.
    Reopening clears the active resolution fields while retaining the previous
    resolution in the history.

Every accepted update is recorded in the ticket activity and audit trail.
Work-state and lifecycle requests include the version of the ticket the user
opened. If another user changes it first, the application returns a
`409 stale_ticket`; reload the ticket, review the new state, and then decide
whether to resubmit.

### Staff-assisted reference tracking

After capturing a call or walk-in request, give the displayed reference to the
requester. Open **Track ticket**, enter the exact reference, and review the
requester-safe progress milestones while assisting them. Use **Open full
ticket** only when internal detail or the complete audit history is needed.
Tracking is restricted to authenticated staff and the server returns a result
only when the ticket falls within that staff member's authorised scope.
New references contain exactly six characters: one leading letter and five digits
(for example, `O00123`).

## 6. Operational workflow

The server shows only transitions that are valid from the current status.

| Current status | Available next steps |
|---|---|
| New | Begin triage |
| Triage | Assign, start work, refer internally, refer to IT, mark duplicate, mark spam, cancel, or reject |
| Assigned | Start work or wait on requester |
| In Progress | Wait on requester, wait on internal unit, wait on IT, send to Quality Review, or resolve |
| Waiting for Requester | Return to In Progress when the requester replies |
| Waiting for Internal Unit | Return to In Progress when the internal reply arrives |
| Waiting for IT | Return to In Progress when the IT reply arrives |
| Quality Review | Return to In Progress or resolve after review |
| Resolved | Reopen or close |
| Reopened | Resume In Progress work |
| Cancelled, Rejected, Duplicate, or Spam | Close where the configured transition is available |
| Closed | Terminal state; no further standard workflow action |

Operational resolution can occur from **In Progress** or **Quality Review** and
requires a resolution code and summary.

## 7. IT workflow

| Current status | Available next steps |
|---|---|
| New | Begin triage |
| Triage | Assign, start work, begin diagnosis, or cancel |
| Assigned | Begin diagnosis or start work |
| Diagnosing | Move to In Progress |
| In Progress | Wait on user, wait on vendor, schedule a change, or send to Validation |
| Waiting for User | Return to In Progress when the user replies |
| Waiting for Vendor | Return to In Progress when the vendor replies |
| Waiting for Change | Move to Validation when the change is complete |
| Validation | Return to In Progress or resolve |
| Resolved | Reopen or close |
| Reopened | Resume In Progress work |
| Cancelled or Closed | Terminal state; no further standard workflow action |

IT resolution occurs from **Validation** and requires a resolution code and
summary.

## 8. Operational-to-IT handoff

Operational and IT data remain separated. The backend supports creation of a
sanitised IT child ticket:

1. An authorised process creates an IT child from an Operational parent.
2. Only approved, sanitised context is copied to the IT child.
3. Operational message bodies, internal notes, and attachments are not copied.
4. The Operational parent moves to **Waiting for IT**.
5. When IT returns the child, a safe status summary is recorded on the parent
   and Operational work resumes.

The current staff workspace does not expose a create-IT-child button. Staff
must use the approved escalation or authorised integration until that user
interface is delivered.

## 9. Basic operating rules

- Use **Reply** only for information that the requester may see.
- Use **Internal note** for staff-only context; never copy it into a reply by
  mistake.
- Do not share passwords, access tokens, or screenshots containing sensitive
  requester information.
- Do not move information between Operational and IT tickets manually.
- Download only attachments marked clean; quarantine or escalate infected and
  failed scans.
- Resolve a ticket only when the resolution code and summary accurately record
  the outcome.
- If access appears incorrect, ask a supervisor or administrator to review the
  user's Keycloak groups and any persisted office, service, or queue assignment.
- Treat the server-provided activity history as the record of accepted actions.

## 10. Common access and workflow responses

| Response | Meaning | Basic action |
|---|---|---|
| `401` | The session is missing or expired. | Sign in again. |
| `403` | The user is authenticated but does not have the required authority. | Confirm the selected domain and ask for a role review if necessary. |
| `404` | The item does not exist or is intentionally hidden because it is out of scope. | Check the ticket number and assigned domain. |
| `400` | One or more submitted fields are invalid. | Correct the named fields and submit again. |
| `409 stale_ticket` | Another user changed the ticket first. | Reload, review the current state, and resubmit only if still appropriate. |

## 11. Related detailed documentation

- [Agent guide](agent-guide.md)
- [Permission matrix](permission-matrix.md)
- [Architecture](architecture.md)
- [Pilot runbook](pilot-runbook.md)
