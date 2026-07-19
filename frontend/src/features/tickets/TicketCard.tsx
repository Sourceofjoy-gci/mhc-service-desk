import { Link } from "react-router-dom";
import type { TicketSummary } from "../../lib/api";
import { clsx } from "clsx";

const priorityColors: Record<string, string> = {
  P1: "bg-red-100 text-red-800",
  P2: "bg-amber-100 text-amber-800",
  P3: "bg-blue-100 text-blue-800",
  P4: "bg-ink-100 text-ink-700",
};

const slaColors: Record<string, string> = {
  on_track: "text-green-700",
  at_risk: "text-amber-700",
  breached: "text-red-700",
  paused: "text-ink-500",
  none: "text-ink-400",
};

export function TicketCard({ ticket, draggable = false }: { ticket: TicketSummary; draggable?: boolean }) {
  return (
    <Link
      to={`/tickets/${ticket.number}`}
      className="block rounded-md border border-ink-100 bg-white p-3 text-sm shadow-sm hover:border-brand-500 hover:shadow no-underline"
      data-ticket-number={ticket.number}
      data-draggable={draggable ? "true" : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-ink-500">{ticket.number}</span>
        <span
          className={clsx(
            "rounded-full px-2 py-0.5 text-xs font-medium",
            priorityColors[ticket.priority] ?? priorityColors.P4,
          )}
        >
          {ticket.priority}
        </span>
      </div>
      <div className="mt-1 line-clamp-2 font-medium text-ink-900">{ticket.title}</div>
      <div className="mt-2 flex items-center justify-between text-xs text-ink-500">
        <span>{ticket.requester_name}</span>
        <span className={slaColors[ticket.sla_health]}>
          {ticket.sla_health === "on_track" ? "on track" : ticket.sla_health.replace("_", " ")}
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between text-xs text-ink-500">
        <span>{ticket.office_code}</span>
        <span>{ticket.age_hours.toFixed(1)}h</span>
      </div>
    </Link>
  );
}
