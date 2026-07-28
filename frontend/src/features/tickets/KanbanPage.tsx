import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import { AlertCircle, GripVertical, Inbox, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/features/auth/AuthProvider";
import PermissionPage from "@/features/auth/PermissionPage";
import {
  ApiError,
  apiProblem,
  domainCapabilities,
  ticketsApi,
  type Domain,
  type TicketSummary,
} from "../../lib/api";
import { TicketCard } from "./TicketCard";
import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const OPERATIONAL_COLUMNS = [
  "new",
  "triage",
  "assigned",
  "in_progress",
  "reopened",
  "waiting_requester",
  "waiting_internal",
  "waiting_it",
  "quality_review",
  "resolved",
];

const IT_COLUMNS = [
  "new",
  "triage",
  "assigned",
  "diagnosing",
  "in_progress",
  "reopened",
  "waiting_user",
  "waiting_vendor",
  "waiting_change",
  "validation",
  "resolved",
];

const WORKFLOW_COLUMNS: Record<Domain, string[]> = {
  operational: OPERATIONAL_COLUMNS,
  it: IT_COLUMNS,
};

const COLUMN_LABELS: Record<string, string> = {
  new: "New",
  triage: "Triage",
  assigned: "Assigned",
  diagnosing: "Diagnosing",
  in_progress: "In Progress",
  waiting_requester: "Waiting for Requester",
  waiting_internal: "Waiting for Internal Unit",
  waiting_it: "Waiting for IT",
  waiting_user: "Waiting for User",
  waiting_vendor: "Waiting for Vendor",
  waiting_change: "Waiting for Change",
  quality_review: "Quality Review",
  validation: "Validation",
  resolved: "Resolved",
  reopened: "Reopened",
};

const DOMAIN_OPTIONS: { value: Domain; label: string }[] = [
  { value: "operational", label: "Operational" },
  { value: "it", label: "IT" },
];

function DraggableTicket({ ticket }: { ticket: TicketSummary }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, isDragging } =
    useDraggable({
      id: ticket.id,
      data: { number: ticket.number, fromStatus: ticket.status_code },
    });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "relative rounded-lg transition-[transform,opacity,box-shadow] duration-150",
        isDragging &&
          "scale-[0.98] opacity-40 ring-2 ring-ring ring-offset-2 ring-offset-background",
      )}
      data-draggable="true"
      data-dragging={isDragging || undefined}
    >
      <TicketCard ticket={ticket} />
      <button
        ref={setActivatorNodeRef}
        type="button"
        {...listeners}
        {...attributes}
        aria-label={`Move ticket ${ticket.number}`}
        className="absolute right-2 bottom-2 z-10 inline-flex size-7 cursor-grab items-center justify-center rounded-md border bg-background/95 text-muted-foreground shadow-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50 active:cursor-grabbing"
      >
        <GripVertical className="size-4" aria-hidden />
      </button>
    </div>
  );
}

function DroppableColumn({
  code,
  label,
  tickets,
}: {
  code: string;
  label: string;
  tickets: TicketSummary[];
}) {
  const { setNodeRef, isOver } = useDroppable({ id: code });

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "flex h-full w-72 shrink-0 flex-col rounded-lg border bg-muted/30 p-2 transition-[transform,box-shadow,border-color] duration-150",
        isOver &&
          "scale-[1.01] border-ring ring-2 ring-ring/50 ring-offset-2 ring-offset-background",
      )}
      data-over={isOver || undefined}
    >
      <div className="mb-2 flex items-center justify-between gap-2 px-1">
        <h2 className="text-sm font-semibold">{label}</h2>
        <Badge variant="secondary" className="tabular-nums">
          {tickets.length}
        </Badge>
      </div>
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {tickets.map((ticket) => (
          <DraggableTicket key={ticket.id} ticket={ticket} />
        ))}
        {tickets.length === 0 ? (
          <Empty className="min-h-24 flex-none gap-2 p-4">
            <EmptyHeader className="gap-1">
              <EmptyMedia variant="icon">
                <Inbox data-icon="inline-start" aria-hidden />
              </EmptyMedia>
              <EmptyTitle>No tickets</EmptyTitle>
              <EmptyDescription>Drop a ticket here.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : null}
      </div>
    </div>
  );
}

export default function KanbanPage() {
  const { user } = useAuth();
  const { queueDomains: domains } = domainCapabilities(user?.groups ?? []);
  const [selectedDomain, setSelectedDomain] = useState<Domain | null>(null);
  const domain =
    selectedDomain && domains.includes(selectedDomain)
      ? selectedDomain
      : domains[0];
  const [validityError, setValidityError] = useState<string | null>(null);
  const pendingTicketNumbers = useRef(new Set<string>());
  const qc = useQueryClient();
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor),
  );

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["kanban", domain],
    queryFn: () => ticketsApi.kanban(domain!),
    enabled: Boolean(domain),
  });

  const transition = useMutation({
    mutationFn: ({
      number,
      to,
      updated_at,
    }: {
      number: string;
      to: string;
      updated_at: string;
    }) =>
      ticketsApi.transition(number, {
        to_status: to,
        updated_at,
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["kanban", domain], exact: true }),
    onError: (mutationError) => {
      if (apiProblem(mutationError)?.code !== "stale_ticket") {
        toast.error("Ticket transition failed");
      }
    },
    onSettled: (_data, _error, variables) => {
      pendingTicketNumbers.current.delete(variables.number);
    },
  });

  const handleDragEnd = (event: DragEndEvent) => {
    const ticketId = event.active?.id as string | undefined;
    const toColumn = event.over?.id as string | undefined;
    if (!ticketId || !toColumn) return;
    const allTickets = Object.values(data?.columns ?? {}).flat();
    const ticket = allTickets.find((item) => item.id === ticketId);
    if (!ticket || ticket.status_code === toColumn) return;
    if (!ticket.available_transition_codes.includes(toColumn)) {
      setValidityError("That transition is not available.");
      return;
    }
    if (pendingTicketNumbers.current.has(ticket.number)) return;
    pendingTicketNumbers.current.add(ticket.number);
    setValidityError(null);
    transition.mutate({
      number: ticket.number,
      to: toColumn,
      updated_at: ticket.updated_at,
    });
  };

  const columns = domain ? WORKFLOW_COLUMNS[domain] : [];
  const columns_data = data?.columns ?? {};
  const loadProblem = apiProblem(error);
  const loadDenied = error instanceof ApiError && error.status === 403;
  const transitionProblem = apiProblem(transition.error);
  const transitionDenied =
    transition.error instanceof ApiError && transition.error.status === 403;
  const stale =
    transition.error instanceof ApiError &&
    transition.error.status === 409 &&
    transitionProblem?.code === "stale_ticket";

  const refreshBoard = async () => {
    await refetch();
    transition.reset();
    setValidityError(null);
  };

  if (!domain) return <PermissionPage />;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Kanban</h1>
          <p className="text-sm text-muted-foreground">
            Move tickets between workflow stages.
          </p>
        </div>
        {domains.length > 1 ? (
          <Field
            orientation="horizontal"
            className="w-full justify-between sm:w-auto sm:justify-start"
          >
            <FieldLabel htmlFor="kanban-domain">Domain</FieldLabel>
            <Select
              items={DOMAIN_OPTIONS.filter((option) =>
                domains.includes(option.value),
              )}
              value={domain}
              onValueChange={(value) => {
                if (value == null || !domains.includes(value as Domain)) return;
                setSelectedDomain(value as Domain);
                transition.reset();
                setValidityError(null);
              }}
            >
              <SelectTrigger id="kanban-domain" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {DOMAIN_OPTIONS.filter((option) =>
                    domains.includes(option.value),
                  ).map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        ) : null}
      </div>

      {transition.isError ? (
        <Alert variant="destructive">
          <AlertCircle data-icon="inline-start" aria-hidden />
          <AlertTitle>
            {stale
              ? "This board is out of date"
              : transitionDenied
                ? "Move not permitted"
                : "Ticket transition failed"}
          </AlertTitle>
          <AlertDescription>
            {transitionProblem?.detail ??
              (transitionDenied
                ? "You do not have permission to move this ticket."
                : "The ticket could not be moved. Please try again.")}
            {transitionProblem ? (
              <span className="block">
                Reference: {transitionProblem.correlation_id}
              </span>
            ) : null}
          </AlertDescription>
          {stale ? (
            <AlertAction>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void refreshBoard()}
                disabled={isLoading}
                data-icon
              >
                <RefreshCw data-icon="inline-start" />
                Refresh board
              </Button>
            </AlertAction>
          ) : null}
        </Alert>
      ) : null}

      {validityError ? (
        <Alert variant="destructive">
          <AlertCircle data-icon="inline-start" aria-hidden />
          <AlertTitle>Move not available</AlertTitle>
          <AlertDescription>{validityError}</AlertDescription>
        </Alert>
      ) : null}

      {isLoading ? <KanbanSkeleton columns={columns} /> : null}

      {error ? (
        <Alert variant="destructive">
          <AlertCircle data-icon="inline-start" aria-hidden />
          <AlertTitle>
            {loadDenied ? "Kanban access denied" : "Could not load the Kanban"}
          </AlertTitle>
          <AlertDescription>
            {loadProblem?.detail ??
              (loadDenied
                ? "You do not have permission to open this board."
                : "The board is unavailable. Please try again.")}
            {loadProblem ? (
              <span className="block">
                Reference: {loadProblem.correlation_id}
              </span>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {data ? (
        <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
          <div className="flex h-[calc(100vh-220px)] gap-3 overflow-x-auto pb-2">
            {columns.map((code) => (
              <DroppableColumn
                key={code}
                code={code}
                label={COLUMN_LABELS[code] ?? code}
                tickets={columns_data[code] ?? []}
              />
            ))}
          </div>
        </DndContext>
      ) : null}
    </section>
  );
}

function KanbanSkeleton({ columns }: { columns: string[] }) {
  return (
    <div
      className="flex h-[calc(100vh-220px)] gap-3 overflow-x-auto pb-2"
      aria-label="Loading Kanban"
    >
      {columns.map((code) => (
        <div
          key={code}
          className="flex h-full w-72 shrink-0 flex-col gap-3 rounded-lg border bg-muted/30 p-2"
        >
          <div className="flex items-center justify-between gap-2 px-1">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-5 w-8 rounded-full" />
          </div>
          <div className="flex flex-col gap-2">
            <Skeleton className="h-28 w-full rounded-lg" />
            <Skeleton className="h-28 w-full rounded-lg" />
            <Skeleton className="h-28 w-full rounded-lg" />
          </div>
        </div>
      ))}
    </div>
  );
}
