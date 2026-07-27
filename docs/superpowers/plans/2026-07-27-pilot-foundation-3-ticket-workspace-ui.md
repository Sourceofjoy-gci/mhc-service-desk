# Pilot Foundation 3: Ticket Workspace UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn ticket detail into a complete operator workspace for assignment, planning, valid transitions, resolution/reopen, SLA visibility, activity, and attachments.

**Architecture:** The page consumes server-derived capabilities and workflow actions; it never recreates authorization or transition rules. Focused components own operations, transitions, activity, and files while `TicketDetailPage` coordinates queries and server-confirmed refreshes. All mutations are non-optimistic and use the ticket's last `updated_at` value.

**Tech Stack:** React 18, TypeScript 5.6, TanStack Query 5, React Router 6, Base UI/shadcn components, Vitest 2, Testing Library, existing REST API client.

## Global Constraints

- Complete Plans 1 and 2 before this plan and consume their canonical API contracts.
- Preserve unrelated working-tree changes and stage only current-task files.
- The listed file-level `git add` commands apply only to paths that were clean at task start. For an already-dirty path, stage only task-owned hunks after reviewing `git diff --cached`; if a hunk cannot be separated from pre-existing work, leave that path uncommitted rather than include someone else's changes.
- Render only server-provided transitions and server-confirmed elevated capabilities.
- Send `updated_at` with every work-state and transition mutation.
- Do not update lifecycle UI optimistically; disable duplicate submissions and replace local state with the successful server response.
- Preserve form values and render field messages from `{code, detail, fields, correlation_id}`.
- Treat `409 stale_ticket` as a reload decision, never as a silent retry.
- Follow test-driven development for every component and client method.

---

### Task 1: Define lifecycle API types and client methods

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/ticket-contracts.test.ts`

**Interfaces:**
- Produces: typed detail capabilities, transitions, SLA clocks, activity, assignees, and attachments.
- Produces: `ticketsApi.updateWorkState`, `ticketsApi.activity`, `ticketsApi.assignees`, enhanced `ticketsApi.transition`, and `attachmentsApi` methods.

- [ ] **Step 1: Write failing API contract tests**

Mock `fetch` and assert exact paths, methods, and request bodies for:

```typescript
await ticketsApi.updateWorkState("OP-202607-000001", {
  updated_at: "2026-07-27T08:00:00Z",
  next_action: "Call requester",
  next_action_at: "2026-07-28T08:00:00Z",
});

await ticketsApi.transition("OP-202607-000001", {
  to_status: "resolved",
  updated_at: "2026-07-27T08:00:00Z",
  reason: "Completed",
  resolution_code: "INFO_PROVIDED",
  resolution_summary: "The requester received the required information.",
});
```

Assert activity and assignee methods call the ticket subresources. Assert attachment upload sends `FormData` without a JSON content type, list uses GET, and download uses `/attachments/{id}/download/`.

- [ ] **Step 2: Run the contract tests and verify methods are absent**

Run `npm.cmd test -- src/lib/ticket-contracts.test.ts` from `frontend`.

Expected: FAIL because the lifecycle methods and types do not exist.

- [ ] **Step 3: Add exact response types**

Add these central types:

```typescript
export interface TicketCapabilities {
  can_update_work_state: boolean;
  can_self_assign: boolean;
  self_assignee_id: string | null;
  can_reassign: boolean;
  can_change_confidentiality: boolean;
}

export interface AvailableTransition {
  to_status: string;
  label: string;
  requires_resolution: boolean;
  requires_reason: boolean;
}

export interface SlaClock {
  state: "not_started" | "running" | "paused" | "met" | "breached";
  due_at: string | null;
  remaining_seconds: number;
  overdue_seconds: number;
}

export interface AttachmentMetadata {
  id: string;
  filename: string;
  size_bytes: number;
  content_type: string;
  uploaded_by: string;
  uploaded_at: string;
  scan_status: "pending" | "clean" | "infected" | "error";
  download_available: boolean;
}

export interface ActivityItem {
  id: string;
  type: "message" | "internal_note" | "status_transition" | "work_state" | "attachment" | "relationship";
  occurred_at: string;
  actor: { subject: string; display_name: string } | null;
  visibility: "requester" | "internal";
  payload: Record<string, unknown>;
}
```

Extend `TicketDetail` with assignee detail, team, waiting/blocked reasons, next-action fields, `reopened_at`, `available_transitions`, `capabilities`, `sla_clocks`, relationships, attachments, and `updated_at`. Extend `TicketSummary` with `available_transition_codes`.

- [ ] **Step 4: Implement client methods and common error accessors**

Export `ApiError` and add:

```typescript
export interface ApiProblem {
  code: string;
  detail: string;
  fields: Record<string, string[]>;
  correlation_id: string;
}

export function apiProblem(error: unknown): ApiProblem | null {
  return error instanceof ApiError && isApiProblem(error.body) ? error.body : null;
}
```

Use the Task 1 request payloads verbatim. `attachmentsApi.upload` passes `body: FormData`; `attachmentsApi.download` returns `{url, filename, expires_in}`.

- [ ] **Step 5: Run tests, typecheck, and commit**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/lib/ticket-contracts.test.ts src/lib/api.test.ts
npm.cmd run typecheck
npm.cmd run lint
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/lib/api.ts frontend/src/lib/ticket-contracts.test.ts
git commit -m "feat(tickets): add lifecycle API client contracts"
```

---

### Task 2: Build the server-driven transition action bar

**Files:**
- Create: `frontend/src/features/tickets/TransitionActions.tsx`
- Create: `frontend/src/features/tickets/TransitionActions.test.tsx`
- Modify: `frontend/src/features/tickets/KanbanPage.tsx`
- Create: `frontend/src/features/tickets/KanbanPage.test.tsx`

**Interfaces:**
- Consumes: `TicketDetail.available_transitions`, `TicketDetail.updated_at`, and `ticketsApi.transition`.
- Produces: `TransitionActions({ticket, onUpdated})`.
- Updates Kanban to submit only a code present in `TicketSummary.available_transition_codes`.

- [ ] **Step 1: Write failing action-bar tests**

Render a ticket with `Start work`, `Wait on requester`, and `Resolve` transitions. Assert exactly those actions appear. Select Resolve and assert code/summary fields are required while reason is absent unless `requires_reason=true`. Submit and assert the mutation includes the current timestamp and all entered fields.

Add tests proving:

- no unavailable status appears;
- inputs and buttons remain disabled while pending;
- server field errors remain beside their fields and typed input remains intact;
- success calls `onUpdated(refreshedTicket)` and closes the dialog;
- `409 stale_ticket` renders “This ticket changed since you opened it” with a Reload button;
- unexpected errors show their correlation ID.

- [ ] **Step 2: Run the component test and verify it fails to import**

Run `npm.cmd test -- src/features/tickets/TransitionActions.test.tsx`.

Expected: FAIL because `TransitionActions` does not exist.

- [ ] **Step 3: Implement transition actions and conditional dialog**

Use the existing `Dialog`, `Button`, `Field`, `Input`, and `Textarea` components. Keep the chosen transition object in local state. Derive required controls only from its booleans. Validate non-empty resolution fields client-side for immediate feedback, but always surface backend field errors as authoritative.

Use a single mutation:

```typescript
const transition = useMutation({
  mutationFn: (values: TransitionValues) =>
    ticketsApi.transition(ticket.number, {
      ...values,
      updated_at: ticket.updated_at,
    }),
  onSuccess: onUpdated,
});
```

Do not mutate cached ticket data in `onMutate`.

- [ ] **Step 4: Write failing Kanban validity tests**

Assert dragging a ticket to an allowed code calls the API with the ticket timestamp. Dragging to a disallowed code does not call the API and shows “That transition is not available.” A pending mutation prevents another submission for the same ticket.

- [ ] **Step 5: Update Kanban to consume server transition codes**

Before mutation, check `ticket.available_transition_codes.includes(toColumn)`. Change the transition client call to the structured payload with `updated_at`. Keep backend rejection handling because authorization can change after rendering.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/features/tickets/TransitionActions.test.tsx src/features/tickets/KanbanPage.test.tsx
npm.cmd run typecheck
npm.cmd run lint
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/features/tickets/TransitionActions.tsx frontend/src/features/tickets/TransitionActions.test.tsx frontend/src/features/tickets/KanbanPage.tsx frontend/src/features/tickets/KanbanPage.test.tsx
git commit -m "feat(tickets): render server-approved transitions"
```

---

### Task 3: Build the operations and SLA panel

**Files:**
- Create: `frontend/src/features/tickets/OperationsPanel.tsx`
- Create: `frontend/src/features/tickets/OperationsPanel.test.tsx`
- Create: `frontend/src/features/tickets/SlaClocks.tsx`
- Create: `frontend/src/features/tickets/SlaClocks.test.tsx`

**Interfaces:**
- Consumes: ticket capabilities/work state, `ticketsApi.assignees`, and `ticketsApi.updateWorkState`.
- Produces: `OperationsPanel({ticket, onUpdated, onReload})` and `SlaClocks({clocks})`.

- [ ] **Step 1: Write failing capability-rendering tests**

Cover these states:

- unassigned agent with `can_self_assign=true` sees Self-assign but not an assignee selector;
- supervisor with `can_reassign=true` sees eligible assignee selection;
- agent cannot edit confidentiality;
- supervisor with `can_change_confidentiality=true` can edit it;
- auditor with `can_update_work_state=false` sees values as read-only;
- no client-side group parsing changes these decisions.

- [ ] **Step 2: Write failing work-state mutation tests**

Change team, waiting reason, blocked reason, next action, and next-action time, then assert one PATCH with changed values plus `updated_at`. Assert the form remains visible and disabled during submission, resets from the returned ticket on success, preserves values on `400`, and calls `onReload` only when the operator chooses Reload after `409`.

- [ ] **Step 3: Run operations tests and verify failure**

Run `npm.cmd test -- src/features/tickets/OperationsPanel.test.tsx`.

Expected: FAIL because the component does not exist.

- [ ] **Step 4: Implement operations panel**

Use a compact form initialized from ticket props. Track a dirty field map so the PATCH sends only changed fields plus `updated_at`. Fetch assignees only when `can_reassign` is true. Self-assignment sends the authenticated user's server-provided assignee identifier from a backend `self_assignee_id` capability value; do not infer a database UUID from the Keycloak subject.

Render common errors with field messages and correlation ID. Disable Save when nothing changed or a mutation is pending.

- [ ] **Step 5: Write and implement SLA display tests**

Assert each clock renders a label, semantic state, due timestamp when present, and a human duration derived only from `remaining_seconds`/`overdue_seconds`. A breached clock uses destructive styling and includes “overdue”; paused uses warning styling; screen-reader text names the clock and state.

`SlaClocks` must never derive due dates from ticket priority or current status.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/features/tickets/OperationsPanel.test.tsx src/features/tickets/SlaClocks.test.tsx
npm.cmd run typecheck
npm.cmd run lint
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/features/tickets/OperationsPanel.tsx frontend/src/features/tickets/OperationsPanel.test.tsx frontend/src/features/tickets/SlaClocks.tsx frontend/src/features/tickets/SlaClocks.test.tsx
git commit -m "feat(tickets): add operations and SLA controls"
```

---

### Task 4: Build unified activity with message and internal-note composition

**Files:**
- Create: `frontend/src/features/tickets/ActivityTimeline.tsx`
- Create: `frontend/src/features/tickets/ActivityTimeline.test.tsx`
- Create: `frontend/src/features/tickets/MessageComposer.tsx`
- Create: `frontend/src/features/tickets/MessageComposer.test.tsx`

**Interfaces:**
- Consumes: `ticketsApi.activity`, `ticketsApi.addMessage`, and `ticketsApi.addNote`.
- Produces: `ActivityTimeline({ticketNumber})` and `MessageComposer({ticketNumber, onCreated})`.

- [ ] **Step 1: Write failing typed-timeline tests**

Provide one item per supported type and assert:

- requester messages and internal notes are visually and textually distinct;
- transition payload displays from/to labels and reason;
- work-state payload displays changed labels without dumping raw JSON;
- attachments show scan state and relationship items link to their ticket number;
- actor display name and semantic `<time dateTime>` are present;
- empty, loading, permission, and unexpected-error states are distinct.

- [ ] **Step 2: Run timeline tests and verify failure**

Run `npm.cmd test -- src/features/tickets/ActivityTimeline.test.tsx`.

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement typed activity rendering**

Create a small renderer per item type in the same focused file. Use an exhaustive `switch` with a `never` guard so new activity types cause a TypeScript error until rendered intentionally. Display newest activity last, matching the backend's ascending order.

- [ ] **Step 4: Write failing composer tests**

Test two tabs/modes: Reply and Internal note. Assert an empty body cannot submit, pending disables duplicate sends, successful send clears only the submitted composer and calls `onCreated`, errors preserve body text, and internal note copy explicitly says it is not requester-visible.

- [ ] **Step 5: Implement non-optimistic composers**

Use separate local strings and mutations. On success, await `onCreated()` so the timeline refresh is requested before clearing the pending state. Display common-contract detail/correlation data when present.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/features/tickets/ActivityTimeline.test.tsx src/features/tickets/MessageComposer.test.tsx
npm.cmd run typecheck
npm.cmd run lint
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/features/tickets/ActivityTimeline.tsx frontend/src/features/tickets/ActivityTimeline.test.tsx frontend/src/features/tickets/MessageComposer.tsx frontend/src/features/tickets/MessageComposer.test.tsx
git commit -m "feat(tickets): add unified activity timeline"
```

---

### Task 5: Replace upload-only attachments with a safe file panel

**Files:**
- Modify: `frontend/src/features/tickets/AttachmentUploader.tsx`
- Create: `frontend/src/features/tickets/AttachmentUploader.test.tsx`

**Interfaces:**
- Consumes: `attachmentsApi.list`, `attachmentsApi.upload`, and `attachmentsApi.download`.
- Produces: one panel containing existing metadata, upload controls, scan state, and guarded downloads.

- [ ] **Step 1: Write failing attachment-panel tests**

Assert:

- existing files load independently of an upload;
- filename, formatted size, media type, uploader, date, and scan status render;
- only `download_available=true` renders a Download button;
- infected renders Quarantined, error renders Scan failed, and pending renders Scanning;
- upload keeps selected files on failure and clears them on success;
- successful upload invalidates/reloads attachment and activity queries;
- download requests a signed URL only when clicked and then calls `window.location.assign(url)`;
- permission errors render a permission state rather than suggesting a dev token.

- [ ] **Step 2: Run attachment tests and verify the upload-only component fails expectations**

Run `npm.cmd test -- src/features/tickets/AttachmentUploader.test.tsx`.

Expected: FAIL because existing metadata/download behavior and authenticated API wiring are absent.

- [ ] **Step 3: Refactor the panel around `attachmentsApi`**

Remove direct `fetch` and `DEV_AUTH_TOKEN` imports. Use one query for metadata, one upload mutation, and one download mutation keyed by attachment ID. Keep scan status visible after upload and refetch the canonical list.

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
Set-Location frontend
npm.cmd test -- src/features/tickets/AttachmentUploader.test.tsx
npm.cmd run typecheck
npm.cmd run lint
```

Expected: all commands exit 0.

Commit:

```powershell
git add frontend/src/features/tickets/AttachmentUploader.tsx frontend/src/features/tickets/AttachmentUploader.test.tsx
git commit -m "feat(files): show safe ticket attachments"
```

---

### Task 6: Integrate the complete ticket workspace

**Files:**
- Modify: `frontend/src/features/tickets/TicketDetailPage.tsx`
- Create: `frontend/src/features/tickets/TicketDetailPage.test.tsx`
- Modify: `frontend/src/features/tickets/TicketCard.tsx`

**Interfaces:**
- Consumes: all components produced by Tasks 2–5.
- Produces: coordinated ticket detail query, refreshed server state, queue return navigation, and responsive main/operations layout.

- [ ] **Step 1: Write failing integration tests**

Render populated detail and assert:

- ticket heading/status/priority/channel and Back to queue appear;
- the action bar contains server transitions;
- activity/composer occupy the main column;
- operations, SLA, relationships, and attachments occupy the context panel;
- a successful child mutation replaces cached detail with its returned ticket or invalidates exact ticket/activity queries;
- Back to queue restores the `returnTo` location when supplied, otherwise uses `/tickets`;
- `401`, `403`, `404`, loading, and unexpected errors render distinct states;
- mobile DOM order places primary action and activity before secondary operations.

- [ ] **Step 2: Run the integration test and verify current detail lacks lifecycle controls**

Run `npm.cmd test -- src/features/tickets/TicketDetailPage.test.tsx`.

Expected: FAIL on missing action, operations, SLA, and activity components.

- [ ] **Step 3: Recompose `TicketDetailPage`**

Use `queryClient.setQueryData(["ticket", number], updatedTicket)` only after a successful server response. Give activity and attachment children their own query invalidation keys. Preserve existing requester and description content. Replace separate message/note lists with `ActivityTimeline` and `MessageComposer`.

Use a single-column mobile layout and `lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]` on desktop. Keep the action bar directly beneath the ticket header.

- [ ] **Step 4: Preserve queue return context in cards**

In `TicketCard`, read the current location and pass it as route state:

```typescript
const location = useLocation();
const returnTo = `${location.pathname}${location.search}`;
<Link to={`/tickets/${ticket.number}`} state={{ returnTo }} />;
```

Ticket detail validates `location.state?.returnTo` begins with `/tickets` before using it.

- [ ] **Step 5: Run full frontend verification and commit**

Run:

```powershell
Set-Location frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

Expected: every command exits 0.

Commit:

```powershell
git add frontend/src/features/tickets/TicketDetailPage.tsx frontend/src/features/tickets/TicketDetailPage.test.tsx frontend/src/features/tickets/TicketCard.tsx
git commit -m "feat(tickets): deliver the operator workspace"
```

---

## Plan 3 Completion Gate

Run fresh frontend commands:

```powershell
Set-Location frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

Expected: every command exits 0. In a development browser, verify desktop and mobile ticket layouts; self-assignment; privileged reassignment; work-state validation; stale-write prompt; resolve/reopen; activity refresh; and clean/pending/infected attachment states.
