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
import { ticketsApi, type Domain, type TicketSummary } from "../../lib/api";
import { TicketCard } from "./TicketCard";
import { clsx } from "clsx";

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
      style={{ opacity: isDragging ? 0.4 : 1 }}
      data-draggable="true"
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
      className={clsx(
        "flex h-full w-72 shrink-0 flex-col rounded-md border bg-ink-50/50 p-2",
        isOver ? "border-brand-500 bg-brand-50" : "border-ink-100",
      )}
    >
      <div className="mb-2 flex items-center justify-between px-1">
        <h3 className="text-sm font-semibold text-ink-700">{label}</h3>
        <span className="rounded-full bg-ink-100 px-2 py-0.5 text-xs text-ink-500">
          {tickets.length}
        </span>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto">
        {tickets.map((t) => (
          <DraggableTicket key={t.id} ticket={t} />
        ))}
        {tickets.length === 0 && (
          <p className="px-1 py-2 text-xs text-ink-400">No tickets</p>
        )}
      </div>
    </div>
  );
}

export default function KanbanPage() {
  const [domain, setDomain] = useState<Domain>("operational");
  const qc = useQueryClient();
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor));

  const { data, isLoading, error } = useQuery({
    queryKey: ["kanban", domain],
    queryFn: () => ticketsApi.kanban(domain),
  });

  const transition = useMutation({
    mutationFn: ({ number, to }: { number: string; to: string }) =>
      ticketsApi.transition(number, to),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["kanban", domain] }),
  });

  const handleDragEnd = (e: DragEndEvent) => {
    const ticketId = e.active?.id as string | undefined;
    const toColumn = e.over?.id as string | undefined;
    if (!ticketId || !toColumn) return;
    const allTickets = Object.values(data?.columns ?? {}).flat();
    const ticket = allTickets.find((t) => t.id === ticketId);
    if (!ticket || ticket.status_code === toColumn) return;
    transition.mutate({ number: ticket.number, to: toColumn });
  };

  const columns = OPERATIONAL_COLUMNS;
  const columns_data = data?.columns ?? {};

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Kanban</h1>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-ink-500">Domain</span>
          <select
            value={domain}
            onChange={(e) => setDomain(e.target.value as Domain)}
            className="rounded-md border border-ink-100 bg-white px-2 py-1"
          >
            <option value="operational">Operational</option>
            <option value="it">IT</option>
          </select>
        </div>
      </div>

      {transition.isError && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Transition failed: {String((transition.error as Error)?.message)}
        </div>
      )}

      {isLoading && <p className="text-ink-500">Loading…</p>}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Could not load the Kanban. Check the backend and your dev token.
        </div>
      )}

      {data && (
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
      )}
    </section>
  );
}
