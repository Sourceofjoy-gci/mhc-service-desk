# Accounts Redesign 3: Staff and Manager UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give staff a role-correct Accounts workspace and My Work experience, and give service-desk managers permission-aware monitoring, assignment, and rerouting controls without exposing ticket action controls.

**Architecture:** TypeScript contracts mirror additive server fields and capabilities. Existing Queue, Kanban, Dashboard, and ticket-detail primitives are extended for Accounts rather than duplicated. New My Work and Manager Overview pages consume dedicated server endpoints, while every mutation control is rendered from server-calculated ticket capabilities and handles stale/error envelopes explicitly.

**Tech Stack:** React 18, TypeScript 5.6, React Router 6, TanStack Query 5, Testing Library, Vitest 2, existing Base UI/shadcn components, Tailwind CSS.

## Global Constraints

- Complete Plans 1 and 2 before this plan.
- Preserve unrelated pre-existing working-tree changes; stage only task-owned files or hunks after reviewing `git diff --cached`.
- The frontend never grants authority. Token memberships select navigation/defaults; server capability fields decide ticket controls; API responses remain authoritative.
- Accounts UI copy says enquiry, verification, reference, and status. It must never say that the service desk pays, refunds, approves, or executes a finance transaction.
- Render a persistent warning on Accounts financial-entry forms: never enter card details, bank credentials, PINs, passwords, or authentication secrets.
- Manager-only users may see monitoring, assignment, and routing controls but no Reply, Internal note, Upload, or lifecycle transition controls.
- Restricted ticket links/counts remain absent for managers without a second eligible role.
- Keep keyboard access, visible focus, labels, error summaries, and non-colour status meaning.
- Preserve current URL query state and safe ticket return-location behavior.
- Follow test-driven development and run each new focused Vitest file in the red state first.

## File Structure

- `frontend/src/lib/api.ts`: server contracts and request methods only.
- `frontend/src/lib/domain-access.ts`: token-membership navigation/default helpers, separate from transport.
- `frontend/src/features/tickets/MyWorkPage.tsx`: assigned-to-me view and work-group filters.
- `frontend/src/features/tickets/FinancialEnquiryPanel.tsx`: Accounts context editor and safety copy.
- `frontend/src/features/tickets/RoutingPanel.tsx`: capability-gated route correction.
- `frontend/src/features/reports/ManagerOverviewPage.tsx`: cross-domain operational overview.
- `frontend/src/features/notifications/NotificationMenu.tsx`: scoped in-app assignment notifications.
- Existing Queue/Kanban/Dashboard/Operations/Transition components remain shared across domains.

---

### Task 1: Align frontend contracts and membership-derived navigation

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/domain-access.ts`
- Create: `frontend/src/lib/domain-access.test.ts`
- Modify: `frontend/src/lib/ticket-contracts.test.ts`
- Modify: `frontend/src/components/domain-badges.tsx`
- Modify: `frontend/src/features/auth/AuthProvider.test.tsx`

**Interfaces:**
- Produces: `Domain = "operational" | "it" | "accounts"`.
- Produces: `domainAccess(groups) -> {queueDomains, dashboardDomains, showMyWork, showManagerOverview, showRoutingExceptions}`.
- Produces: typed assignment, routing, financial-state, My Work, manager overview, notification, Service, Office, and routing-exception contracts.
- Updates: `TicketCapabilities` exposes `can_action`, `can_self_assign`, `can_assign`, `can_reroute`, `can_monitor`, and existing granular content/confidentiality fields.

- [ ] **Step 1: Write failing role-to-navigation tests**

Create `domain-access.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { domainAccess } from "./domain-access";

describe("domainAccess", () => {
  it.each([
    ["agent-operational", ["operational"]],
    ["agent-it", ["it"]],
    ["agent-accounts", ["accounts"]],
  ] as const)("maps %s to its queue", (membership, expected) => {
    expect(domainAccess([membership]).queueDomains).toEqual(expected);
  });

  it("gives service managers all normal domain navigation", () => {
    expect(domainAccess(["/service-desk-managers"])).toEqual({
      queueDomains: ["operational", "it", "accounts"],
      dashboardDomains: ["operational", "it", "accounts"],
      showMyWork: false,
      showManagerOverview: true,
      showRoutingExceptions: true,
    });
  });

  it("does not give technical administrators business navigation", () => {
    expect(domainAccess(["admin", "system-admins"]).queueDomains).toEqual([]);
    expect(domainAccess(["admin"]).showManagerOverview).toBe(false);
  });

  it("keeps security responders out of unrestricted dashboards", () => {
    const access = domainAccess(["security-responders"]);
    expect(access.queueDomains).toEqual(["operational", "it", "accounts"]);
    expect(access.dashboardDomains).toEqual([]);
  });
});
```

Add a composed-role case showing `service-desk-manager + agent-accounts` has manager navigation and My Work.

- [ ] **Step 2: Run the navigation tests and verify the missing Accounts/type failures**

Run:

```powershell
Set-Location frontend
npm test -- --run src/lib/domain-access.test.ts src/lib/ticket-contracts.test.ts
```

Expected: FAIL because `Domain` excludes Accounts and the helper/contracts do not exist.

- [ ] **Step 3: Define exact transport contracts**

In `api.ts`, extend `Domain` and add:

```typescript
export type FinancialEnquiryCategory =
  | "payment"
  | "invoice"
  | "refund"
  | "fee"
  | "receipt"
  | "financial_status";

export type FinancialVerificationStatus =
  | "not_required"
  | "pending"
  | "verified"
  | "not_found"
  | "disputed";

export interface AssignmentRequest {
  assignee_id: string;
  expected_updated_at: string;
  reason?: string;
}

export interface RoutingRequest {
  service_code: string;
  request_type_code: string;
  office_code: string;
  queue_id?: string | null;
  priority?: Priority;
  expected_updated_at: string;
  reason: string;
}

export interface FinancialStateRequest {
  updated_at: string;
  financial_enquiry_category?: FinancialEnquiryCategory;
  financial_reference?: string;
  external_finance_reference?: string;
  enquiry_amount?: string | null;
  enquiry_currency?: string;
  financial_verification_status?: FinancialVerificationStatus;
}
```

Add the seven structured financial fields to `TicketDetail`, `work_flags` to `TicketSummary`, additive capability booleans, and the exact response interfaces from Plan 2. Type each Request Type's `requires_financial_verification` and `requires_supervisor_review` flags. Keep legacy `can_reassign` during the compatibility release but drive new UI from `can_assign`.

Add methods:

```typescript
assign: (number: string, values: AssignmentRequest) =>
  api<TicketDetail>(`/tickets/${number}/assignment/`, { method: "POST", body: values }),
routing: (number: string, values: RoutingRequest) =>
  api<TicketDetail>(`/tickets/${number}/routing/`, { method: "POST", body: values }),
updateFinancialState: (number: string, values: FinancialStateRequest) =>
  api<TicketDetail>(`/tickets/${number}/financial-state/`, { method: "PATCH", body: values }),
myWork: async (params: Record<string, string> = {}) =>
  normalizePage(await api<unknown>(`/tickets/my-work/?${new URLSearchParams(params)}`)),
```

Add typed `reportsApi.managerOverview`, `notificationsApi.list/markRead`, `routingExceptionsApi.list/resolve/dismiss`, `servicesApi.list`, and `organisationsApi.offices`.

- [ ] **Step 4: Move membership logic into `domain-access.ts`**

Normalise group paths by their last non-empty segment. Use explicit sets for Accounts aliases, manager aliases, auditors, security responders, and technical administrators. Return domains in fixed order `operational`, `it`, `accounts` so query canonicalisation is deterministic.

Auditors receive all queue/dashboard domains and manager-style read-only reporting; technical administrators receive none. `showMyWork` is true only if a membership grants a domain action role. `showManagerOverview` is true for managers or auditors. Do not infer any mutation capability here.

- [ ] **Step 5: Add Accounts badges and contract assertions**

Add a text-visible Accounts badge style to `domain-badges.tsx` and tests that unknown domain/status values still render safe humanised text. In `ticket-contracts.test.ts`, assert API fixtures include all new capability and financial keys and that the parser/test fixture does not accept numeric amounts as executable transaction values.

- [ ] **Step 6: Verify types and commit**

Run:

```powershell
Set-Location frontend
npm test -- --run src/lib/domain-access.test.ts src/lib/ticket-contracts.test.ts src/features/auth/AuthProvider.test.tsx
npm run typecheck
npm run lint
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/lib/api.ts frontend/src/lib/domain-access.ts frontend/src/lib/domain-access.test.ts frontend/src/lib/ticket-contracts.test.ts frontend/src/components/domain-badges.tsx frontend/src/features/auth/AuthProvider.test.tsx
git diff --cached --check
git commit -m "feat(frontend): add accounts role contracts"
```

---

### Task 2: Add My Work and Accounts queue/Kanban navigation

**Files:**
- Create: `frontend/src/features/tickets/MyWorkPage.tsx`
- Create: `frontend/src/features/tickets/MyWorkPage.test.tsx`
- Modify: `frontend/src/features/tickets/QueuePage.tsx`
- Modify: `frontend/src/features/tickets/QueuePage.test.tsx`
- Modify: `frontend/src/features/tickets/KanbanPage.tsx`
- Modify: `frontend/src/features/tickets/KanbanPage.test.tsx`
- Modify: `frontend/src/features/tickets/TicketCard.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`
- Modify: `frontend/src/components/app-shell.tsx`

**Interfaces:**
- Produces route: `/my-work`.
- Updates: `/tickets`, `/kanban`, and their domain query parameters accept Accounts.
- Consumes: `ticketsApi.myWork`, `domainAccess`, and server `work_flags`.

- [ ] **Step 1: Write failing My Work behavior tests**

Cover loading, empty, error, stale query canonicalisation, pagination, and filters. The main success test must assert:

```typescript
it("shows only server-returned assigned work and attention flags", async () => {
  server.use(
    http.get("*/api/v1/tickets/my-work/", () =>
      HttpResponse.json({
        next: null,
        previous: null,
        results: [ticket({
          number: "AC-202607-000001",
          domain: "accounts",
          work_flags: ["due_soon", "waiting"],
        })],
      }),
    ),
  );
  renderAppAt("/my-work?status_group=waiting");
  expect(await screen.findByRole("link", { name: /AC-202607-000001/i })).toBeVisible();
  expect(screen.getByText("Due soon")).toBeVisible();
  expect(screen.getByText("Waiting")).toBeVisible();
});
```

Add a baseline `staff` and manager-only case that renders the permission page rather than calling My Work; a combined manager+Accounts agent may use it.

- [ ] **Step 2: Write failing Accounts queue and Kanban tests**

Add tests proving:

- an Accounts agent defaults `/tickets` and `/kanban` to `domain=accounts`;
- the domain selector includes Accounts for managers/auditors;
- Accounts status filters include Pending Financial Verification, Waiting for Internal Finance Unit, and Supervisor Review;
- Operational/IT-only users cannot force `domain=accounts` through the URL; and
- technical administrators have no business queue page.

- [ ] **Step 3: Run page tests in the red state**

Run:

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/MyWorkPage.test.tsx src/features/tickets/QueuePage.test.tsx src/features/tickets/KanbanPage.test.tsx src/app/App.test.tsx
```

Expected: FAIL because the page/route and Accounts options are absent.

- [ ] **Step 4: Implement My Work with URL-backed filters**

Use fixed filter options:

```typescript
const WORK_GROUPS = [
  { value: "active", label: "Active" },
  { value: "waiting", label: "Waiting" },
  { value: "due_soon", label: "Due soon" },
  { value: "at_risk", label: "SLA at risk" },
  { value: "breached", label: "SLA breached" },
  { value: "overdue", label: "Overdue" },
  { value: "recently_reassigned", label: "Recently reassigned" },
] as const;
```

Canonicalise invalid/duplicate `status_group`, `domain`, `priority`, and `cursor` parameters as QueuePage does. Query with `queryKey: ["my-work", params]`, keep server pagination links scoped through `cursorFromPageLink`, and retain `/my-work?...` as the ticket return location.

Use TicketCard work flags as labelled badges; never derive SLA status in the browser.

- [ ] **Step 5: Extend shared queue and Kanban components**

Replace hard-coded two-domain arrays with a shared `DOMAIN_OPTIONS` exported from `domain-access.ts`. Define status options by domain so Accounts-only values are not shown for Operational or IT. Keep unknown server statuses visible through the existing humaniser.

Update App routes and desktop/mobile navigation. Show My Work only when `showMyWork`; show Queue/Kanban only when `queueDomains.length > 0`. Preserve public links and protected-route behavior.

- [ ] **Step 6: Verify staff navigation and commit**

Run:

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/MyWorkPage.test.tsx src/features/tickets/QueuePage.test.tsx src/features/tickets/KanbanPage.test.tsx src/app/App.test.tsx
npm run typecheck
npm run lint
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/features/tickets/MyWorkPage.tsx frontend/src/features/tickets/MyWorkPage.test.tsx frontend/src/features/tickets/QueuePage.tsx frontend/src/features/tickets/QueuePage.test.tsx frontend/src/features/tickets/KanbanPage.tsx frontend/src/features/tickets/KanbanPage.test.tsx frontend/src/features/tickets/TicketCard.tsx frontend/src/app/App.tsx frontend/src/app/App.test.tsx frontend/src/components/app-shell.tsx
git diff --cached --check
git commit -m "feat(frontend): add accounts and my work views"
```

---

### Task 3: Separate assignment/routing and add Accounts enquiry controls

**Files:**
- Modify: `frontend/src/features/tickets/OperationsPanel.tsx`
- Modify: `frontend/src/features/tickets/OperationsPanel.test.tsx`
- Create: `frontend/src/features/tickets/FinancialEnquiryPanel.tsx`
- Create: `frontend/src/features/tickets/FinancialEnquiryPanel.test.tsx`
- Create: `frontend/src/features/tickets/RoutingPanel.tsx`
- Create: `frontend/src/features/tickets/RoutingPanel.test.tsx`
- Modify: `frontend/src/features/tickets/TransitionActions.tsx`
- Modify: `frontend/src/features/tickets/TransitionActions.test.tsx`
- Modify: `frontend/src/features/tickets/TicketDetailPage.tsx`
- Modify: `frontend/src/features/tickets/TicketDetailPage.test.tsx`
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Consumes: `ticketsApi.assign`, `ticketsApi.routing`, `ticketsApi.updateFinancialState`, typed Services/Request Types/Offices, and server capability booleans.
- Produces: assignment requests separate from ordinary `updateWorkState`.
- Produces: Accounts-only financial context and resolution controls.
- Produces: rerouting controls only when `can_reroute` is true.

- [ ] **Step 1: Write failing manager-only workspace tests**

Render an Accounts ticket with capabilities:

```typescript
capabilities: {
  can_action: false,
  can_self_assign: false,
  self_assignee_id: null,
  can_assign: true,
  can_reroute: true,
  can_monitor: true,
  can_change_confidentiality: false,
  can_add_message: false,
  can_add_note: false,
  can_upload_attachment: false,
}
```

Assert assignment and routing controls are visible, while Reply, Internal note, Upload attachment, financial editing, and lifecycle actions are absent. Submit reassignment and assert the request body includes `assignee_id`, `expected_updated_at`, and a nonblank reason and does not call `/work-state/`.

- [ ] **Step 2: Write failing Accounts agent financial tests**

Assert the panel:

- appears only for `domain="accounts"`;
- displays all six categories and five verification statuses;
- pairs amount with a three-letter currency;
- shows the credential safety warning;
- sends only allowlisted financial-state keys;
- reloads on `stale_ticket`; and
- never labels the action Pay, Refund, Approve, or Execute.

Add transition tests requiring a checked `no_transaction_executed` box for an Accounts resolving transition and omitting it for Operational/IT resolution.

- [ ] **Step 3: Run workspace tests in the red state**

Run:

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/OperationsPanel.test.tsx src/features/tickets/FinancialEnquiryPanel.test.tsx src/features/tickets/RoutingPanel.test.tsx src/features/tickets/TransitionActions.test.tsx src/features/tickets/TicketDetailPage.test.tsx
```

Expected: FAIL because assignment still uses work-state and the financial/routing panels do not exist.

- [ ] **Step 4: Split assignment from ordinary work-state edits**

Keep team, waiting reason, blocked reason, next action, next-action date, and confidentiality in `updateWorkState`. Use a separate assignment mutation:

```typescript
const assignment = useMutation({
  mutationFn: (values: { assigneeId: string; reason: string }) =>
    ticketsApi.assign(ticket.number, {
      assignee_id: values.assigneeId,
      expected_updated_at: ticket.updated_at,
      reason: values.reason || undefined,
    }),
  onSuccess: handleUpdatedTicket,
});
```

Self-assignment uses `self_assignee_id` and no reason. Assignment to another user requires a visible reason field. Disable duplicate submissions, show server field errors, and show a Reload action for `stale_ticket`.

- [ ] **Step 5: Implement Accounts financial enquiry panel**

Initial form values come only from TicketDetail. Submit `enquiry_amount` as a decimal string, uppercase currency before sending, and require both or neither. Render this warning above the form:

> Enquiry context only. Do not enter card details, bank credentials, PINs, passwords, or authentication secrets. Financial transactions are completed only in the authorised finance system.

Read-only users see labelled financial values with blank values rendered as Not provided. Action-capable Accounts agents/supervisors receive Save controls. Never render this panel for other domains.

- [ ] **Step 6: Implement capability-gated routing**

Fetch Services and Offices only when `can_reroute`. Changing Service filters Request Types to that Service and resets an incompatible Request Type. Changing Office resets a queue not belonging to that office. The reason field is always required.

Submit:

```typescript
ticketsApi.routing(ticket.number, {
  service_code: selectedService.code,
  request_type_code: requestTypeCode,
  office_code: officeCode,
  queue_id: queueId || null,
  priority,
  expected_updated_at: ticket.updated_at,
  reason: reason.trim(),
});
```

After success, replace cached detail, invalidate Queue/My Work/Dashboard/Manager Overview queries, and announce that routing may have cleared an ineligible assignee. Handle `invalid_route`, field validation, 403, and stale reload explicitly.

- [ ] **Step 7: Add Accounts resolution affirmation**

When `ticket.domain === "accounts" && transition.requires_resolution`, render a required checkbox labelled `I confirm no financial transaction was executed in the service desk`. Include `no_transaction_executed: true` only when checked. Include `external_finance_reference` when entered; resolution code and summary remain required.

- [ ] **Step 8: Integrate panels into ticket detail and verify**

Place FinancialEnquiryPanel with ticket context, OperationsPanel with assignment/work-state, RoutingPanel for eligible users, and existing SLA/activity components. Render MessageComposer, AttachmentUploader, and TransitionActions only from their server capabilities.

Run:

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/OperationsPanel.test.tsx src/features/tickets/FinancialEnquiryPanel.test.tsx src/features/tickets/RoutingPanel.test.tsx src/features/tickets/TransitionActions.test.tsx src/features/tickets/TicketDetailPage.test.tsx
npm run typecheck
npm run lint
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/features/tickets/OperationsPanel.tsx frontend/src/features/tickets/OperationsPanel.test.tsx frontend/src/features/tickets/FinancialEnquiryPanel.tsx frontend/src/features/tickets/FinancialEnquiryPanel.test.tsx frontend/src/features/tickets/RoutingPanel.tsx frontend/src/features/tickets/RoutingPanel.test.tsx frontend/src/features/tickets/TransitionActions.tsx frontend/src/features/tickets/TransitionActions.test.tsx frontend/src/features/tickets/TicketDetailPage.tsx frontend/src/features/tickets/TicketDetailPage.test.tsx frontend/src/lib/api.ts
git diff --cached --check
git commit -m "feat(frontend): add accounts ticket controls"
```

---

### Task 4: Add Accounts dashboard, manager overview, routing exceptions, and notifications

**Files:**
- Modify: `frontend/src/features/reports/DashboardPage.tsx`
- Modify: `frontend/src/features/reports/DashboardPage.test.tsx`
- Create: `frontend/src/features/reports/ManagerOverviewPage.tsx`
- Create: `frontend/src/features/reports/ManagerOverviewPage.test.tsx`
- Create: `frontend/src/features/tickets/RoutingExceptionsPage.tsx`
- Create: `frontend/src/features/tickets/RoutingExceptionsPage.test.tsx`
- Create: `frontend/src/features/notifications/NotificationMenu.tsx`
- Create: `frontend/src/features/notifications/NotificationMenu.test.tsx`
- Modify: `frontend/src/components/app-shell.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Produces routes: `/manager`, `/routing-exceptions`.
- Updates route: `/dashboard?domain=accounts`.
- Consumes: `reportsApi.managerOverview`, `routingExceptionsApi`, and `notificationsApi`.

- [ ] **Step 1: Write failing Accounts dashboard tests**

Assert Accounts agents/supervisors/managers/auditors can select Accounts as allowed by `domainAccess`, the heading is `Accounts dashboard`, status rows render Accounts labels, and the fifth metric is SLA breach rather than IT P1/P2. An Operational-only user cannot retain an Accounts domain URL.

- [ ] **Step 2: Write failing manager overview tests**

Mock a three-domain response and assert the page renders:

- unassigned and oldest-unassigned age per domain;
- active/waiting/overdue workload per staff member;
- SLA due-soon/at-risk/breached metrics;
- domain/service/request type/office/queue/priority/status/assignee filters in the URL;
- links to filtered Queue views; and
- no Restricted metric or ticket identifier absent from the response.

Manager-only users may open the page; ordinary agents and technical administrators receive PermissionPage; auditors see the page without mutation shortcuts.

- [ ] **Step 3: Write failing routing exception and notification tests**

For routing exceptions, assert a manager sees metadata only, can choose a configured Service/Request Type and enter a reason, and can dismiss with a reason. Assert no raw body/description field is rendered.

For NotificationMenu, assert recipient-scoped rows display assignment/reassignment, mark read through the API, use safe relative ticket links, show unread count, and do not render a server link outside `/tickets/`.

- [ ] **Step 4: Run reporting/notification UI tests in the red state**

Run:

```powershell
Set-Location frontend
npm test -- --run src/features/reports/DashboardPage.test.tsx src/features/reports/ManagerOverviewPage.test.tsx src/features/tickets/RoutingExceptionsPage.test.tsx src/features/notifications/NotificationMenu.test.tsx src/app/App.test.tsx
```

Expected: FAIL because the pages/menu and Accounts dashboard option are absent.

- [ ] **Step 5: Implement dashboards and manager filters**

Extend the shared dashboard domain options and known Accounts statuses. In ManagerOverviewPage, keep one canonical `URLSearchParams` source, remove cursors whenever a filter changes, query every 30 seconds, and use metric cards/table components already used by DashboardPage.

Drill-down links must be generated with `URLSearchParams`, for example:

```typescript
const queueLink = (domain: Domain, extra: Record<string, string> = {}) => {
  const params = new URLSearchParams({ domain, ...extra });
  return `/tickets?${params.toString()}`;
};
```

Do not calculate counts from already rounded display values.

- [ ] **Step 6: Implement routing-exception and notification views**

RoutingExceptionsPage is manager-only by token navigation and server 403. Show source, source account, reason code, allowed route metadata, created time, and actions. After resolve/dismiss, invalidate exception and manager-overview queries.

NotificationMenu uses a dropdown or sheet with a button labelled `Notifications, N unread`. Poll every 30 seconds while authenticated. Admit a link only when a URL parsed against `window.location.origin` has the same origin and pathname matching `/tickets/{number}`; otherwise render the notification without a link.

- [ ] **Step 7: Add role-correct routes/navigation and verify**

Show Manager Overview and Routing Exceptions only when the domain-access helper permits them. Show Notifications to every authenticated functional staff role; an empty baseline Staff identity sees an empty notification menu and no business navigation.

Run:

```powershell
Set-Location frontend
npm test -- --run src/features/reports src/features/tickets/RoutingExceptionsPage.test.tsx src/features/notifications/NotificationMenu.test.tsx src/app/App.test.tsx
npm run typecheck
npm run lint
npm run build
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/features/reports/DashboardPage.tsx frontend/src/features/reports/DashboardPage.test.tsx frontend/src/features/reports/ManagerOverviewPage.tsx frontend/src/features/reports/ManagerOverviewPage.test.tsx frontend/src/features/tickets/RoutingExceptionsPage.tsx frontend/src/features/tickets/RoutingExceptionsPage.test.tsx frontend/src/features/notifications/NotificationMenu.tsx frontend/src/features/notifications/NotificationMenu.test.tsx frontend/src/components/app-shell.tsx frontend/src/app/App.tsx frontend/src/app/App.test.tsx
git diff --cached --check
git commit -m "feat(frontend): add manager oversight workspace"
```

---

## Plan 3 Completion Gate

Run from the repository root:

```powershell
docker compose run --rm --no-deps --build --volume /app/node_modules frontend env VITE_API_BASE_URL= npm test -- --run
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run typecheck
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run lint
docker compose run --rm --no-deps --build --volume /app/node_modules frontend npm run build
```

Expected: all commands exit 0; Accounts staff can reach Accounts/My Work; manager-only users can monitor/assign/reroute but cannot action; technical administrators have no business navigation; and notification/routing links cannot escape authorised application paths.
