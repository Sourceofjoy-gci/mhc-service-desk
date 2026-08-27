import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { Badge } from "./ui/badge";

export type StatusCode =
  | "new"
  | "triage"
  | "assigned"
  | "in_progress"
  | "waiting_requester"
  | "waiting_internal"
  | "waiting_it"
  | "quality_review"
  | "resolved"
  | "closed"
  | "cancelled"
  | "rejected"
  | "duplicate"
  | "spam";

export type PriorityCode = "P1" | "P2" | "P3" | "P4";
export type SlaState = "on_track" | "at_risk" | "breached" | "paused" | "none";

const PRIORITY_CODES: PriorityCode[] = ["P1", "P2", "P3", "P4"];
const SLA_STATES: SlaState[] = [
  "on_track",
  "at_risk",
  "breached",
  "paused",
  "none",
];

const STATUS_CODES: StatusCode[] = [
  "new",
  "triage",
  "assigned",
  "in_progress",
  "waiting_requester",
  "waiting_internal",
  "waiting_it",
  "quality_review",
  "resolved",
  "closed",
  "cancelled",
  "rejected",
  "duplicate",
  "spam",
];

const STATUS_LABELS: Record<StatusCode, string> = {
  new: "New",
  triage: "Triage",
  assigned: "Assigned",
  in_progress: "In progress",
  waiting_requester: "Waiting on requester",
  waiting_internal: "Waiting internal",
  waiting_it: "Waiting on IT",
  quality_review: "Quality review",
  resolved: "Resolved",
  closed: "Closed",
  cancelled: "Cancelled",
  rejected: "Rejected",
  duplicate: "Duplicate",
  spam: "Spam",
};

const statusBadge = cva("border-transparent font-medium", {
  variants: {
    code: {
      new: "bg-info/15 text-info-foreground ring-1 ring-inset ring-info/30",
      triage: "bg-info/15 text-info-foreground ring-1 ring-inset ring-info/30",
      assigned:
        "bg-warning/15 text-warning-foreground ring-1 ring-inset ring-warning/30",
      in_progress:
        "bg-warning/15 text-warning-foreground ring-1 ring-inset ring-warning/30",
      waiting_requester:
        "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
      waiting_internal:
        "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
      waiting_it:
        "bg-gold/15 text-gold-foreground ring-1 ring-inset ring-gold/30",
      quality_review:
        "bg-accent text-accent-foreground ring-1 ring-inset ring-border",
      resolved:
        "bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30",
      closed: "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
      cancelled: "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
      rejected:
        "bg-destructive-surface text-destructive ring-1 ring-inset ring-destructive/30",
      duplicate: "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
      spam: "bg-destructive-surface text-destructive ring-1 ring-inset ring-destructive/30",
    },
  },
  defaultVariants: { code: "new" },
});

function normalizeStatusCode(code: string): StatusCode {
  return STATUS_CODES.find((status) => status === code) ?? "new";
}

export interface StatusBadgeProps extends Omit<
  React.HTMLAttributes<HTMLSpanElement>,
  "children"
> {
  code: string;
  label?: string;
}

export function StatusBadge({
  code,
  label,
  className,
  ...rest
}: StatusBadgeProps) {
  const status = normalizeStatusCode(code);

  return (
    <Badge
      data-slot="status-badge"
      data-status={code}
      className={cn(statusBadge({ code: status }), className)}
      {...rest}
    >
      {label ?? (code === status ? STATUS_LABELS[status] : code)}
    </Badge>
  );
}

const priorityDot = cva("size-2 rounded-full", {
  variants: {
    code: {
      P1: "bg-destructive",
      P2: "bg-warning",
      P3: "bg-info",
      P4: "bg-muted-foreground",
    },
  },
  defaultVariants: { code: "P3" },
});

export interface PriorityBadgeProps extends Omit<
  React.HTMLAttributes<HTMLSpanElement>,
  "children"
> {
  code: string;
  showDot?: boolean;
}

function normalizePriorityCode(code: string): PriorityCode {
  return PRIORITY_CODES.find((priority) => priority === code) ?? "P3";
}

export function PriorityBadge({
  code,
  showDot = true,
  className,
  ...rest
}: PriorityBadgeProps) {
  const priority = normalizePriorityCode(code);

  return (
    <Badge
      variant="outline"
      data-slot="priority-badge"
      data-priority={code}
      className={cn(
        "border-border/60 font-mono text-xs font-semibold tracking-wider",
        className,
      )}
      {...rest}
    >
      {showDot ? (
        <span
          data-icon="inline-start"
          className={priorityDot({ code: priority })}
          aria-hidden
        />
      ) : null}
      {code}
    </Badge>
  );
}

const CHANNEL_LABELS: Record<string, string> = {
  web: "Web",
  call: "Call",
  walk_in: "Walk-in",
  email: "Email",
  internal: "Internal",
  whatsapp: "WhatsApp",
  monitoring: "Monitoring",
};

export function ChannelBadge({
  channel,
  className,
}: {
  channel: string;
  className?: string;
}) {
  return (
    <Badge
      variant="secondary"
      data-slot="channel-badge"
      className={cn("text-xs font-normal", className)}
    >
      {CHANNEL_LABELS[channel] ?? channel}
    </Badge>
  );
}

const SLA_LABELS: Record<SlaState, string> = {
  on_track: "On track",
  at_risk: "At risk",
  breached: "Breached",
  paused: "Paused",
  none: "No SLA",
};

const slaHealthDot = cva("size-2 rounded-full ring-2 ring-background", {
  variants: {
    state: {
      on_track: "bg-success",
      at_risk: "bg-warning",
      breached: "bg-destructive",
      paused: "bg-muted-foreground",
      none: "bg-muted-foreground/40",
    },
  },
  defaultVariants: { state: "none" },
});

export function SlaIndicator({
  health,
  className,
}: {
  health: string;
  className?: string;
}) {
  const state = SLA_STATES.find((slaState) => slaState === health) ?? "none";
  const label = SLA_LABELS[state];

  return (
    <Badge
      variant="outline"
      data-slot="sla-indicator"
      data-sla={health}
      className={cn("font-normal text-muted-foreground", className)}
      title={`SLA: ${label}`}
    >
      <span
        data-icon="inline-start"
        className={slaHealthDot({ state })}
        aria-hidden
      />
      {label}
    </Badge>
  );
}
