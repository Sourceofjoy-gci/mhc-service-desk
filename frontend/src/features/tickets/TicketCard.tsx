import { Link, useLocation } from "react-router-dom";
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
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

interface TicketCardProps {
  ticket: TicketSummary;
  draggable?: boolean;
}

export function TicketCard({ ticket, draggable = false }: TicketCardProps) {
  const location = useLocation();
  const returnTo = `${location.pathname}${location.search}`;

  return (
    <Link
      to={`/tickets/${ticket.number}`}
      state={{ returnTo }}
      data-ticket-number={ticket.number}
      data-draggable={draggable ? "true" : undefined}
      className="group block text-card-foreground no-underline hover:no-underline focus-visible:outline-none"
    >
      <Card
        size="sm"
        className={cn(
          "h-full transition-transform group-hover:-translate-y-1",
          "group-focus-visible:ring-3 group-focus-visible:ring-ring/50",
        )}
      >
        <CardHeader className="gap-2">
          <div className="flex items-center justify-between gap-2">
            <CardDescription>
              <span className="font-mono text-[11px] font-medium tracking-tight">
                {ticket.number}
              </span>
            </CardDescription>
            <div className="flex items-center gap-2">
              <PriorityBadge code={ticket.priority} />
              <ChannelBadge channel={ticket.channel} />
            </div>
          </div>
          <CardTitle className="line-clamp-2">
            <h3>{ticket.title}</h3>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-xs text-muted-foreground">
          <dl className="grid grid-cols-2 gap-x-2 gap-y-3">
            <div className="min-w-0">
              <dt className="sr-only">Requester</dt>
              <dd className="truncate font-medium text-foreground/80">
                {ticket.requester_name}
              </dd>
            </div>
            <div className="justify-self-end">
              <dt className="sr-only">Status</dt>
              <dd>
                <StatusBadge
                  code={ticket.status_code}
                  label={ticket.status_public}
                />
              </dd>
            </div>
            <div>
              <dt className="sr-only">Office</dt>
              <dd className="inline-flex items-center gap-2">
                <Building2 className="size-3" aria-hidden />
                {ticket.office_code}
              </dd>
            </div>
            <div className="justify-self-end">
              <dt className="sr-only">Age</dt>
              <dd className="inline-flex items-center gap-2">
                <Clock className="size-3" aria-hidden />
                <time
                  dateTime={`PT${ticket.age_hours}H`}
                  aria-label={`${ticket.age_hours.toFixed(1)} hours old`}
                >
                  {ticket.age_hours.toFixed(1)}h
                </time>
              </dd>
            </div>
          </dl>
          <Separator />
          <div className="flex items-center justify-between gap-2">
            <SlaIndicator health={ticket.sla_health} />
            <ArrowUpRight className="size-4" aria-hidden />
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
