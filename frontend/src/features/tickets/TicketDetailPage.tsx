import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  ChevronRight,
  Mail,
  Phone,
  Tag,
  UserRound,
  UsersRound,
} from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  ChannelBadge,
  PriorityBadge,
  StatusBadge,
} from "@/components/domain-badges";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ApiError,
  apiProblem,
  ticketsApi,
  type TicketDetail,
  type TicketRelationship,
} from "@/lib/api";
import { ActivityTimeline } from "./ActivityTimeline";
import AttachmentUploader from "./AttachmentUploader";
import { MessageComposer } from "./MessageComposer";
import { OperationsPanel } from "./OperationsPanel";
import { SlaClocks } from "./SlaClocks";
import { TransitionActions } from "./TransitionActions";

const RETURN_URL_BASE = new URL("https://ticket-app.invalid/");
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/u;
const PERCENT_ESCAPE = /%[0-9a-f]{2}/iu;

function isTicketPath(pathname: string): boolean {
  return pathname === "/tickets" || pathname.startsWith("/tickets/");
}

function decodedPathStaysInTickets(pathname: string): boolean {
  let candidate = pathname;
  let decodedAtLeastOnce = false;

  for (let index = 0; index < 8; index += 1) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(candidate);
    } catch {
      return (
        decodedAtLeastOnce &&
        candidate.includes("%") &&
        !PERCENT_ESCAPE.test(candidate)
      );
    }

    if (CONTROL_CHARACTERS.test(decoded)) return false;

    let normalized: URL;
    try {
      normalized = new URL(decoded, RETURN_URL_BASE);
    } catch {
      return false;
    }

    if (
      normalized.origin !== RETURN_URL_BASE.origin ||
      !isTicketPath(normalized.pathname)
    ) {
      return false;
    }
    if (decoded === candidate) return true;
    decodedAtLeastOnce = true;
    candidate = decoded;
  }

  return false;
}

function admittedReturnTo(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    /[\u0000-\u001f\u007f]/u.test(value)
  ) {
    return "/tickets";
  }

  try {
    const decodedValue = decodeURI(value);
    if (CONTROL_CHARACTERS.test(decodedValue)) return "/tickets";
    const normalized = new URL(value, RETURN_URL_BASE);
    if (
      normalized.origin !== RETURN_URL_BASE.origin ||
      !isTicketPath(normalized.pathname) ||
      !decodedPathStaysInTickets(normalized.pathname)
    ) {
      return "/tickets";
    }
    return `${normalized.pathname}${normalized.search}${normalized.hash}`;
  } catch {
    return "/tickets";
  }
}

function ticketPath(ticketNumber: string): string {
  return `/tickets/${encodeURIComponent(ticketNumber)}`;
}

function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function BackToQueue({ to }: { to: string }) {
  return (
    <Link to={to} className={buttonVariants({ variant: "ghost", size: "sm" })}>
      <ArrowLeft data-icon="inline-start" aria-hidden />
      Back to queue
    </Link>
  );
}

function TicketLoading() {
  return (
    <section
      className="flex flex-col xl:relative xl:left-1/2 xl:w-[calc(100vw-8rem)] xl:max-w-[84rem] xl:-translate-x-1/2"
      aria-busy="true"
      aria-label="Loading ticket"
    >
      <Skeleton className="mb-4 h-7 w-32" />
      <div className="grid gap-6 pb-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
        <div className="flex flex-col gap-3">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-9 w-3/4" />
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-5 w-1/2" />
        </div>
        <div className="flex flex-col gap-4 lg:items-end">
          <Skeleton className="h-6 w-52" />
          <Skeleton className="h-9 w-32" />
        </div>
      </div>
      <div className="border-y border-border/70 bg-card py-3 [box-shadow:0_0_0_100vmax_var(--card)] [clip-path:inset(0_-100vmax)]">
        <Skeleton className="mb-3 h-5 w-32" />
        <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3 xl:gap-8">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full md:col-span-2 xl:col-span-1" />
        </div>
      </div>
      <div className="grid grid-cols-1 items-stretch gap-5 xl:grid-cols-[minmax(0,1.9fr)_minmax(21rem,1fr)]">
        <Skeleton className="h-[34rem] w-full" />
        <Skeleton className="h-[34rem] w-full" />
      </div>
    </section>
  );
}

function TicketLoadFailure({
  error,
  returnTo,
}: {
  error: unknown;
  returnTo: string;
}) {
  const problem = apiProblem(error);
  const status = error instanceof ApiError ? error.status : null;
  const copy =
    status === 401
      ? {
          title: "Authentication required",
          fallback: "Sign in again to open this ticket.",
        }
      : status === 403
        ? {
            title: "Ticket access denied",
            fallback: "You do not have permission to view this ticket.",
          }
        : status === 404
          ? {
              title: "Ticket not found",
              fallback: "This ticket may have been removed or is unavailable.",
            }
          : {
              title: "Could not load ticket",
              fallback: "The ticket details are unavailable. Please try again.",
            };

  return (
    <Alert variant="destructive">
      <AlertCircle data-icon="inline-start" aria-hidden />
      <AlertTitle>{copy.title}</AlertTitle>
      <AlertDescription>
        <p>{problem?.detail ?? copy.fallback}</p>
        {problem ? <p>Reference: {problem.correlation_id}</p> : null}
        <p>
          <Link to={returnTo}>Back to queue</Link>
        </p>
      </AlertDescription>
    </Alert>
  );
}

function Relationships({
  relationships,
}: {
  relationships: TicketRelationship[];
}) {
  return (
    <section aria-labelledby="relationships-heading" className="flex flex-col">
      <div className="flex items-center gap-2 px-4 py-3">
        <UsersRound className="size-4 text-muted-foreground" aria-hidden />
        <h2 id="relationships-heading" className="text-base font-semibold">
          Relationships
        </h2>
      </div>
      <div className="flex items-center justify-between gap-3 border-t px-4 py-3 text-sm">
        <span className="text-muted-foreground">Linked tickets</span>
        <span className="flex items-center gap-3">
          <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium">
            {relationships.length}
          </span>
          <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
        </span>
      </div>
      {relationships.length ? (
        <ul
          className="divide-y border-t px-4"
          aria-label="Ticket relationships"
        >
          {relationships.map((relationship) => (
            <li
              key={relationship.id}
              className="flex items-center justify-between gap-3 py-3"
            >
              <div className="min-w-0">
                <Link
                  className="break-all text-sm font-medium text-primary underline underline-offset-4"
                  to={ticketPath(relationship.ticket_number)}
                >
                  {relationship.ticket_number}
                </Link>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {humanize(relationship.kind)}
                </p>
              </div>
              <span className="shrink-0 text-xs text-muted-foreground">
                {humanize(relationship.direction)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="sr-only">No related tickets.</p>
      )}
    </section>
  );
}

function RequesterSection({ ticket }: { ticket: TicketDetail }) {
  return (
    <section
      aria-labelledby="requester-heading"
      className="flex flex-col gap-3"
    >
      <div className="flex items-center gap-2">
        <UserRound className="size-4 text-muted-foreground" aria-hidden />
        <h2 id="requester-heading" className="text-base font-semibold">
          Requester
        </h2>
      </div>
      <p className="text-sm font-medium">{ticket.requester.full_name}</p>
      <dl className="flex flex-col gap-2.5 text-sm">
        {ticket.requester.email ? (
          <div>
            <dt className="sr-only">Email</dt>
            <dd>
              <a
                className="flex w-fit items-center gap-2 font-medium text-primary underline-offset-4 hover:underline"
                href={`mailto:${ticket.requester.email}`}
              >
                <Mail className="size-3.5" aria-hidden />
                {ticket.requester.email}
              </a>
            </dd>
          </div>
        ) : null}
        {ticket.requester.phone_e164 ? (
          <div>
            <dt className="sr-only">Phone</dt>
            <dd>
              <a
                className="flex w-fit items-center gap-2 font-medium text-primary underline-offset-4 hover:underline"
                href={`tel:${ticket.requester.phone_e164}`}
              >
                <Phone className="size-3.5" aria-hidden />
                {ticket.requester.phone_e164}
              </a>
            </dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}

function ClassificationSection({ ticket }: { ticket: TicketDetail }) {
  return (
    <section
      aria-labelledby="classification-heading"
      className="flex flex-col gap-4"
    >
      <div className="flex items-center gap-2">
        <Tag className="size-4 text-muted-foreground" aria-hidden />
        <h2 id="classification-heading" className="text-base font-semibold">
          Classification
        </h2>
      </div>
      <dl className="grid gap-2 text-sm">
        <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-center gap-3">
          <dt className="text-muted-foreground">Channel</dt>
          <dd>
            <ChannelBadge channel={ticket.channel} />
          </dd>
        </div>
        <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-3">
          <dt className="text-muted-foreground">Office</dt>
          <dd>{ticket.office}</dd>
        </div>
        <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-3">
          <dt className="text-muted-foreground">Service</dt>
          <dd>{ticket.service}</dd>
        </div>
        <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-3">
          <dt className="text-muted-foreground">Type</dt>
          <dd>{ticket.request_type}</dd>
        </div>
        {ticket.matter_reference ? (
          <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-3">
            <dt className="text-muted-foreground">Matter</dt>
            <dd className="break-all text-sm font-medium">
              {ticket.matter_reference}
            </dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}

export default function TicketDetailPage() {
  const { number } = useParams<{ number: string }>();
  const location = useLocation();
  const queryClient = useQueryClient();
  const returnTo = admittedReturnTo(
    (location.state as { returnTo?: unknown } | null)?.returnTo,
  );

  const ticketQuery = useQuery({
    queryKey: ["ticket", number],
    queryFn: () => ticketsApi.get(number!),
    enabled: Boolean(number),
  });

  if (ticketQuery.isLoading) return <TicketLoading />;

  if (ticketQuery.error || !ticketQuery.data) {
    return <TicketLoadFailure error={ticketQuery.error} returnTo={returnTo} />;
  }

  const ticket = ticketQuery.data;
  const replaceTicket = (updatedTicket: TicketDetail) => {
    queryClient.setQueryData(["ticket", updatedTicket.number], updatedTicket);
    void queryClient.invalidateQueries({ queryKey: ["tickets"] });
    void queryClient.invalidateQueries({ queryKey: ["kanban"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({
      queryKey: ["ticket", updatedTicket.number, "assignees"],
    });
  };
  const refreshActivity = () =>
    queryClient.invalidateQueries({
      queryKey: ["ticket-activity", number],
    });
  const reloadTicket = async () => {
    await queryClient.refetchQueries({
      queryKey: ["ticket", number],
      exact: true,
    });
    await refreshActivity();
  };

  return (
    <section
      className="flex flex-col xl:relative xl:left-1/2 xl:w-[calc(100vw-8rem)] xl:max-w-[84rem] xl:-translate-x-1/2"
      data-testid="ticket-detail-page"
    >
      <div className="pb-4">
        <BackToQueue to={returnTo} />
      </div>

      <header
        className="grid gap-6 pb-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end"
        data-testid="ticket-header"
      >
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex min-w-0 flex-col gap-1">
            <p className="font-mono text-xs text-muted-foreground">
              {ticket.number}
            </p>
            <h1 className="text-2xl font-semibold tracking-tight">
              {ticket.title}
            </h1>
            <p className="text-sm text-muted-foreground">
              {ticket.requester.full_name} · {ticket.office} · {ticket.service}{" "}
              · {ticket.request_type}
            </p>
          </div>
          {ticket.description ? (
            <p className="max-w-4xl whitespace-pre-line text-sm leading-relaxed text-foreground">
              {ticket.description}
            </p>
          ) : null}
        </div>
        <div
          className="flex flex-col items-start gap-4 lg:items-end"
          data-testid="ticket-header-actions"
        >
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            <StatusBadge code={ticket.status_code} label={ticket.status_name} />
            <PriorityBadge code={ticket.priority} />
            <ChannelBadge channel={ticket.channel} />
            <span className="text-sm tabular-nums text-muted-foreground">
              {ticket.age_hours.toFixed(1)}h old
            </span>
          </div>
          <div className="[&_[role=group]]:justify-end [&_[role=group]>button:first-child]:border-primary [&_[role=group]>button:first-child]:bg-primary [&_[role=group]>button:first-child]:text-primary-foreground">
            <TransitionActions
              ticket={ticket}
              onUpdated={replaceTicket}
              onActivityChanged={refreshActivity}
            />
          </div>
        </div>
      </header>

      <section
        id="ticket-context"
        aria-labelledby="ticket-essentials-heading"
        className="border-y border-border/70 bg-card [box-shadow:0_0_0_100vmax_var(--card)] [clip-path:inset(0_-100vmax)]"
      >
        <div className="w-full py-3">
          <h2
            id="ticket-essentials-heading"
            className="text-base font-semibold"
          >
            Ticket essentials
          </h2>
          <div
            className="mt-2 grid gap-6 md:grid-cols-2 xl:grid-cols-3 xl:gap-0"
            data-testid="ticket-essentials-grid"
          >
            <div className="min-w-0 xl:border-r xl:border-border/70 xl:pr-8">
              <RequesterSection ticket={ticket} />
            </div>
            <div className="min-w-0 xl:border-r xl:border-border/70 xl:px-8">
              <ClassificationSection ticket={ticket} />
            </div>
            <div className="min-w-0 md:col-span-2 xl:col-span-1 xl:pl-8">
              <AttachmentUploader
                ticketNumber={ticket.number}
                canUpload={ticket.capabilities.can_upload_attachment}
                embedded
                compact
              />
            </div>
          </div>
        </div>
      </section>

      <div
        data-testid="ticket-workspace-layout"
        className="grid grid-cols-1 items-stretch gap-5 xl:grid-cols-[minmax(0,1.9fr)_minmax(21rem,1fr)]"
      >
        <section className="min-w-0" aria-label="Ticket activity workspace">
          <Card
            className="h-full overflow-hidden rounded-lg!"
            data-testid="ticket-activity-card"
          >
            <CardHeader>
              <CardTitle>
                <h2>Activity</h2>
              </CardTitle>
              <CardDescription>
                Requester messages and internal ticket changes in one stream.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex min-h-0 flex-1 flex-col">
              <div className="min-h-0" data-testid="ticket-activity-scroll">
                <ActivityTimeline ticketNumber={ticket.number} />
              </div>
              {ticket.capabilities.can_add_message ||
              ticket.capabilities.can_add_note ? (
                <MessageComposer
                  ticketNumber={ticket.number}
                  onCreated={refreshActivity}
                  canAddMessage={ticket.capabilities.can_add_message}
                  canAddNote={ticket.capabilities.can_add_note}
                  compact
                />
              ) : null}
            </CardContent>
          </Card>
        </section>

        <aside
          className="min-w-0 overflow-x-clip rounded-lg bg-card ring-1 ring-foreground/10"
          aria-label="Ticket operations"
          data-testid="ticket-operations-rail"
        >
          <div className="p-4">
            <OperationsPanel
              ticket={ticket}
              onUpdated={replaceTicket}
              onReload={reloadTicket}
              onActivityChanged={refreshActivity}
              compact
            />
          </div>
          <Separator />
          <SlaClocks clocks={ticket.sla_clocks} compact />
          <Separator />
          <Relationships relationships={ticket.relationships} />
        </aside>
      </div>
    </section>
  );
}
