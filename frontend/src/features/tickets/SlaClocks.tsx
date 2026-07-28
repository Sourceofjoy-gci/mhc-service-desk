import { Clock3 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SlaClock, TicketDetail } from "@/lib/api";

interface SlaClocksProps {
  clocks: TicketDetail["sla_clocks"];
}

const CLOCKS: Array<{
  key: keyof TicketDetail["sla_clocks"];
  label: string;
}> = [
  { key: "first_response", label: "First response" },
  { key: "resolution", label: "Resolution" },
];

const STATE_LABELS: Record<SlaClock["state"], string> = {
  not_started: "Not started",
  running: "Running",
  paused: "Paused",
  met: "Met",
  breached: "Breached",
};

function formatDuration(seconds: number) {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  if (totalSeconds < 60) return "less than 1 minute";

  const totalMinutes = Math.floor(totalSeconds / 60);
  const days = Math.floor(totalMinutes / (24 * 60));
  const hours = Math.floor((totalMinutes % (24 * 60)) / 60);
  const minutes = totalMinutes % 60;
  const parts: string[] = [];

  if (days > 0) parts.push(`${days} ${days === 1 ? "day" : "days"}`);
  if (hours > 0) parts.push(`${hours} ${hours === 1 ? "hour" : "hours"}`);
  if (minutes > 0 && parts.length < 2) {
    parts.push(`${minutes} ${minutes === 1 ? "minute" : "minutes"}`);
  }
  return parts.slice(0, 2).join(" ");
}

function durationLabel(clock: SlaClock) {
  if (clock.state === "breached") {
    return `${formatDuration(clock.overdue_seconds)} overdue`;
  }
  if (clock.state === "met") return "Target met";
  if (clock.state === "not_started") return "Clock not started";
  return `${formatDuration(clock.remaining_seconds)} remaining`;
}

function stateClassName(state: SlaClock["state"]) {
  if (state === "breached") return "border-destructive/30 text-destructive";
  if (state === "paused") {
    return "border-amber-300 bg-amber-50/70 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300";
  }
  if (state === "met") {
    return "border-emerald-300 text-emerald-700 dark:border-emerald-800 dark:text-emerald-300";
  }
  return "border-border text-foreground";
}

export function SlaClocks({ clocks }: SlaClocksProps) {
  return (
    <section className="space-y-3" aria-labelledby="sla-heading">
      <div>
        <h2 id="sla-heading" className="text-base font-semibold">
          Service targets
        </h2>
        <p className="text-sm text-muted-foreground">
          Current clocks calculated by the service policy.
        </p>
      </div>

      <ul className="divide-y divide-border border-y border-border">
        {CLOCKS.map(({ key, label }) => {
          const clock = clocks[key];
          const stateLabel = STATE_LABELS[clock.state];
          return (
            <li
              key={key}
              aria-label={`${label} SLA: ${clock.state}`}
              className={cn(
                "flex items-start justify-between gap-4 border-l-2 px-3 py-3 first:border-t-0",
                stateClassName(clock.state),
              )}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Clock3 className="size-4 shrink-0" aria-hidden />
                  <span className="text-sm font-medium">{label}</span>
                </div>
                {clock.due_at ? (
                  <time
                    dateTime={clock.due_at}
                    className="mt-1 block text-xs text-muted-foreground"
                  >
                    Due{" "}
                    {new Intl.DateTimeFormat(undefined, {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(clock.due_at))}
                  </time>
                ) : null}
              </div>
              <div className="shrink-0 text-right">
                <span className="text-xs font-semibold uppercase tracking-wide">
                  {stateLabel}
                </span>
                <span className="mt-0.5 block text-sm">
                  {durationLabel(clock)}
                </span>
              </div>
              <span className="sr-only">
                {label} SLA is {clock.state}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
