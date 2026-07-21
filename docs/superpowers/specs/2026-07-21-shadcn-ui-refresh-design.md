# Shadcn UI Refresh Design

## Objective

Elevate every frontend route into a cohesive, production-grade civic operations interface while preserving all existing behavior, API contracts, routes, and domain workflows.

## Visual Thesis

Calm civic operations: cool neutral surfaces establish clarity, deep navy communicates authority and primary action, and warm gold appears sparingly as an institutional accent. The interface should feel precise, trustworthy, and contemporary rather than decorative.

## Design System

### Color

- Keep all colors behind semantic OKLCH tokens in `frontend/src/index.css`.
- Use navy for `primary`, focus, active navigation, and primary actions.
- Use gold only for brand details and carefully selected institutional emphasis.
- Use semantic `success`, `warning`, `info`, and `destructive` tokens for operational states.
- Use cool neutral `background`, `card`, `muted`, `accent`, `border`, and sidebar tokens.
- Maintain equivalent light and dark themes without component-level `dark:` color overrides.

### Typography

- Retain Geist Variable as the sole interface typeface.
- Display/hero: 36/44 to 48/52 depending on viewport.
- Page title: 24/32, semibold.
- Section title: 16/24 to 20/28, semibold.
- Body/control: 14/20.
- Caption/metadata: 12/16.
- Use tabular or monospaced numerals only for ticket numbers, measurements, and counts.

### Spacing, Radius, and Elevation

- Use a four-pixel spacing grid.
- Use 16px mobile and 24px desktop page gutters.
- Use 24px between major page sections, 16px within sections, and 8–12px within control groups.
- Keep the global radius at 10px; derive component radii from the shadcn token.
- Prefer borders and surface contrast; reserve subtle shadows for overlays and interactive hover elevation.

### Interaction and Accessibility

- Preserve the restrained route fade.
- Use fast, consistent hover and pressed transitions for interactive surfaces.
- Make drag-over state obvious without relying on color alone.
- Preserve keyboard drag support and add clear focus-visible treatment everywhere.
- Use semantic landmarks, headings, lists, tables, labels, fieldsets, and live feedback.
- Respect reduced-motion preferences.

## Route and Component Audit

| Route | Existing UI | Upgrade direction |
| --- | --- | --- |
| `/` | Card, Badge, Button, Skeleton, Brand | Simplify chrome, strengthen hierarchy, normalize tokens and icon composition. |
| `/tickets` | Card, Input, Select, Button, Badge, Skeleton, TicketCard | Standardize filters, grouped Select content, Empty and Alert states, responsive ticket grid. |
| `/tickets/:number` | Custom cards, raw textarea/buttons, AttachmentUploader | Card composition, Field/Textarea/Button, Badge, Alert, Empty, Spinner, and semantic metadata. |
| `/kanban` | dnd-kit, TicketCard, native select, custom columns | Select, Alert, Badge, ScrollArea, Skeleton/Empty states, semantic columns and drag feedback. |
| `/dashboard` | Custom stat cards and lists | Card composition, responsive metrics, Table breakdowns, Skeleton, Alert, and Empty states. |
| `/intake/call` | Card, Input, Textarea, Select, Badge, Button | FieldGroup/Field forms, grouped Select items, consistent actions and validation semantics. |
| `/intake/walk-in` | Shared ChannelIntakePage | Same shared form-system upgrade with channel-specific copy unchanged. |
| `/public` | Card, Input, Textarea, Select, Checkbox, Badge, Button | FieldGroup, FieldSet, accessible validation, clearer responsive step hierarchy. |
| `/health` | Card, Badge, Button, Skeleton, Separator | Alert states, standardized status treatment, improved responsive summary. |
| `/login` | Card, Badge, Button, Skeleton, Separator | Alert states, Spinner feedback, balanced responsive authentication composition. |

The shared shell currently uses Brand, Button, DropdownMenu, Avatar, Separator, ThemeToggle, and TooltipProvider. It will retain the same navigation destinations while improving responsive layout and semantic grouping.

## Shadcn Composition Rules

- Use existing project components before adding new primitives.
- Add only required official shadcn primitives through the project CLI.
- Use built-in component variants and semantic tokens rather than raw color utilities.
- Use `FieldGroup`, `Field`, `FieldSet`, and `FieldLegend` for forms.
- Wrap `SelectItem` elements in `SelectGroup` and use the Base UI API from the current `base-nova` setup.
- Use full Card composition with header, title, description, content, and footer where applicable.
- Use Alert for callouts, Empty for empty states, Separator for divisions, Skeleton for loading, Badge for statuses, Spinner for pending actions, and Sonner for transient mutation feedback.
- Use `render` for Base UI triggers and links; set `nativeButton={false}` when rendering a non-button element where required.
- Use the configured Lucide icon library. Icons inside shadcn components receive `data-icon` and no manual sizing.
- Use `cn()` for conditional classes and `gap-*` rather than `space-*` utilities.

## Page-Level Implementation

### Shared Shell and Home

Normalize navigation density, active states, mobile overflow, footer rhythm, and brand treatment. Keep every destination and the health query unchanged. Reduce ornamental surfaces so the operational pathways remain dominant.

### Queue

Retain the current query, sorting, filters, links, and ticket-card presentation. Compose search and filters from shadcn inputs/selects, use accessible labels, group menu items, and replace custom loading/error/empty markup with the matching primitives.

### Kanban

Retain dnd-kit sensors, mutations, transition validation, and column ordering. Replace the native domain control and custom state callouts. Use consistent column headers, counts, empty states, scroll behavior, focus states, and mutation feedback.

### Dashboard

Retain the dashboard query and refresh cadence. Present totals through complete Card composition and priority/status breakdowns with responsive Tables. Provide consistent loading, empty, and error surfaces.

### Ticket Detail and Attachments

Retain ticket queries, reply/note mutations, attachment upload behavior, and all displayed information. Recompose the page into a primary work column and semantic context rail. Standardize message, note, file, scan, pending, and error presentation without changing data or actions.

### Intake and Public Forms

Retain field values, validation rules, mutations, redirects, and completion states. Move layout and accessibility semantics to Field/FieldGroup/FieldSet, group Select items, and standardize pending, invalid, and success feedback.

### Login and Health

Retain Keycloak and health-check behavior. Normalize alerts, status badges, loading placeholders, focus treatment, and responsive layout.

## Responsive Behavior

- Mobile: single-column forms and details, horizontally safe Kanban, wrapped action groups, and touch-friendly controls.
- Tablet: two-column layouts where content remains readable.
- Desktop: maximum-width workspace, primary/secondary context split, and dense operational data without card mosaics.
- No horizontal page overflow outside intentional Kanban scrolling.

## Verification

- Run formatting/lint, TypeScript checks, tests, and production build.
- Start the Vite app against the available backend or stable mocked network responses.
- Visit all ten routes at desktop and mobile widths in light and dark mode.
- Verify loading, empty, error, and populated states where accessible.
- Check keyboard navigation, focus visibility, form labels, overlay titles, drag controls, and responsive overflow.
- Confirm API calls, route destinations, mutations, and user-visible behavior remain unchanged.

## Commit Strategy

1. Design-system and shared primitive additions.
2. Shell and home.
3. Queue and Kanban.
4. Dashboard.
5. Ticket detail and attachments.
6. Intake and public forms.
7. Login and health.
8. Verification fixes.

Each commit will contain only the related frontend files and will not include the unrelated existing backend or workspace changes.
