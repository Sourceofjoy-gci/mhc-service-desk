import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft } from "lucide-react";
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
      className="flex flex-col gap-6"
      aria-busy="true"
      aria-label="Loading ticket"
    >
      <Skeleton className="h-7 w-32" />
      <div className="flex flex-col gap-3">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-9 w-3/4" />
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-20 w-full" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
        <Skeleton className="h-96 w-full" />
        <div className="flex flex-col gap-4">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
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
    <section aria-labelledby="relationships-heading" className="space-y-3">
      <div>
        <h2 id="relationships-heading" className="text-base font-semibold">
          Relationships
        </h2>
        <p className="text-sm text-muted-foreground">
          Tickets linked to the current request.
        </p>
      </div>
      {relationships.length ? (
        <ul className="divide-y border-y" aria-label="Ticket relationships">
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
        <p className="border-y py-3 text-sm text-muted-foreground">
          No related tickets.
        </p>
      )}
    </section>
  );
}

function RequesterCard({ ticket }: { ticket: TicketDetail }) {
  return (
    <Card className="rounded-lg!">
      <CardHeader>
        <CardTitle>
          <h2>Requester</h2>
        </CardTitle>
        <CardDescription>Contact details for this ticket.</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="text-sm">
          <div className="flex items-start justify-between gap-4">
            <dt className="text-muted-foreground">Full name</dt>
            <dd className="text-right font-medium">
              {ticket.requester.full_name}
            </dd>
          </div>
          {ticket.requester.email ? (
            <>
              <Separator className="my-3" />
              <div className="flex items-start justify-between gap-4">
                <dt className="text-muted-foreground">Email</dt>
                <dd className="break-all text-right">
                  {ticket.requester.email}
                </dd>
              </div>
            </>
          ) : null}
          {ticket.requester.phone_e164 ? (
            <>
              <Separator className="my-3" />
              <div className="flex items-start justify-between gap-4">
                <dt className="text-muted-foreground">Phone</dt>
                <dd className="text-right">{ticket.requester.phone_e164}</dd>
              </div>
            </>
          ) : null}
        </dl>
      </CardContent>
    </Card>
  );
}

function ClassificationCard({ ticket }: { ticket: TicketDetail }) {
  return (
    <Card className="rounded-lg!">
      <CardHeader>
        <CardTitle>
          <h2>Classification</h2>
        </CardTitle>
        <CardDescription>Routing and matter details.</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="text-sm">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Channel</dt>
            <dd>
              <ChannelBadge channel={ticket.channel} />
            </dd>
          </div>
          <Separator className="my-3" />
          <div className="flex items-start justify-between gap-4">
            <dt className="text-muted-foreground">Office</dt>
            <dd className="text-right">{ticket.office}</dd>
          </div>
          <Separator className="my-3" />
          <div className="flex items-start justify-between gap-4">
            <dt className="text-muted-foreground">Service</dt>
            <dd className="text-right">{ticket.service}</dd>
          </div>
          <Separator className="my-3" />
          <div className="flex items-start justify-between gap-4">
            <dt className="text-muted-foreground">Type</dt>
            <dd className="text-right">{ticket.request_type}</dd>
          </div>
          {ticket.matter_reference ? (
            <>
              <Separator className="my-3" />
              <div className="flex items-start justify-between gap-4">
                <dt className="text-muted-foreground">Matter</dt>
                <dd className="break-all text-right text-xs">
                  {ticket.matter_reference}
                </dd>
              </div>
            </>
          ) : null}
        </dl>
      </CardContent>
    </Card>
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
    queryClient.setQueryData(["ticket", number], updatedTicket);
  };
  const refreshActivity = () =>
    queryClient.invalidateQueries({
      queryKey: ["ticket-activity", number],
      exact: true,
    });
  const reloadTicket = async () => {
    await queryClient.refetchQueries({
      queryKey: ["ticket", number],
      exact: true,
    });
    await refreshActivity();
  };

  return (
    <section className="flex flex-col gap-6">
      <div>
        <BackToQueue to={returnTo} />
      </div>

      <header className="flex flex-col gap-4">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
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
          <div className="flex flex-wrap items-center gap-2 md:justify-end">
            <StatusBadge code={ticket.status_code} label={ticket.status_name} />
            <PriorityBadge code={ticket.priority} />
            <ChannelBadge channel={ticket.channel} />
            <span className="text-sm tabular-nums text-muted-foreground">
              {ticket.age_hours.toFixed(1)}h old
            </span>
          </div>
        </div>
        {ticket.description ? (
          <p className="max-w-4xl whitespace-pre-line text-sm leading-relaxed text-foreground">
            {ticket.description}
          </p>
        ) : null}
      </header>

      <TransitionActions
        ticket={ticket}
        onUpdated={replaceTicket}
        onActivityChanged={refreshActivity}
      />

      <div
        data-testid="ticket-workspace-layout"
        className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]"
      >
        <main className="min-w-0" aria-label="Ticket activity workspace">
          <Card className="rounded-lg!">
            <CardHeader>
              <CardTitle>
                <h2>Activity</h2>
              </CardTitle>
              <CardDescription>
                Requester messages and internal ticket changes in one stream.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ActivityTimeline ticketNumber={ticket.number} />
              {ticket.capabilities.can_add_message ||
              ticket.capabilities.can_add_note ? (
                <MessageComposer
                  ticketNumber={ticket.number}
                  onCreated={refreshActivity}
                  canAddMessage={ticket.capabilities.can_add_message}
                  canAddNote={ticket.capabilities.can_add_note}
                />
              ) : null}
            </CardContent>
          </Card>
        </main>

        <aside
          className="flex min-w-0 flex-col gap-5"
          aria-label="Ticket context"
        >
          <div className="border-b pb-5">
            <OperationsPanel
              ticket={ticket}
              onUpdated={replaceTicket}
              onReload={reloadTicket}
              onActivityChanged={refreshActivity}
            />
          </div>
          <div className="border-b pb-5">
            <SlaClocks clocks={ticket.sla_clocks} />
          </div>
          <div className="border-b pb-5">
            <Relationships relationships={ticket.relationships} />
          </div>
          <AttachmentUploader
            ticketNumber={ticket.number}
            canUpload={ticket.capabilities.can_upload_attachment}
          />
          <RequesterCard ticket={ticket} />
          <ClassificationCard ticket={ticket} />
        </aside>
      </div>
    </section>
  );
}
