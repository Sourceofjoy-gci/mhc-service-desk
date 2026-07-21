# Shadcn UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade all ten Vite/React routes to a cohesive, accessible navy-and-gold shadcn interface without changing behavior, routes, API calls, or domain workflows.

**Architecture:** Retain the existing React Router, TanStack Query, Base UI–backed `base-nova` shadcn setup, and feature-page boundaries. First complete the semantic token and primitive layer, then migrate page groups from custom markup to shared shadcn compositions, with typecheck/build and browser verification after every independently reviewable group.

**Tech Stack:** React 18, TypeScript 5.6, Vite 5, Tailwind CSS 4, shadcn/ui `base-nova`, Base UI, Lucide React, TanStack Query, React Router 6, dnd-kit, Sonner.

## Global Constraints

- Preserve the current navy-and-gold civic identity.
- Keep all behavior, API contracts, route paths, query keys, mutations, redirects, and domain workflows unchanged.
- Use semantic OKLCH tokens and avoid raw Tailwind color families in feature code.
- Use Geist Variable as the only interface typeface.
- Use a four-pixel spacing grid, 16px mobile gutters, 24px desktop gutters, and a 10px base radius.
- Use Base UI shadcn APIs (`render`, Base Select `items`) rather than Radix-only APIs.
- Use Lucide icons; icons inside shadcn components use `data-icon` and no manual size classes.
- Use `FieldGroup`/`Field` for forms, `SelectGroup` for select items, `Alert` for callouts, `Empty` for empty states, `Skeleton` for loading, `Badge` for status, `Spinner` for pending actions, and Sonner for transient mutation feedback.
- Use `cn()` for conditional classes and `gap-*` rather than `space-*` utilities.
- Do not stage or commit unrelated existing backend, log, conversion, or workspace changes.

## File Map

- `frontend/src/index.css`: semantic tokens, typography, global focus, motion, and layout utilities.
- `frontend/src/main.tsx`: application providers and global Toaster.
- `frontend/src/components/ui/{alert,empty,field,spinner,table}.tsx`: official shadcn primitives added through the CLI.
- `frontend/src/components/ui/sonner.tsx`: bridge Sonner to the existing custom theme provider.
- `frontend/src/components/app-shell.tsx`: shared application navigation, page frame, and responsive shell.
- `frontend/src/components/{brand,domain-badges}.tsx`: shared civic identity and operational status vocabulary.
- `frontend/src/features/home/HomePage.tsx`: platform overview and entry points.
- `frontend/src/features/tickets/{QueuePage,KanbanPage,TicketCard,TicketDetailPage,AttachmentUploader,ChannelIntakePage}.tsx`: operational ticket workflows.
- `frontend/src/features/reports/DashboardPage.tsx`: operational metrics and breakdown tables.
- `frontend/src/features/public/PublicFormPage.tsx`: requester-facing submission form.
- `frontend/src/features/{auth/LoginPage,health/HealthPage}.tsx`: authentication and dependency health.

---

### Task 1: Semantic foundation and official primitives

**Files:**
- Create: `frontend/src/components/ui/alert.tsx`
- Create: `frontend/src/components/ui/empty.tsx`
- Create: `frontend/src/components/ui/field.tsx`
- Create: `frontend/src/components/ui/spinner.tsx`
- Create: `frontend/src/components/ui/table.tsx`
- Modify: `frontend/src/components/ui/sonner.tsx`
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Consumes: current `base-nova` component configuration, `@/lib/utils`, custom `ThemeProvider`.
- Produces: `Alert*`, `Empty*`, `Field*`, `Spinner`, `Table*`, and a theme-aware global `<Toaster />` for all later tasks.

- [ ] **Step 1: Inspect component APIs before adding them**

Run:

```powershell
cd frontend
npx.cmd shadcn@latest docs alert empty field spinner table sonner
npx.cmd shadcn@latest add alert empty field spinner table --dry-run
```

Expected: official documentation URLs and a dry-run listing only the five new UI component files plus required dependencies.

- [ ] **Step 2: Add the missing official primitives**

Run:

```powershell
npx.cmd shadcn@latest add alert empty field spinner table
```

Expected: the five files exist under `frontend/src/components/ui`; no existing customized component is overwritten.

- [ ] **Step 3: Review generated components against Base UI rules**

Read every generated file and confirm imports use `@/`, icons use `lucide-react`, and no Radix-only `asChild` APIs appear.

Run:

```powershell
rg -n "asChild|space-[xy]-|bg-(blue|gray|red|green|amber)-|text-(blue|gray|red|green|amber)-" src/components/ui/alert.tsx src/components/ui/empty.tsx src/components/ui/field.tsx src/components/ui/spinner.tsx src/components/ui/table.tsx
```

Expected: no project-rule violations.

- [ ] **Step 4: Connect Sonner to the existing theme context**

Replace `next-themes` usage in `src/components/ui/sonner.tsx` with the project provider:

```tsx
import { useTheme } from "@/components/theme-provider"

const Toaster = ({ ...props }: ToasterProps) => {
  const { resolvedTheme } = useTheme()
  return <Sonner theme={resolvedTheme} {...props} />
}
```

Keep the semantic popover variables, official icons, and existing `ToasterProps` forwarding.

- [ ] **Step 5: Mount global feedback and normalize global motion**

Add `<Toaster richColors={false} position="top-right" />` inside `ThemeProvider`, after the router, in `src/main.tsx`. Add reduced-motion handling and a reusable page-heading rhythm in `src/index.css`:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

Do not change route layout or component behavior in this task.

- [ ] **Step 6: Verify and commit the foundation**

Run:

```powershell
npm.cmd run typecheck
npm.cmd run build
```

Expected: both commands exit 0.

Commit only Task 1 files:

```powershell
git add frontend/src/components/ui/alert.tsx frontend/src/components/ui/empty.tsx frontend/src/components/ui/field.tsx frontend/src/components/ui/spinner.tsx frontend/src/components/ui/table.tsx frontend/src/components/ui/sonner.tsx frontend/src/index.css frontend/src/main.tsx frontend/package.json frontend/package-lock.json
git commit -m "chore(ui): complete semantic component foundation"
```

---

### Task 2: Shared shell, home, and ticket vocabulary

**Files:**
- Modify: `frontend/src/components/app-shell.tsx`
- Modify: `frontend/src/components/brand.tsx`
- Modify: `frontend/src/components/domain-badges.tsx`
- Modify: `frontend/src/features/home/HomePage.tsx`
- Modify: `frontend/src/features/tickets/TicketCard.tsx`

**Interfaces:**
- Consumes: Task 1 semantic tokens and primitives.
- Produces: consistent application frame, page-entry hierarchy, operational badges, and reusable ticket surface for Queue and Kanban.

- [ ] **Step 1: Normalize shell semantics and responsive navigation**

Keep every existing `to` destination and active-route rule. Use one `nav` label per group, semantic token styling, touch-safe mobile links, and no manual icon sizing inside shadcn components. Preserve the current footer content and route fade.

Representative active-link composition:

```tsx
return cn(
  "inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-sm transition-colors",
  "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
  active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/70 hover:text-foreground",
)
```

- [ ] **Step 2: Restrain the home composition**

Keep the health query, route links, and copy. Reduce nested decorative card treatment, preserve the navy/gold hero, use complete Card composition where cards represent an interaction, and apply `data-icon` to icons inside Button/Badge.

- [ ] **Step 3: Normalize shared operational badges**

Keep existing public props and labels. Remove `any` casts by defining exact status/priority/SLA unions, preserve semantic token variants, and keep `Badge` as the rendered primitive.

```tsx
type PriorityCode = "P1" | "P2" | "P3" | "P4"
type SlaState = "on_track" | "at_risk" | "breached" | "paused" | "none"
```

- [ ] **Step 4: Refine TicketCard without changing navigation**

Retain the `/tickets/${ticket.number}` link, draggable attributes, all ticket metadata, and current shared badges. Use a full Card header/content structure, one restrained hover lift, and semantic `<time>`/metadata labels where values permit.

- [ ] **Step 5: Verify and commit shared surfaces**

Run `npm.cmd run typecheck`, `npm.cmd run lint`, and `npm.cmd run build`; all must exit 0.

Commit:

```powershell
git add frontend/src/components/app-shell.tsx frontend/src/components/brand.tsx frontend/src/components/domain-badges.tsx frontend/src/features/home/HomePage.tsx frontend/src/features/tickets/TicketCard.tsx
git commit -m "feat(ui): refine shared civic application surfaces"
```

---

### Task 3: Queue and Kanban workspaces

**Files:**
- Modify: `frontend/src/features/tickets/QueuePage.tsx`
- Modify: `frontend/src/features/tickets/KanbanPage.tsx`

**Interfaces:**
- Consumes: Task 1 `Alert`, `Empty`, `Field`, `Select`, `Skeleton`; Task 2 `TicketCard` and domain badges.
- Produces: consistent list and board workspaces with the existing query/mutation contracts intact.

- [ ] **Step 1: Recompose Queue filters**

Retain state, query parameters, sorting, clear behavior, and refresh. Use `Field` with a visually hidden `FieldLabel` for search and selects. Wrap each set of `SelectItem` nodes in `SelectGroup`; replace general `Separator` nodes inside selects with `SelectSeparator`.

```tsx
<SelectContent>
  <SelectGroup>
    {STATUS_OPTIONS.map((status) => (
      <SelectItem key={status.value} value={status.value}>{status.label}</SelectItem>
    ))}
  </SelectGroup>
</SelectContent>
```

- [ ] **Step 2: Replace Queue state markup**

Use `Alert` for fetch failure, `Empty` for zero results, and the existing Card/Skeleton grid for loading. Keep retry and clear-filter callbacks unchanged.

- [ ] **Step 3: Recompose Kanban controls and columns**

Retain `DndContext`, sensors, IDs, transition mutation, column order, and viewport-height scrolling. Replace native `<select>` with Base UI `Select` and an `items` array. Replace custom count pills with `Badge`, errors with `Alert`, loading text with Skeletons, and empty column copy with the compact `Empty` composition.

- [ ] **Step 4: Add non-color drag feedback and Sonner mutation errors**

Use `cn()` for over/drag states and include ring/scale/opacity cues. Call `toast.error("Ticket transition failed")` from the existing mutation error path while retaining an inline Alert for persistent context.

- [ ] **Step 5: Verify and commit ticket workspaces**

Run typecheck, lint, and build; expect exit 0. In a browser, verify `/tickets` and `/kanban` at 390px and 1440px, including keyboard focus and horizontal Kanban scrolling.

Commit:

```powershell
git add frontend/src/features/tickets/QueuePage.tsx frontend/src/features/tickets/KanbanPage.tsx
git commit -m "feat(ui): modernize queue and kanban workspaces"
```

---

### Task 4: Operational dashboard

**Files:**
- Modify: `frontend/src/features/reports/DashboardPage.tsx`

**Interfaces:**
- Consumes: `ticketsApi.dashboard()`, Task 1 Card/Table/Alert/Empty/Skeleton primitives, domain badges.
- Produces: responsive metric summary and priority/status tables without changing polling or data shape.

- [ ] **Step 1: Preserve data flow and add full state surfaces**

Keep `queryKey: ["dashboard"]`, `ticketsApi.dashboard()`, and the 30-second refetch interval. Render a composed Skeleton layout while loading, Alert on error, and Empty only when all returned breakdowns contain no rows.

- [ ] **Step 2: Compose metric Cards**

Use `CardHeader`, `CardDescription`, and `CardContent` for each metric. Use `text-destructive` only when `breached_sla > 0`; use tabular numerals for values.

- [ ] **Step 3: Replace custom lists with responsive Tables**

```tsx
<Table>
  <TableHeader><TableRow><TableHead>Status</TableHead><TableHead className="text-right">Tickets</TableHead></TableRow></TableHeader>
  <TableBody>
    {d.by_status.map((row) => (
      <TableRow key={row.status__code}>
        <TableCell>{row.status__name}</TableCell>
        <TableCell className="text-right tabular-nums">{row.count}</TableCell>
      </TableRow>
    ))}
  </TableBody>
</Table>
```

Use `PriorityBadge`/`StatusBadge` where the API provides known codes; preserve exact counts and labels.

- [ ] **Step 4: Verify and commit dashboard**

Run typecheck, lint, and build; inspect `/dashboard` at mobile and desktop widths in light/dark mode.

Commit:

```powershell
git add frontend/src/features/reports/DashboardPage.tsx
git commit -m "feat(ui): elevate operational dashboard"
```

---

### Task 5: Ticket detail and attachments

**Files:**
- Modify: `frontend/src/features/tickets/TicketDetailPage.tsx`
- Modify: `frontend/src/features/tickets/AttachmentUploader.tsx`

**Interfaces:**
- Consumes: existing ticket query/mutations/upload function and Task 1 feedback/form primitives.
- Produces: accessible detail workspace, reply/note composers, metadata rail, and attachment scan presentation.

- [ ] **Step 1: Recompose loading/error/header states**

Use Skeleton for loading and Alert with the existing queue link for failure. Preserve ticket number/title/requester/classification/description. Use `StatusBadge`, `PriorityBadge`, and `ChannelBadge` rather than custom pills.

- [ ] **Step 2: Recompose the conversation and notes**

Keep message/note ordering, timestamps, text, mutation calls, reset callbacks, and query invalidation. Use Card sections, semantic lists, `Field`/`FieldLabel`/`Textarea`, and Button + Spinner pending composition:

```tsx
<Button disabled={!reply.trim() || addMessage.isPending} onClick={() => addMessage.mutate(reply)}>
  {addMessage.isPending ? <Spinner data-icon="inline-start" /> : <Send data-icon="inline-start" />}
  {addMessage.isPending ? "Sending…" : "Send reply"}
</Button>
```

- [ ] **Step 3: Recompose requester/classification metadata**

Use semantic `<aside>`, complete Cards, and `<dl>` rows with consistent separators. Do not hide any optional requester or matter-reference fields that currently render.

- [ ] **Step 4: Upgrade AttachmentUploader**

Keep the native file input behavior, request URL, auth header, FormData field name, result ordering, and scan data. Wrap input in `Field`, use Button + Spinner, Alert for upload error, Badge for scan status, and Sonner success feedback after the existing `setFiles([])` callback.

- [ ] **Step 5: Verify and commit ticket detail**

Run typecheck, lint, and build. Inspect `/tickets/:number` populated, empty-message, pending, upload-result, and error states where the backend permits.

Commit:

```powershell
git add frontend/src/features/tickets/TicketDetailPage.tsx frontend/src/features/tickets/AttachmentUploader.tsx
git commit -m "feat(ui): rebuild ticket detail workspace"
```

---

### Task 6: Agent intake and public submission forms

**Files:**
- Modify: `frontend/src/features/tickets/ChannelIntakePage.tsx`
- Modify: `frontend/src/features/public/PublicFormPage.tsx`

**Interfaces:**
- Consumes: existing local form state, validation, ticket mutations, route state, and Task 1 Field/Alert/Spinner primitives.
- Produces: consistent accessible internal and public form experiences for `/intake/call`, `/intake/walk-in`, and `/public`.

- [ ] **Step 1: Convert ChannelIntakePage to Field composition**

Keep every input name, state setter, submission payload, query/mutation, route-derived channel, success link, and reset action. Replace raw layout wrappers with `FieldGroup`/`Field`; set `data-invalid` and `aria-invalid` together when existing validation fails. Wrap all select options in `SelectGroup`.

- [ ] **Step 2: Normalize intake feedback**

Use Alert for submission failure, Button + Spinner for pending, and the existing success Card/link destination. Preserve call/walk-in titles and descriptions from `App.tsx`.

- [ ] **Step 3: Convert PublicFormPage to Field composition**

Keep all requester fields, service selections, consent state, mutation payload, validation messages, completion state, and links. Use `FieldSet`/`FieldLegend` for consent or related option groups, semantic validation attributes, and complete Card sections.

- [ ] **Step 4: Verify and commit forms**

Run typecheck, lint, and build. Inspect all three routes at 390px/768px/1440px; keyboard through every field and verify visible labels, validation, disabled/pending states, and successful submission presentation.

Commit:

```powershell
git add frontend/src/features/tickets/ChannelIntakePage.tsx frontend/src/features/public/PublicFormPage.tsx
git commit -m "feat(ui): standardize ticket intake forms"
```

---

### Task 7: Login and system health

**Files:**
- Modify: `frontend/src/features/auth/LoginPage.tsx`
- Modify: `frontend/src/features/health/HealthPage.tsx`

**Interfaces:**
- Consumes: existing Keycloak lifecycle, health query, and Task 1 Alert/Spinner/Skeleton primitives.
- Produces: consistent authentication and operational health pages without authentication or polling changes.

- [ ] **Step 1: Normalize LoginPage states**

Keep `initKeycloak`, login/logout redirect URIs, profile fields, expiry display, and retry state. Keep the existing Skeleton during Keycloak initialization, use Alert for unreachable and signed-in states, and use complete Card composition with semantic icon treatment.

- [ ] **Step 2: Normalize HealthPage states**

Keep `/api/v1/health`, query keys, 15-second interval, refresh control, dependency labels, latency values, version, and environment. Use Alert for failure/degradation, semantic Badge variants for checks, and consistent Card header/content structure.

- [ ] **Step 3: Verify and commit utility routes**

Run typecheck, lint, and build. Inspect `/login` and `/health` in light/dark modes at mobile and desktop widths.

Commit:

```powershell
git add frontend/src/features/auth/LoginPage.tsx frontend/src/features/health/HealthPage.tsx
git commit -m "feat(ui): polish login and system health"
```

---

### Task 8: Full-route visual and accessibility verification

**Files:**
- Modify: only frontend files requiring verified corrective fixes.

**Interfaces:**
- Consumes: Tasks 1–7 completed UI.
- Produces: verified rendering across all ten routes and a final audit with no legacy style violations.

- [ ] **Step 1: Run static verification**

```powershell
cd frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run build
```

Expected: all commands exit 0. If `npm.cmd test` reports no test files as a non-zero configuration result, record that explicitly and rely on typecheck/build plus route QA; do not fabricate tests unrelated to behavior.

- [ ] **Step 2: Run legacy-pattern audit**

```powershell
rg -n "ink-|brand-|space-[xy]-|<button|<select|<textarea|bg-(white|red|green|amber|blue)-|text-(red|green|amber|blue)-" src/features src/components
```

Expected: no feature-level legacy palette, raw interactive controls except intentional native file input, or spacing-rule violations.

- [ ] **Step 3: Verify all routes in the browser**

Visit `/`, `/tickets`, one `/tickets/:number`, `/kanban`, `/dashboard`, `/intake/call`, `/intake/walk-in`, `/public`, `/health`, and `/login` at 390×844 and 1440×900. Repeat representative home, form, dashboard, and ticket-detail pages in dark mode. Check console errors, overflow, focus visibility, semantic labels, loading/error/empty states, and unchanged navigation/mutations.

- [ ] **Step 4: Apply and verify corrective fixes**

For every observed issue, make the smallest UI-only correction in the owning page, rerun typecheck/build, and re-open that route at the failing viewport.

- [ ] **Step 5: Commit verification fixes if needed**

```powershell
git add -- frontend/src/index.css frontend/src/main.tsx frontend/src/components/app-shell.tsx frontend/src/components/brand.tsx frontend/src/components/domain-badges.tsx frontend/src/components/ui/sonner.tsx frontend/src/features/home/HomePage.tsx frontend/src/features/tickets/QueuePage.tsx frontend/src/features/tickets/KanbanPage.tsx frontend/src/features/tickets/TicketCard.tsx frontend/src/features/reports/DashboardPage.tsx frontend/src/features/tickets/TicketDetailPage.tsx frontend/src/features/tickets/AttachmentUploader.tsx frontend/src/features/tickets/ChannelIntakePage.tsx frontend/src/features/public/PublicFormPage.tsx frontend/src/features/auth/LoginPage.tsx frontend/src/features/health/HealthPage.tsx
git commit -m "fix(ui): resolve cross-route visual regressions"
```

If no corrective changes are needed, do not create an empty commit.
