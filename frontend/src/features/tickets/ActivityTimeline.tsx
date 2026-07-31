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
import { ApiError, apiProblem, type ActivityItem, ticketsApi } from "@/lib/api";

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
  status_transition: { from: string; to: string; reason: string };
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
  custody_event: Record<string, unknown>;
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

function text(value: unknown, fallback = "Not provided"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function typedActivity(item: ActivityItem): TypedActivityItem {
  const payload = record(item.payload);
  switch (item.type) {
    case "message":
      return {
        ...item,
        type: "message",
        payload: {
          body_text: text(payload.body_text),
          direction: text(payload.direction, "message"),
          delivery_status: text(payload.delivery_status, "unknown"),
        },
      };
    case "internal_note":
      return {
        ...item,
        type: "internal_note",
        payload: { body: text(payload.body) },
      };
    case "status_transition":
      return {
        ...item,
        type: "status_transition",
        payload: {
          from: text(payload.from, "unknown"),
          to: text(payload.to, "unknown"),
          reason: text(payload.reason, "No reason recorded"),
        },
      };
    case "work_state":
      return {
        ...item,
        type: "work_state",
        payload: {
          before: record(payload.before),
          after: record(payload.after),
        },
      };
    case "attachment":
      return {
        ...item,
        type: "attachment",
        payload: {
          filename: text(payload.filename, "Unnamed attachment"),
          scan_status: text(payload.scan_status, "unknown"),
        },
      };
    case "relationship":
      return {
        ...item,
        type: "relationship",
        payload: {
          kind: text(payload.kind, "related"),
          ticket_number: text(payload.ticket_number, "Unknown ticket"),
          direction: text(payload.direction, "related"),
        },
      };
    case "custody_event":
      return {
        ...item,
        type: "custody_event",
        payload,
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

function ActivityFrame({
  item,
  label,
  children,
  className = "",
}: {
  item: TypedActivityItem;
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <article
      aria-label={label}
      data-visibility={item.visibility}
      className={`border-l-2 py-3 pl-4 ${className}`}
    >
      {children}
      <footer className="mt-3 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
        <span>{item.actor?.display_name ?? "System"}</span>
        <span aria-hidden>·</span>
        <time dateTime={item.occurred_at}>
          {new Intl.DateTimeFormat(undefined, {
            dateStyle: "medium",
            timeStyle: "short",
          }).format(new Date(item.occurred_at))}
        </time>
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
      className="border-l-sky-500 bg-sky-50/60 pr-3 dark:bg-sky-950/20"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">Message</h3>
        <span className="text-xs font-medium text-sky-700 dark:text-sky-300">
          Visible to requester
        </span>
      </div>
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
      className="border-l-amber-500 bg-amber-50/60 pr-3 dark:bg-amber-950/20"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">Internal note</h3>
        <span className="text-xs font-medium text-amber-800 dark:text-amber-300">
          Internal only
        </span>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm">{item.payload.body}</p>
    </ActivityFrame>
  );
}

function TransitionActivity({
  item,
}: {
  item: Extract<TypedActivityItem, { type: "status_transition" }>;
}) {
  return (
    <ActivityFrame
      item={item}
      label="Status transition"
      className="border-l-primary"
    >
      <h3 className="font-medium">Status changed</h3>
      <p className="mt-1 text-sm">
        {humanize(item.payload.from)} to {humanize(item.payload.to)}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">
        {item.payload.reason}
      </p>
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
  return (
    <ActivityFrame
      item={item}
      label="Custody event"
      className="border-l-emerald-500"
    >
      <h3 className="font-medium">Custody event</h3>
      <p className="mt-1 text-sm">
        {humanize(text(item.payload.action, "Recorded"))}
      </p>
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
