import { cva } from "class-variance-authority";
import { Badge } from "./ui/badge";
import { cn } from "@/lib/utils";

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
      closed:
        "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
      cancelled:
        "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
      rejected: "bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30",
      duplicate:
        "bg-muted text-muted-foreground ring-1 ring-inset ring-border",
      spam: "bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30",
    },
  },
  defaultVariants: { code: "new" },
});

export interface StatusBadgeProps
  extends Omit<React.HTMLAttributes<HTMLSpanElement>, "children"> {
  code: string;
  label?: string;
}

const STATUS_LABELS: Record<string, string> = {
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

export function StatusBadge({ code, label, className, ...rest }: StatusBadgeProps) {
  const key = (STATUS_LABELS[code] ? code : "new") as
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
  return (
    <Badge
      data-slot="status-badge"
      data-status={code}
      className={cn(statusBadge({ code: key }), className)}
      {...rest}
    >
      {label ?? STATUS_LABELS[code] ?? code}
    </Badge>
  );
}

const priorityDot = cva("size-1.5 rounded-full", {
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

export interface PriorityBadgeProps
  extends Omit<React.HTMLAttributes<HTMLSpanElement>, "children"> {
  code: string;
  showDot?: boolean;
}

export function PriorityBadge({
  code,
  showDot = true,
  className,
  ...rest
}: PriorityBadgeProps) {
  return (
    <Badge
      variant="outline"
      data-slot="priority-badge"
      data-priority={code}
      className={cn(
        "border-border/60 font-mono text-[10px] font-semibold tracking-wider",
        className,
      )}
      {...rest}
    >
      {showDot ? (
        <span
          className={cn(priorityDot({ code: code as any }), "mr-1")}
          aria-hidden
        />
      ) : null}
      {code}
    </Badge>
  );
}

const channelLabel: Record<string, string> = {
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
      className={cn("text-[11px] font-normal", className)}
    >
      {channelLabel[channel] ?? channel}
    </Badge>
  );
}

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
  health:
    | "on_track"
    | "at_risk"
    | "breached"
    | "paused"
    | "none"
    | string;
  className?: string;
}) {
  const state = (health as any) ?? "none";
  const label =
    health === "on_track"
      ? "On track"
      : health === "at_risk"
        ? "At risk"
        : health === "breached"
          ? "Breached"
          : health === "paused"
            ? "Paused"
            : "No SLA";
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs", className)}
      title={`SLA: ${label}`}
    >
      <span className={cn(slaHealthDot({ state }))} aria-hidden />
      <span className="text-muted-foreground">{label}</span>
    </span>
  );
}
