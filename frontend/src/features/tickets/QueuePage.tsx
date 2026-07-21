import { useQuery } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  Search,
  RefreshCw,
  Inbox,
  Filter,
  X,
  AlertCircle,
  ListChecks,
  ArrowUpDown,
} from "lucide-react";
import { ticketsApi, type TicketSummary } from "@/lib/api";
import { TicketCard } from "./TicketCard";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

const STATUS_OPTIONS = [
  { value: "new", label: "New" },
  { value: "triage", label: "Triage" },
  { value: "assigned", label: "Assigned" },
  { value: "in_progress", label: "In progress" },
  { value: "waiting_requester", label: "Waiting on requester" },
  { value: "waiting_internal", label: "Waiting internal" },
  { value: "waiting_it", label: "Waiting on IT" },
  { value: "quality_review", label: "Quality review" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" },
];

const PRIORITY_OPTIONS = ["P1", "P2", "P3", "P4"] as const;

type SortKey = "priority" | "created" | "updated" | "sla";

export default function QueuePage() {
  const [status, setStatus] = useState<string>("");
  const [priority, setPriority] = useState<string>("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("priority");

  const params: Record<string, string> = {};
  if (status) params.status = status;
  if (priority) params.priority = priority;
  if (search) params.search = search;

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["tickets", params],
    queryFn: () => ticketsApi.list(params),
  });

  const items: TicketSummary[] = data ?? [];

  const sorted = useMemo(() => {
    const arr = [...items];
    const priorityOrder: Record<string, number> = {
      P1: 0,
      P2: 1,
      P3: 2,
      P4: 3,
    };
    arr.sort((a, b) => {
      switch (sort) {
        case "priority":
          return (
            (priorityOrder[a.priority] ?? 9) - (priorityOrder[b.priority] ?? 9)
          );
        case "created":
          return b.created_at.localeCompare(a.created_at);
        case "updated":
          return b.updated_at.localeCompare(a.updated_at);
        case "sla":
          return slaScore(a.sla_health) - slaScore(b.sla_health);
      }
    });
    return arr;
  }, [items, sort]);

  const activeFilters = [status, priority, search].filter(Boolean).length;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        count={items.length}
        isFetching={isFetching}
        onRefresh={() => refetch()}
        sort={sort}
        onSortChange={setSort}
      />

      <FilterBar
        search={search}
        onSearch={setSearch}
        status={status}
        onStatus={setStatus}
        priority={priority}
        onPriority={setPriority}
        activeFilters={activeFilters}
        onClear={() => {
          setStatus("");
          setPriority("");
          setSearch("");
        }}
      />

      {error ? (
        <ErrorState
          onRetry={() => refetch()}
          message="Could not load tickets. Make sure the backend is running and you have a valid dev token (VITE_DEV_AUTH=1)."
        />
      ) : isLoading ? (
        <QueueSkeleton />
      ) : sorted.length === 0 ? (
        <EmptyState
          hasFilters={activeFilters > 0}
          onClear={() => {
            setStatus("");
            setPriority("");
            setSearch("");
          }}
        />
      ) : (
        <div className="grid grid-cols-tickets gap-3">
          {sorted.map((t) => (
            <TicketCard key={t.id} ticket={t} />
          ))}
        </div>
      )}
    </div>
  );
}

function slaScore(h: string): number {
  switch (h) {
    case "breached":
      return 0;
    case "at_risk":
      return 1;
    case "on_track":
      return 2;
    case "paused":
      return 3;
    default:
      return 4;
  }
}

function PageHeader({
  count,
  isFetching,
  onRefresh,
  sort,
  onSortChange,
}: {
  count: number;
  isFetching: boolean;
  onRefresh: () => void;
  sort: SortKey;
  onSortChange: (s: SortKey) => void;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Queue</h1>
          <Badge variant="secondary" className="font-mono">
            {count}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Live ticket list, scoped to your domain. Filters apply to the URL so
          they can be shared.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Select
          value={sort}
          onValueChange={(v) => { if (v == null) return; onSortChange(v as SortKey) }}
        >
          <SelectTrigger className="w-44" data-icon>
            <ArrowUpDown data-icon="inline-start" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="priority">By priority</SelectItem>
            <SelectItem value="created">Newest first</SelectItem>
            <SelectItem value="updated">Recently updated</SelectItem>
            <SelectItem value="sla">SLA at risk first</SelectItem>
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          onClick={onRefresh}
          disabled={isFetching}
          data-icon
        >
          <RefreshCw
            data-icon="inline-start"
            className={cn(isFetching && "animate-spin")}
          />
          Refresh
        </Button>
      </div>
    </div>
  );
}

function FilterBar({
  search,
  onSearch,
  status,
  onStatus,
  priority,
  onPriority,
  activeFilters,
  onClear,
}: {
  search: string;
  onSearch: (v: string) => void;
  status: string;
  onStatus: (v: string) => void;
  priority: string;
  onPriority: (v: string) => void;
  activeFilters: number;
  onClear: () => void;
}) {
  return (
    <Card data-size="sm">
      <CardContent className="flex flex-col gap-3 p-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            placeholder="Search by number, title, matter reference…"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            className="pl-8"
          />
        </div>
        <Select
          value={status || "all"}
          onValueChange={(v) => { if (v == null) return; onStatus(v === "all" ? "" : v) }}
        >
          <SelectTrigger className="sm:w-48" data-icon>
            <Filter data-icon="inline-start" />
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <Separator />
            {STATUS_OPTIONS.map((s) => (
              <SelectItem key={s.value} value={s.value}>
                {s.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={priority || "all"}
          onValueChange={(v) => { if (v == null) return; onPriority(v === "all" ? "" : v) }}
        >
          <SelectTrigger className="sm:w-36" data-icon>
            <Filter data-icon="inline-start" />
            <SelectValue placeholder="All priorities" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All priorities</SelectItem>
            <Separator />
            {PRIORITY_OPTIONS.map((p) => (
              <SelectItem key={p} value={p}>
                {p}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {activeFilters > 0 ? (
          <Button variant="ghost" size="sm" onClick={onClear} data-icon>
            <X data-icon="inline-start" />
            Clear ({activeFilters})
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

function QueueSkeleton() {
  return (
    <div className="grid grid-cols-tickets gap-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i}>
          <CardHeader>
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/3" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-3 w-full" />
            <Skeleton className="mt-2 h-3 w-2/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center">
        <div className="grid size-10 shrink-0 place-items-center rounded-full bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30">
          <AlertCircle className="size-5" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium">Could not load tickets</p>
          <p className="text-xs text-muted-foreground">{message}</p>
        </div>
        <Button variant="outline" onClick={onRetry} data-icon>
          <RefreshCw data-icon="inline-start" />
          Retry
        </Button>
      </CardContent>
    </Card>
  );
}

function EmptyState({
  hasFilters,
  onClear,
}: {
  hasFilters: boolean;
  onClear: () => void;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <div className="grid size-12 place-items-center rounded-full bg-muted text-muted-foreground">
          <Inbox className="size-5" />
        </div>
        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium">
            {hasFilters ? "No tickets match your filters" : "Queue is empty"}
          </p>
          <p className="max-w-sm text-xs text-muted-foreground">
            {hasFilters
              ? "Try clearing one or more filters, or capture a new request via the intake pages."
              : "Capture a call, walk-in, or web submission to get started."}
          </p>
        </div>
        {hasFilters ? (
          <Button variant="outline" onClick={onClear} data-icon>
            <X data-icon="inline-start" />
            Clear filters
          </Button>
        ) : (
          <Button render={<Link to="/intake/call" />} variant="outline" data-icon>
            <ListChecks data-icon="inline-start" />
            Capture a call
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
