# Internal Staff Assignment and Custody UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give internal staff a searchable, confirm-before-submit assignment control with role-derived team context, an immediate authoritative success receipt, and a clearly categorised creation-to-closure custody timeline.

**Architecture:** Typed API contracts describe server-authoritative candidates, assignment receipts, and activity categories. A focused `AssignmentControl` owns candidate search, confirmation, mutation, cache synchronisation, and recoverable errors. `OperationsPanel` keeps non-ownership fields separate. The activity timeline renders public replies, internal notes, workflow events, and custody events as visually distinct typed records.

**Tech Stack:** React 18, TypeScript 5.6, Vite, TanStack Query 5, Base UI, shadcn components, Sonner, Vitest, Testing Library, ESLint

## Global Constraints

- Keep all new controls inside authenticated internal ticket detail. Do not expose staff names or assignment actions on public/requester pages.
- The server response is authoritative. Never infer target eligibility or assignment success from Keycloak roles in the browser.
- Always show a confirmation dialog before assignment, transfer, self-assignment, or unassignment.
- On success, replace the detail cache and visible ticket from the returned payload before invalidating dependent lists; no browser refresh is required.
- The success confirmation must identify ticket, previous assignee, new assignee, date/time, and performer.
- Make role/designation and derived team labels searchable and visible in candidate options.
- Preserve keyboard navigation, focus return, screen-reader labels, and reduced-motion conventions already used by the component library.
- Preserve unrelated working-tree changes and stage only the files listed by each task.

## Plan Boundary and Dependencies

This is Plan 3 of 3. It requires Plan 2's candidate, capability, assignment request, assignment response, and receipt contracts, and Plan 1's categorised activity response. It does not add public self-service features.

## File Structure

- `frontend/src/lib/api.ts`: owns assignment, candidate, capability, and activity TypeScript contracts and API methods.
- `frontend/src/lib/ticket-contracts.test.ts`: covers assignment route and payload contracts.
- `frontend/src/features/auth/AuthProvider.tsx`: recognises designation realm roles for authenticated navigation only.
- `frontend/src/features/auth/AuthProvider.test.tsx`: covers designation-token parsing without granting client-side authority.
- `frontend/src/components/ui/combobox.tsx`: provides the accessible searchable candidate primitive.
- `frontend/src/components/ui/combobox.test.tsx`: covers keyboard, search, selection, and empty states.
- `frontend/src/features/tickets/AssignmentControl.tsx`: owns assignment selection, confirmation, mutation, receipt, and error state.
- `frontend/src/features/tickets/AssignmentControl.test.tsx`: covers all assignment interaction requirements.
- `frontend/src/features/tickets/OperationsPanel.tsx`: composes assignment separately from work-state editing.
- `frontend/src/features/tickets/OperationsPanel.test.tsx`: protects non-assignment operations and capability display.
- `frontend/src/features/tickets/ActivityTimeline.tsx`: renders categorised custody and workflow history.
- `frontend/src/features/tickets/ActivityTimeline.test.tsx`: covers category distinctions and complete custody payloads.
- `frontend/src/features/tickets/TicketDetailPage.tsx`: synchronises detail/activity cache callbacks.
- `frontend/src/features/tickets/TicketDetailPage.test.tsx`: covers immediate visible owner updates.

---

### Task 1: Add exact frontend assignment and activity contracts

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/ticket-contracts.test.ts`
- Modify: `frontend/src/features/auth/AuthProvider.tsx`
- Modify: `frontend/src/features/auth/AuthProvider.test.tsx`

**Interfaces:**
- Extends: `TicketCapabilities` with `can_assign` and `self_assignee_detail` while retaining `can_reassign` and `self_assignee_id` during compatibility.
- Extends: `TicketAssignee` with `designations` and `team_labels`.
- Produces: `AssignmentRequest`, `AssignmentParty`, `AssignmentReceipt`, and `AssignmentResponse`.
- Extends: `ActivityItem` with category and custody-event type.

- [ ] **Step 1: Write failing contract tests**

In `ticket-contracts.test.ts`, assert:

```typescript
await ticketsApi.assignees("OP-202607-000001", "account");
expect(fetchMock).toHaveBeenLastCalledWith(
  expect.stringContaining(
    "/api/v1/tickets/OP-202607-000001/assignees/?search=account",
  ),
  expect.any(Object),
);

await ticketsApi.assign("OP-202607-000001", {
  assignee_id: "00000000-0000-0000-0000-000000000012",
  expected_updated_at: "2026-07-30T10:00:00Z",
  reason: "Transfer to finance review",
});
expect(fetchMock).toHaveBeenLastCalledWith(
  expect.stringContaining(
    "/api/v1/tickets/OP-202607-000001/assignment/",
  ),
  expect.objectContaining({ method: "POST" }),
);
```

Add auth tests showing each designation realm role is retained in the authenticated role set and permits normal authenticated app navigation, but does not create a client-computed ticket capability.

- [ ] **Step 2: Run focused tests in the red state**

```powershell
Set-Location frontend
npm test -- --run src/lib/ticket-contracts.test.ts src/features/auth/AuthProvider.test.tsx
```

Expected: assignment types/method and designation role recognition are missing.

- [ ] **Step 3: Add exact TypeScript contracts**

Add these public shapes:

```typescript
export interface AssignmentParty {
  id: string;
  display_name: string;
  designations: string[];
  team_labels: string[];
}

export interface AssignmentReceipt {
  ticket_number: string;
  action: "assigned" | "reassigned" | "unassigned" | "unchanged";
  previous_assignee: AssignmentParty | null;
  new_assignee: AssignmentParty | null;
  occurred_at: string;
  performed_by: {
    kind: "user" | "system";
    subject: string;
    display_name: string;
  };
}

export interface AssignmentRequest {
  assignee_id: string | null;
  expected_updated_at: string;
  reason?: string;
}

export interface AssignmentResponse {
  ticket: TicketDetail;
  receipt: AssignmentReceipt;
}
```

Add `can_assign: boolean` and `self_assignee_detail: TicketAssignee | null` to capabilities, and add `designations: string[]` plus `team_labels: string[]` to `TicketAssignee`. Extend `ActivityItem.type` with `custody_event`, and add:

```typescript
category:
  | "public_reply"
  | "internal_note"
  | "workflow"
  | "custody"
  | "attachment"
  | "relationship";
```

Implement `ticketsApi.assignees(number, search = "")` with `URLSearchParams` and `ticketsApi.assign(number, body)` as a POST returning `AssignmentResponse`.

- [ ] **Step 4: Recognise designation tokens for navigation only**

Add all eleven canonical role keys from Plan 2 to `KEYCLOAK_REALM_ROLES` and the authenticated operational-navigation set. Do not derive `can_assign`, office, service, queue, or confidentiality permissions from these client-side sets.

- [ ] **Step 5: Run contract, auth, type, and lint checks**

```powershell
Set-Location frontend
npm test -- --run src/lib/ticket-contracts.test.ts src/features/auth/AuthProvider.test.tsx
npm run typecheck
npm run lint -- --quiet
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit frontend contracts**

```powershell
git add frontend/src/lib/api.ts frontend/src/lib/ticket-contracts.test.ts frontend/src/features/auth/AuthProvider.tsx frontend/src/features/auth/AuthProvider.test.tsx
git diff --cached --check
git commit -m "feat(frontend): add assignment contracts"
```

---

### Task 2: Add an accessible searchable staff combobox

**Files:**
- Create: `frontend/src/components/ui/combobox.tsx`
- Create: `frontend/src/components/ui/combobox.test.tsx`

**Interfaces:**
- Produces: controlled `StaffCombobox` focused on `TicketAssignee` options.
- Emits: selected candidate ID or `null` for Unassigned.

- [ ] **Step 1: Write failing interaction tests**

Render options for an Accountant in Finance and an Estate Examiner in Estate Administration. Assert:

- the trigger exposes its accessible label and current value;
- ArrowDown/Enter selects an option;
- typing `finance`, `accountant`, or the person's name finds the Accountant;
- typing `estate administration` finds the Estate Examiner;
- the option renders the person's name as primary text and `Accountant · Finance` as supporting text;
- `Unassigned` remains a distinct option when `allowUnassigned` is true;
- an empty search shows `No eligible team members found`; and
- Escape closes the popup and returns focus to the trigger.

- [ ] **Step 2: Run the combobox test in the red state**

```powershell
Set-Location frontend
npm test -- --run src/components/ui/combobox.test.tsx
```

Expected: the component module is absent.

- [ ] **Step 3: Implement the controlled component**

Use the installed Base UI Combobox primitives and the project's button/input styling. The public prop contract is:

```typescript
interface StaffComboboxProps {
  id: string;
  label: string;
  value: string | null;
  options: TicketAssignee[];
  onValueChange: (value: string | null) => void;
  onSearchChange: (value: string) => void;
  allowUnassigned: boolean;
  disabled?: boolean;
  loading?: boolean;
  error?: string;
}
```

Build each option's searchable text from display name, username, all designations, and all team labels. Do not filter out server-returned results based on a browser role list. Keep the popup within the ticket panel's stacking context and constrain it to a scrollable height.

- [ ] **Step 4: Verify accessibility and component quality**

```powershell
Set-Location frontend
npm test -- --run src/components/ui/combobox.test.tsx
npm run typecheck
npm run lint -- --quiet
```

Expected: keyboard, focus, search, and empty-state tests pass.

- [ ] **Step 5: Commit the combobox**

```powershell
git add frontend/src/components/ui/combobox.tsx frontend/src/components/ui/combobox.test.tsx
git diff --cached --check
git commit -m "feat(frontend): add staff assignment combobox"
```

---

### Task 3: Build confirm-before-submit assignment control

**Files:**
- Create: `frontend/src/features/tickets/AssignmentControl.tsx`
- Create: `frontend/src/features/tickets/AssignmentControl.test.tsx`

**Interfaces:**
- Consumes: `TicketDetail`, candidate endpoint, assignment endpoint, and `StaffCombobox`.
- Emits: `onUpdated(ticket)`, `onActivityChanged()`, and a persistent in-panel receipt.

- [ ] **Step 1: Write failing capability, search, and confirmation tests**

Cover these behaviours:

1. when both `can_assign` and `can_self_assign` are false, render the current owner read-only and never fetch candidates;
2. when `can_assign` is true, fetch candidates and display names with designation/team context;
3. candidate search sends the debounced text to the API and ignores stale query results;
4. selecting another owner opens a dialog naming ticket, previous owner, and proposed owner;
5. reassignment and unassignment require a reason before Confirm enables;
6. initial assignment permits an optional reason;
7. Cancel makes no assignment request and returns focus;
8. double-clicking Confirm results in one request;
9. `can_self_assign` renders a Self-assign action from `self_assignee_detail`, uses the same confirmation dialog, and does not fetch the wider candidate directory when `can_assign` is false; and
10. a stale-ticket error shows Reload while keeping the proposed selection and reason.

- [ ] **Step 2: Run the new test in the red state**

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/AssignmentControl.test.tsx
```

Expected: the assignment control is absent.

- [ ] **Step 3: Implement selection and confirmation state**

The component contract is:

```typescript
interface AssignmentControlProps {
  ticket: TicketDetail;
  onUpdated: (ticket: TicketDetail) => void;
  onReload: () => void;
  onActivityChanged?: () => void | Promise<void>;
}
```

Fetch candidates only when `ticket.capabilities.can_assign` is true. Use a 250 ms debounced search value in the query key `['ticket', ticket.number, 'assignees', debouncedSearch]`. Maintain `selectedId`, `reason`, and the selected candidate snapshot locally until confirmation or cancellation. When only `can_self_assign` is true, build the proposed selection exclusively from the server-returned `self_assignee_detail` and never call the candidates endpoint.

Use the existing Dialog component. The dialog title is `Confirm ticket assignment`. Its body explicitly states:

```text
Ticket: {ticket.number}
Previous assignee: {current name or Unassigned}
New assignee: {selected name or Unassigned}
```

Label the textarea `Reason for transfer`; require a trimmed value for reassignment and unassignment. The button label reflects `Assign`, `Transfer`, or `Unassign`, and becomes `Assigning…`, `Transferring…`, or `Unassigning…` while pending.

- [ ] **Step 4: Submit exactly one authoritative mutation**

Call:

```typescript
ticketsApi.assign(ticket.number, {
  assignee_id: selectedId,
  expected_updated_at: ticket.updated_at,
  reason: reason.trim(),
});
```

Disable every assignment interaction while pending. On API validation error, keep the dialog open and render structured field errors. On 409, close no state and show Reload. On 403, discard the candidate selection after showing that permission or eligibility changed.

- [ ] **Step 5: Render the authoritative receipt**

On success, call `onUpdated(response.ticket)` before any invalidation, close the dialog, and render a persistent `role="status"` receipt inside the panel using only `response.receipt`:

```text
{ticket_number} {action}: {previous name or Unassigned} → {new name or Unassigned} on {local date/time} by {performed_by.display_name}.
```

Also send the same concise summary through Sonner. Await `onActivityChanged` so the custody timeline includes the new record promptly.

- [ ] **Step 6: Run focused assignment UI checks**

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/AssignmentControl.test.tsx src/components/ui/combobox.test.tsx
npm run typecheck
npm run lint -- --quiet
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit the assignment control**

```powershell
git add frontend/src/features/tickets/AssignmentControl.tsx frontend/src/features/tickets/AssignmentControl.test.tsx
git diff --cached --check
git commit -m "feat(frontend): confirm internal ticket assignments"
```

---

### Task 4: Separate assignment from generic operations and update immediately

**Files:**
- Modify: `frontend/src/features/tickets/OperationsPanel.tsx`
- Modify: `frontend/src/features/tickets/OperationsPanel.test.tsx`
- Modify: `frontend/src/features/tickets/TicketDetailPage.tsx`
- Modify: `frontend/src/features/tickets/TicketDetailPage.test.tsx`

**Interfaces:**
- `OperationsPanel` composes `AssignmentControl` above non-ownership work-state fields.
- `TicketDetailPage` updates its exact ticket query synchronously and invalidates dependent views after success.

- [ ] **Step 1: Write failing separation and cache tests**

Assert that OperationsPanel no longer includes `assignee` in `TicketWorkStateUpdate`, no longer fetches candidates itself, and renders `AssignmentControl` for the assignment area. Retain existing tests for team, waiting reason, blocked reason, next action, next-action time, and confidentiality.

At the page level, seed the ticket cache with Assignee A, resolve an assignment mutation with Assignee B, and assert Assignee B is visible immediately without clicking Reload and before any refetch promise resolves. Assert list, Kanban, dashboard, candidate, and activity queries are invalidated after the exact detail cache is replaced.

- [ ] **Step 2: Run panel and page tests in the red state**

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/OperationsPanel.test.tsx src/features/tickets/TicketDetailPage.test.tsx
```

Expected: OperationsPanel still owns assignment and sends assignee through work state.

- [ ] **Step 3: Refactor OperationsPanel**

Remove `assignee` from `FormValues`, `EditableField`, `valuesFromTicket`, submit mapping, candidate query, and self-assignment mutation. Compose:

```tsx
<AssignmentControl
  ticket={ticket}
  onUpdated={onUpdated}
  onReload={onReload}
  onActivityChanged={onActivityChanged}
/>
```

Keep non-assignment dirty tracking and errors unchanged. Update the operations introduction to say `Ownership and the next planned action` only if the assignment control is nested under the same heading; otherwise give Assignment its own visible heading.

- [ ] **Step 4: Replace and invalidate caches in the correct order**

In the page's `onUpdated`, first call:

```typescript
queryClient.setQueryData(["ticket", updated.number], updated);
```

Then update visible component state through the existing detail query. Invalidate these prefixes after replacement:

```typescript
["tickets"]
["kanban"]
["dashboard"]
["ticket", updated.number, "assignees"]
["ticket-activity", updated.number]
```

Do not await a detail refetch before showing the new owner.

- [ ] **Step 5: Run UI integration and regressions**

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/AssignmentControl.test.tsx src/features/tickets/OperationsPanel.test.tsx src/features/tickets/TicketDetailPage.test.tsx
npm run typecheck
npm run lint -- --quiet
```

Expected: all commands exit 0 and the new assignee is visible synchronously.

- [ ] **Step 6: Commit operations integration**

```powershell
git add frontend/src/features/tickets/OperationsPanel.tsx frontend/src/features/tickets/OperationsPanel.test.tsx frontend/src/features/tickets/TicketDetailPage.tsx frontend/src/features/tickets/TicketDetailPage.test.tsx
git diff --cached --check
git commit -m "refactor(frontend): separate assignment operations"
```

---

### Task 5: Render complete categorised custody history

**Files:**
- Modify: `frontend/src/features/tickets/ActivityTimeline.tsx`
- Modify: `frontend/src/features/tickets/ActivityTimeline.test.tsx`
- Modify: `frontend/src/features/tickets/TicketDetailPage.test.tsx`

**Interfaces:**
- Consumes: Plan 1 activity categories and `custody_event` payload.
- Produces: visibly distinct public reply, internal note, workflow, and custody cards.

- [ ] **Step 1: Write the failing full-timeline test**

Create chronological activity fixtures containing public reply, internal note, creation, assignment, reassignment, unassignment, queue change, escalation, status change, reopening, and closure. Assert every item renders in API order and that:

- public reply says `Visible to requester`;
- internal note says `Internal only`;
- status/reopen/close records say `Workflow`;
- custody records say `Chain of custody`;
- owner events render previous and new person or `Unassigned`;
- queue events render previous and new queue or `Not set`;
- all custody records render actor, local date/time, and reason when supplied; and
- created, escalated, reopened, and closed are each distinguishable by action label.

- [ ] **Step 2: Run timeline tests in the red state**

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/ActivityTimeline.test.tsx src/features/tickets/TicketDetailPage.test.tsx
```

Expected: category and custody-event cases are unsupported.

- [ ] **Step 3: Add typed custody payload parsing**

Extend `ActivityPayloads` with:

```typescript
custody_event: {
  action: string;
  previous_owner: AssignmentParty | null;
  new_owner: AssignmentParty | null;
  previous_queue: { id: string; label: string } | null;
  new_queue: { id: string; label: string } | null;
  previous_status: { code: string; label: string } | null;
  new_status: { code: string; label: string } | null;
  actor_kind: "user" | "system";
  source_process: string;
  reason: string;
};
```

Use safe record/string/array parsers for every server payload. Preserve exhaustive `assertNever` checks so a new event type cannot silently disappear.

- [ ] **Step 4: Render categories and custody actions**

Add an explicit category badge/header to every frame. Keep public replies sky, internal notes amber, workflow primary, and custody emerald/slate with text labels so colour is not the only distinction. The custody card renders action, previous/new owner or queue, actor kind/process when system-generated, reason, and timestamp.

For status events backed by custody, keep the existing `status_transition` presentation and mark it `Workflow`; do not render a second custody card for the same transition.

- [ ] **Step 5: Run activity and accessibility checks**

```powershell
Set-Location frontend
npm test -- --run src/features/tickets/ActivityTimeline.test.tsx src/features/tickets/TicketDetailPage.test.tsx
npm run typecheck
npm run lint -- --quiet
```

Expected: all commands exit 0 with a complete chronological creation-to-closure presentation.

- [ ] **Step 6: Commit the custody timeline UI**

```powershell
git add frontend/src/features/tickets/ActivityTimeline.tsx frontend/src/features/tickets/ActivityTimeline.test.tsx frontend/src/features/tickets/TicketDetailPage.test.tsx
git diff --cached --check
git commit -m "feat(frontend): render ticket custody timeline"
```

---

### Task 6: Run end-to-end role and regression verification

**Files:**
- Modify only if a failing test exposes a defect in files already listed by Plans 1–3.

- [ ] **Step 1: Run the full frontend suite**

```powershell
Set-Location frontend
npm test
npm run typecheck
npm run lint
npm run build
```

Expected: every command exits 0.

- [ ] **Step 2: Run the full backend suite**

```powershell
Set-Location backend
pytest -q
ruff check .
mypy apps
python manage.py makemigrations --check --dry-run
python manage.py check
```

Expected: every command exits 0.

- [ ] **Step 3: Run repository verification**

From the repository root:

```powershell
make verify
```

Expected: backend, frontend, migration, lint, type, test, and build checks all exit 0.

- [ ] **Step 4: Perform the internal role acceptance matrix**

For Master, Deputy Master, Assistant Master, Assistant Accountant, Accountant, Senior Accountant, Principal Accountant, Financial Controller, Estate Examiner, Records Clerk, and Data Clerk, verify one allowed exact-scope assignment and one denied mismatched-scope assignment. Also verify supervisor, IT lead, auditor, inactive staff, expired role, and automation rows from the permission matrix.

For one successful transfer, verify the page immediately shows the new assignee and the receipt includes ticket, previous assignee, new assignee, time, and performer. Verify the activity stream shows creation through closure with public reply, internal note, workflow, and custody distinctions.

- [ ] **Step 5: Inspect the final diff and working tree**

```powershell
git diff --check
git status --short
git log --oneline --decorate -15
```

Expected: no whitespace errors, implementation commits are ordered by the three plans, and unrelated pre-existing user changes remain unstaged.

## Plan 3 Completion Gate

The feature is complete only when fresh results show:

- all eleven primary internal designations pass allowed and denied eligibility cases;
- direct API calls cannot assign an ineligible user;
- every assignment interaction requires confirmation;
- a successful assignment updates the visible owner without refresh and renders the authoritative receipt;
- every supported custody event appears once in chronological activity;
- public replies, internal notes, workflow events, and custody events are visibly and semantically distinct; and
- full backend, frontend, migration, lint, typecheck, test, and build commands pass.
