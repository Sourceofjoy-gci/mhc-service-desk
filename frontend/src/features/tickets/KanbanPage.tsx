import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
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
import { AlertCircle, Inbox } from "lucide-react";
import { toast } from "sonner";
import { ticketsApi, type Domain, type TicketSummary } from "../../lib/api";
import { TicketCard } from "./TicketCard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
  "waiting_requester",
  "waiting_internal",
  "waiting_it",
  "quality_review",
  "reopened",
];

const COLUMN_LABELS: Record<string, string> = {
  new: "New",
  triage: "Triage",
  assigned: "Assigned",
  in_progress: "In Progress",
  waiting_requester: "Waiting Requester",
  waiting_internal: "Waiting Internal",
  waiting_it: "Waiting IT",
  quality_review: "Quality Review",
  reopened: "Reopened",
};

const DOMAIN_OPTIONS: { value: Domain; label: string }[] = [
  { value: "operational", label: "Operational" },
  { value: "it", label: "IT" },
];

function DraggableTicket({ ticket }: { ticket: TicketSummary }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: ticket.id,
    data: { number: ticket.number, fromStatus: ticket.status_code },
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={cn(
        "rounded-xl transition-[transform,opacity,box-shadow] duration-150",
        isDragging &&
          "scale-[0.98] opacity-40 ring-2 ring-ring ring-offset-2 ring-offset-background",
      )}
      data-draggable="true"
      data-dragging={isDragging || undefined}
    >
      <TicketCard ticket={ticket} draggable />
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
        "flex h-full w-72 shrink-0 flex-col rounded-xl border bg-muted/30 p-2 transition-[transform,box-shadow,border-color] duration-150",
        isOver &&
          "scale-[1.01] border-ring ring-2 ring-ring/50 ring-offset-2 ring-offset-background",
      )}
      data-over={isOver || undefined}
    >
      <div className="mb-2 flex items-center justify-between gap-2 px-1">
        <h2 className="text-sm font-semibold">{label}</h2>
        <Badge variant="secondary" className="font-mono">
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
                <Inbox aria-hidden />
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
  const [domain, setDomain] = useState<Domain>("operational");
  const qc = useQueryClient();
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor),
  );

  const { data, isLoading, error } = useQuery({
    queryKey: ["kanban", domain],
    queryFn: () => ticketsApi.kanban(domain),
  });

  const transition = useMutation({
    mutationFn: ({ number, to }: { number: string; to: string }) =>
      ticketsApi.transition(number, to),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["kanban", domain] }),
    onError: () => toast.error("Ticket transition failed"),
  });

  const handleDragEnd = (event: DragEndEvent) => {
    const ticketId = event.active?.id as string | undefined;
    const toColumn = event.over?.id as string | undefined;
    if (!ticketId || !toColumn) return;
    const allTickets = Object.values(data?.columns ?? {}).flat();
    const ticket = allTickets.find((item) => item.id === ticketId);
    if (!ticket || ticket.status_code === toColumn) return;
    transition.mutate({ number: ticket.number, to: toColumn });
  };

  const columns = OPERATIONAL_COLUMNS;
  const columns_data = data?.columns ?? {};

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Kanban</h1>
          <p className="text-sm text-muted-foreground">
            Move tickets between workflow stages.
          </p>
        </div>
        <Field
          orientation="horizontal"
          className="w-full justify-between sm:w-auto sm:justify-start"
        >
          <FieldLabel htmlFor="kanban-domain">Domain</FieldLabel>
          <Select
            items={DOMAIN_OPTIONS}
            value={domain}
            onValueChange={(value) => {
              if (value == null) return;
              setDomain(value as Domain);
            }}
          >
            <SelectTrigger id="kanban-domain" className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {DOMAIN_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
      </div>

      {transition.isError ? (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertTitle>Ticket transition failed</AlertTitle>
          <AlertDescription>
            Transition failed: {String((transition.error as Error)?.message)}
          </AlertDescription>
        </Alert>
      ) : null}

      {isLoading ? <KanbanSkeleton /> : null}

      {error ? (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertTitle>Could not load the Kanban</AlertTitle>
          <AlertDescription>
            Check the backend and your dev token, then try again.
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

function KanbanSkeleton() {
  return (
    <div
      className="flex h-[calc(100vh-220px)] gap-3 overflow-x-auto pb-2"
      aria-label="Loading Kanban"
    >
      {OPERATIONAL_COLUMNS.map((code) => (
        <div
          key={code}
          className="flex h-full w-72 shrink-0 flex-col gap-3 rounded-xl border bg-muted/30 p-2"
        >
          <div className="flex items-center justify-between gap-2 px-1">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-5 w-8 rounded-full" />
          </div>
          <div className="flex flex-col gap-2">
            <Skeleton className="h-28 w-full rounded-xl" />
            <Skeleton className="h-28 w-full rounded-xl" />
            <Skeleton className="h-28 w-full rounded-xl" />
          </div>
        </div>
      ))}
    </div>
  );
}
