import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  apiProblem,
  type ActivityItem,
  type AssignmentParty,
  ticketsApi,
} from "@/lib/api";

interface ActivityTimelineProps {
  ticketNumber: string;
}

interface ActivityPayloads {
  message: {
    body_text: string;
    direction: string;
    delivery_status: string;
  };
  internal_note: { body: string };
  status_transition: {
    action: string;
    from: string;
    to: string;
    reason: string;
  };
  work_state: {
    before: Record<string, unknown>;
    after: Record<string, unknown>;
  };
  attachment: { filename: string; scan_status: string };
  relationship: {
    kind: string;
    ticket_number: string;
    direction: string;
  };
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
}

type TypedActivityItem = {
  [Type in ActivityItem["type"]]: Omit<ActivityItem, "type" | "payload"> & {
    type: Type;
    payload: ActivityPayloads[Type];
  };
}[ActivityItem["type"]];

function assertNever(value: never): never {
  throw new Error(`Unsupported activity item: ${String(value)}`);
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function nullableRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown, fallback = "Not provided"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter(
        (entry): entry is string =>
          typeof entry === "string" && Boolean(entry.trim()),
      )
    : [];
}

function assignmentParty(value: unknown): AssignmentParty | null {
  const party = nullableRecord(value);
  if (!party) return null;
  return {
    id: text(party.id, ""),
    display_name: text(party.display_name, "Unknown owner"),
    designations: strings(party.designations),
    team_labels: strings(party.team_labels),
  };
}

function queue(value: unknown): { id: string; label: string } | null {
  const queueRecord = nullableRecord(value);
  if (!queueRecord) return null;
  return {
    id: text(queueRecord.id, ""),
    label: text(queueRecord.label, "Unknown queue"),
  };
}

function status(value: unknown): { code: string; label: string } | null {
  const statusRecord = nullableRecord(value);
  if (!statusRecord) return null;
  return {
    code: text(statusRecord.code, "unknown"),
    label: text(statusRecord.label, "Unknown status"),
  };
}

function actorKind(value: unknown): "user" | "system" {
  return value === "system" ? "system" : "user";
}

function activityActor(value: unknown): ActivityItem["actor"] {
  const actor = nullableRecord(value);
  if (!actor) return null;
  const subject = text(actor.subject, "");
  const displayName = text(actor.display_name, subject);
  return displayName ? { subject, display_name: displayName } : null;
}

function typedActivity(item: ActivityItem): TypedActivityItem {
  const payload = record(item.payload);
  const safeItem = { ...item, actor: activityActor(item.actor) };
  switch (item.type) {
    case "message":
      return {
        ...safeItem,
        type: "message",
        payload: {
          body_text: text(payload.body_text),
          direction: text(payload.direction, "message"),
          delivery_status: text(payload.delivery_status, "unknown"),
        },
      };
    case "internal_note":
      return {
        ...safeItem,
        type: "internal_note",
        payload: { body: text(payload.body) },
      };
    case "status_transition":
      return {
        ...safeItem,
        type: "status_transition",
        payload: {
          action: text(payload.action, "status_changed"),
          from: text(payload.from, "unknown"),
          to: text(payload.to, "unknown"),
          reason: text(payload.reason, ""),
        },
      };
    case "work_state":
      return {
        ...safeItem,
        type: "work_state",
        payload: {
          before: record(payload.before),
          after: record(payload.after),
        },
      };
    case "attachment":
      return {
        ...safeItem,
        type: "attachment",
        payload: {
          filename: text(payload.filename, "Unnamed attachment"),
          scan_status: text(payload.scan_status, "unknown"),
        },
      };
    case "relationship":
      return {
        ...safeItem,
        type: "relationship",
        payload: {
          kind: text(payload.kind, "related"),
          ticket_number: text(payload.ticket_number, "Unknown ticket"),
          direction: text(payload.direction, "related"),
        },
      };
    case "custody_event":
      return {
        ...safeItem,
        type: "custody_event",
        payload: {
          action: text(payload.action, "recorded"),
          previous_owner: assignmentParty(payload.previous_owner),
          new_owner: assignmentParty(payload.new_owner),
          previous_queue: queue(payload.previous_queue),
          new_queue: queue(payload.new_queue),
          previous_status: status(payload.previous_status),
          new_status: status(payload.new_status),
          actor_kind: actorKind(payload.actor_kind),
          source_process: text(payload.source_process, ""),
          reason: text(payload.reason, ""),
        },
      };
    default:
      return assertNever(item.type);
  }
}

function humanize(value: string): string {
  const words = value.replaceAll("_", " ").replaceAll("-", " ");
  return words ? words[0].toUpperCase() + words.slice(1) : "Not set";
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not set";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") {
    return humanize(String(value));
  }
  if (Array.isArray(value))
    return value.map(displayValue).join(", ") || "Not set";
  return "Updated";
}

function formatDateTime(
  value: unknown,
): { dateTime: string; label: string } | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return {
    dateTime: value,
    label: new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date),
  };
}

function ActivityFrame({
  item,
  label,
  category,
  categoryClassName,
  children,
  className = "",
}: {
  item: TypedActivityItem;
  label: string;
  category: string;
  categoryClassName: string;
  children: React.ReactNode;
  className?: string;
}) {
  const occurredAt = formatDateTime(item.occurred_at);
  return (
    <article
      aria-label={label}
      data-visibility={item.visibility}
      className={`border-l-2 py-3 pl-4 ${className}`}
    >
      <div className="mb-2">
        <span
          className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${categoryClassName}`}
        >
          {category}
        </span>
      </div>
      {children}
      <footer className="mt-3 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
        <span>{item.actor?.display_name ?? "System"}</span>
        <span aria-hidden>·</span>
        {occurredAt ? (
          <time dateTime={occurredAt.dateTime}>{occurredAt.label}</time>
        ) : (
          <span>Time unavailable</span>
        )}
      </footer>
    </article>
  );
}

function MessageActivity({
  item,
}: {
  item: Extract<TypedActivityItem, { type: "message" }>;
}) {
  return (
    <ActivityFrame
      item={item}
      label="Requester-visible message"
      category="Visible to requester"
      categoryClassName="border-sky-300/70 bg-sky-100/70 text-sky-800 dark:border-sky-700 dark:bg-sky-950/50 dark:text-sky-300"
      className="border-l-sky-500 bg-sky-50/60 pr-3 dark:bg-sky-950/20"
    >
      <h3 className="font-medium">Message</h3>
      <p className="mt-2 whitespace-pre-wrap text-sm">
        {item.payload.body_text}
      </p>
      <p className="mt-2 text-xs text-muted-foreground">
        {humanize(item.payload.direction)} ·{" "}
        {humanize(item.payload.delivery_status)}
      </p>
    </ActivityFrame>
  );
}

function NoteActivity({
  item,
}: {
  item: Extract<TypedActivityItem, { type: "internal_note" }>;
}) {
  return (
    <ActivityFrame
      item={item}
      label="Internal note"
      category="Internal only"
      categoryClassName="border-amber-300/70 bg-amber-100/70 text-amber-900 dark:border-amber-700 dark:bg-amber-950/50 dark:text-amber-300"
      className="border-l-amber-500 bg-amber-50/60 pr-3 dark:bg-amber-950/20"
    >
      <h3 className="font-medium">Internal note</h3>
      <p className="mt-2 whitespace-pre-wrap text-sm">{item.payload.body}</p>
    </ActivityFrame>
  );
}

function TransitionActivity({
  item,
}: {
  item: Extract<TypedActivityItem, { type: "status_transition" }>;
}) {
  const actionLabel =
    item.payload.action === "reopened" || item.payload.to === "reopened"
      ? "Ticket reopened"
      : item.payload.action === "closed" || item.payload.to === "closed"
        ? "Ticket closed"
        : "Status changed";
  return (
    <ActivityFrame
      item={item}
      label={`Workflow event: ${actionLabel}`}
      category="Workflow"
      categoryClassName="border-primary/30 bg-primary/5 text-primary"
      className="border-l-primary"
    >
      <h3 className="font-medium">{actionLabel}</h3>
      <p className="mt-1 text-sm">
        Status: {humanize(item.payload.from)} → {humanize(item.payload.to)}
      </p>
      {item.payload.reason ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {item.payload.reason}
        </p>
      ) : null}
    </ActivityFrame>
  );
}

function WorkStateActivity({
  item,
}: {
  item: Extract<TypedActivityItem, { type: "work_state" }>;
}) {
  const keys = [
    ...new Set([
      ...Object.keys(item.payload.before),
      ...Object.keys(item.payload.after),
    ]),
  ].filter(
    (key) =>
      displayValue(item.payload.before[key]) !==
      displayValue(item.payload.after[key]),
  );
  return (
    <ActivityFrame
      item={item}
      label="Work state change"
      category="Workflow"
      categoryClassName="border-primary/30 bg-primary/5 text-primary"
      className="border-l-slate-400"
    >
      <h3 className="font-medium">Work state updated</h3>
      {keys.length ? (
        <div className="mt-2 space-y-1 text-sm">
          {keys.map((key) => (
            <p key={key}>
              {humanize(key)} changed from{" "}
              {displayValue(item.payload.before[key])} to{" "}
              {displayValue(item.payload.after[key])}
            </p>
          ))}
        </div>
      ) : (
        <p className="mt-1 text-sm text-muted-foreground">
          No field details recorded.
        </p>
      )}
    </ActivityFrame>
  );
}

function AttachmentActivity({
  item,
}: {
  item: Extract<TypedActivityItem, { type: "attachment" }>;
}) {
  return (
    <ActivityFrame
      item={item}
      label="Attachment added"
      category="Attachment"
      categoryClassName="border-violet-300/70 bg-violet-50 text-violet-800 dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-300"
      className="border-l-violet-400"
    >
      <h3 className="font-medium">Attachment added</h3>
      <p className="mt-1 text-sm">{item.payload.filename}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Scan: {humanize(item.payload.scan_status)}
      </p>
    </ActivityFrame>
  );
}

function RelationshipActivity({
  item,
}: {
  item: Extract<TypedActivityItem, { type: "relationship" }>;
}) {
  return (
    <ActivityFrame
      item={item}
      label="Ticket relationship"
      category="Relationship"
      categoryClassName="border-slate-300 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900/40 dark:text-slate-300"
      className="border-l-emerald-500"
    >
      <h3 className="font-medium">Ticket relationship added</h3>
      <p className="mt-1 text-sm">
        {humanize(item.payload.direction)} {humanize(item.payload.kind)} ticket{" "}
        <Link
          className="font-medium text-primary underline underline-offset-4"
          to={`/tickets/${item.payload.ticket_number}`}
        >
          {item.payload.ticket_number}
        </Link>
      </p>
    </ActivityFrame>
  );
}

function CustodyActivity({
  item,
}: {
  item: Extract<TypedActivityItem, { type: "custody_event" }>;
}) {
  const actionLabels: Record<string, string> = {
    created: "Ticket created",
    assigned: "Assigned",
    reassigned: "Reassigned",
    unassigned: "Unassigned",
    queue_changed: "Queue changed",
    escalated: "Escalated",
  };
  const actionLabel =
    actionLabels[item.payload.action] ?? humanize(item.payload.action);
  const ownerActions = new Set(["assigned", "reassigned", "unassigned"]);
  const showsOwner =
    ownerActions.has(item.payload.action) ||
    item.payload.previous_owner !== null ||
    item.payload.new_owner !== null;
  const showsQueue =
    item.payload.action === "queue_changed" ||
    item.payload.previous_queue !== null ||
    item.payload.new_queue !== null;
  const showsStatus =
    item.payload.previous_status !== null || item.payload.new_status !== null;

  const ownerLabel = (owner: AssignmentParty | null) => {
    if (!owner) return "Unassigned";
    const context = [...new Set([...owner.designations, ...owner.team_labels])];
    return context.length
      ? `${owner.display_name} (${context.join(" · ")})`
      : owner.display_name;
  };
  return (
    <ActivityFrame
      item={item}
      label={`Custody event: ${actionLabel}`}
      category="Chain of custody"
      categoryClassName="border-emerald-300/70 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300"
      className="border-l-emerald-500 bg-slate-50/40 pr-3 dark:bg-slate-950/20"
    >
      <h3 className="font-medium">{actionLabel}</h3>
      <div className="mt-2 space-y-1 text-sm">
        {showsOwner ? (
          <p>
            Owner: {ownerLabel(item.payload.previous_owner)} →{" "}
            {ownerLabel(item.payload.new_owner)}
          </p>
        ) : null}
        {showsQueue ? (
          <p>
            Queue: {item.payload.previous_queue?.label ?? "Not set"} →{" "}
            {item.payload.new_queue?.label ?? "Not set"}
          </p>
        ) : null}
        {showsStatus ? (
          <p>
            Status: {item.payload.previous_status?.label ?? "Not set"} →{" "}
            {item.payload.new_status?.label ?? "Not set"}
          </p>
        ) : null}
      </div>
      {item.payload.actor_kind === "system" && item.payload.source_process ? (
        <p className="mt-2 text-xs font-medium text-emerald-800 dark:text-emerald-300">
          System process: {item.payload.source_process}
        </p>
      ) : null}
      {item.payload.reason ? (
        <p className="mt-2 text-sm text-muted-foreground">
          {item.payload.reason}
        </p>
      ) : null}
    </ActivityFrame>
  );
}

function renderActivity(item: TypedActivityItem) {
  switch (item.type) {
    case "message":
      return <MessageActivity item={item} />;
    case "internal_note":
      return <NoteActivity item={item} />;
    case "status_transition":
      return <TransitionActivity item={item} />;
    case "work_state":
      return <WorkStateActivity item={item} />;
    case "attachment":
      return <AttachmentActivity item={item} />;
    case "relationship":
      return <RelationshipActivity item={item} />;
    case "custody_event":
      return <CustodyActivity item={item} />;
    default:
      return assertNever(item);
  }
}

export function ActivityTimeline({ ticketNumber }: ActivityTimelineProps) {
  const query = useQuery({
    queryKey: ["ticket-activity", ticketNumber],
    queryFn: () => ticketsApi.activity(ticketNumber),
  });

  if (query.isLoading) {
    return (
      <div className="flex min-h-24 items-center justify-center">
        <Spinner className="size-5" aria-label="Loading activity" />
      </div>
    );
  }

  if (query.isError) {
    const problem = apiProblem(query.error);
    const denied =
      query.error instanceof ApiError && query.error.status === 403;
    return (
      <Alert variant="destructive">
        <AlertTitle>
          {denied ? "Activity unavailable" : "Could not load activity"}
        </AlertTitle>
        <AlertDescription>
          <p>
            {problem?.detail ??
              (denied
                ? "You do not have permission to view this ticket activity."
                : "Please try again.")}
          </p>
          {problem ? <p>Reference: {problem.correlation_id}</p> : null}
        </AlertDescription>
      </Alert>
    );
  }

  if (!query.data?.results.length) {
    return (
      <Empty className="min-h-32 border">
        <EmptyHeader>
          <EmptyTitle>No activity yet</EmptyTitle>
          <EmptyDescription>
            Messages and ticket changes will appear here.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const items = query.data.results.map(typedActivity);

  return (
    <ol aria-label="Ticket activity" className="divide-y">
      {items.map((item) => (
        <li key={item.id}>{renderActivity(item)}</li>
      ))}
    </ol>
  );
}
