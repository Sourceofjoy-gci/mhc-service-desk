import { Link } from "react-router-dom";
import { Clock, Building2, ArrowUpRight } from "lucide-react";
import type { TicketSummary } from "@/lib/api";
import {
  ChannelBadge,
  PriorityBadge,
  SlaIndicator,
  StatusBadge,
} from "@/components/domain-badges";
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface TicketCardProps {
  ticket: TicketSummary;
  draggable?: boolean;
}

export function TicketCard({ ticket, draggable = false }: TicketCardProps) {
  return (
    <Link
      to={`/tickets/${ticket.number}`}
      data-ticket-number={ticket.number}
      data-draggable={draggable ? "true" : undefined}
      className="group block focus-visible:outline-none"
    >
      <Card
        className={cn(
          "h-full transition-all",
          "group-hover:border-primary/50 group-hover:shadow-md group-hover:-translate-y-px",
          "group-focus-visible:ring-2 group-focus-visible:ring-ring",
        )}
      >
        <CardHeader className="gap-2">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-[11px] font-medium text-muted-foreground tracking-tight">
              {ticket.number}
            </span>
            <div className="flex items-center gap-1.5">
              <PriorityBadge code={ticket.priority} />
              <ChannelBadge channel={ticket.channel} />
            </div>
          </div>
          <h3 className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
            {ticket.title}
          </h3>
        </CardHeader>
        <CardContent className="flex flex-col gap-2.5 text-xs text-muted-foreground">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-medium text-foreground/80">
              {ticket.requester_name}
            </span>
            <StatusBadge code={ticket.status_code} label={ticket.status_public} />
          </div>
          <div className="flex items-center justify-between gap-2 text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Building2 className="size-3" />
              {ticket.office_code}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock className="size-3" />
              {ticket.age_hours.toFixed(1)}h
            </span>
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-border/60 pt-2">
            <SlaIndicator health={ticket.sla_health} />
            <ArrowUpRight className="size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
