import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  ArrowUpDown,
  Filter,
  Inbox,
  ListChecks,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { ticketsApi, type TicketSummary } from "@/lib/api";
import { TicketCard } from "./TicketCard";
import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";

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

const SORT_OPTIONS = [
  { value: "priority", label: "By priority" },
  { value: "created", label: "Newest first" },
  { value: "updated", label: "Recently updated" },
  { value: "sla", label: "SLA at risk first" },
];

const STATUS_SELECT_ITEMS = [
  { value: "all", label: "All statuses" },
  ...STATUS_OPTIONS,
];

const PRIORITY_SELECT_ITEMS = [
  { value: "all", label: "All priorities" },
  ...PRIORITY_OPTIONS.map((value) => ({ value, label: value })),
];

const EMPTY_TICKETS: TicketSummary[] = [];

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

  const items = data ?? EMPTY_TICKETS;

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
          {sorted.map((ticket) => (
            <TicketCard key={ticket.id} ticket={ticket} />
          ))}
        </div>
      )}
    </div>
  );
}

function slaScore(health: string): number {
  switch (health) {
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
  onSortChange: (sort: SortKey) => void;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Queue</h1>
          <Badge variant="secondary" className="tabular-nums">
            {count}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Live ticket list, scoped to your domain. Filters apply to the URL so
          they can be shared.
        </p>
      </div>
      <div className="flex w-full items-center gap-2 sm:w-auto">
        <Field className="min-w-0 flex-1 sm:w-44 sm:flex-none">
          <FieldLabel htmlFor="queue-sort" className="sr-only">
            Sort tickets
          </FieldLabel>
          <Select
            items={SORT_OPTIONS}
            value={sort}
            onValueChange={(value) => {
              if (value == null) return;
              onSortChange(value as SortKey);
            }}
          >
            <SelectTrigger id="queue-sort" className="w-full" data-icon>
              <ArrowUpDown data-icon="inline-start" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {SORT_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
        <Button
          variant="outline"
          onClick={onRefresh}
          disabled={isFetching}
          data-icon
        >
          {isFetching ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <RefreshCw data-icon="inline-start" />
          )}
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
  onSearch: (value: string) => void;
  status: string;
  onStatus: (value: string) => void;
  priority: string;
  onPriority: (value: string) => void;
  activeFilters: number;
  onClear: () => void;
}) {
  return (
    <FieldGroup className="grid gap-3 rounded-lg bg-card p-3 ring-1 ring-foreground/10 sm:grid-cols-[minmax(12rem,1fr)_12rem_9rem_auto] sm:items-center">
      <Field>
        <FieldLabel htmlFor="queue-search" className="sr-only">
          Search tickets
        </FieldLabel>
        <div className="relative">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            id="queue-search"
            placeholder="Search by number, title, matter reference…"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            className="pl-9"
          />
        </div>
      </Field>
      <Field>
        <FieldLabel htmlFor="queue-status" className="sr-only">
          Filter by status
        </FieldLabel>
        <Select
          items={STATUS_SELECT_ITEMS}
          value={status || "all"}
          onValueChange={(value) => {
            if (value == null) return;
            onStatus(value === "all" ? "" : value);
          }}
        >
          <SelectTrigger id="queue-status" className="w-full" data-icon>
            <Filter data-icon="inline-start" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">All statuses</SelectItem>
            </SelectGroup>
            <SelectSeparator />
            <SelectGroup>
              {STATUS_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>
      <Field>
        <FieldLabel htmlFor="queue-priority" className="sr-only">
          Filter by priority
        </FieldLabel>
        <Select
          items={PRIORITY_SELECT_ITEMS}
          value={priority || "all"}
          onValueChange={(value) => {
            if (value == null) return;
            onPriority(value === "all" ? "" : value);
          }}
        >
          <SelectTrigger id="queue-priority" className="w-full" data-icon>
            <Filter data-icon="inline-start" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              <SelectItem value="all">All priorities</SelectItem>
            </SelectGroup>
            <SelectSeparator />
            <SelectGroup>
              {PRIORITY_OPTIONS.map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>
      {activeFilters > 0 ? (
        <Button variant="ghost" size="sm" onClick={onClear} data-icon>
          <X data-icon="inline-start" />
          Clear ({activeFilters})
        </Button>
      ) : null}
    </FieldGroup>
  );
}

function QueueSkeleton() {
  return (
    <div className="grid grid-cols-tickets gap-3" aria-label="Loading tickets">
      {Array.from({ length: 6 }).map((_, index) => (
        <Card key={index} size="sm">
          <CardHeader>
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/3" />
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
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
    <Alert variant="destructive">
      <AlertCircle data-icon="inline-start" aria-hidden />
      <AlertTitle>Could not load tickets</AlertTitle>
      <AlertDescription>{message}</AlertDescription>
      <AlertAction>
        <Button variant="outline" size="sm" onClick={onRetry} data-icon>
          <RefreshCw data-icon="inline-start" />
          Retry
        </Button>
      </AlertAction>
    </Alert>
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
    <Empty className="border py-12">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Inbox data-icon="inline-start" aria-hidden />
        </EmptyMedia>
        <EmptyTitle>
          {hasFilters ? "No tickets match your filters" : "Queue is empty"}
        </EmptyTitle>
        <EmptyDescription>
          {hasFilters
            ? "Try clearing one or more filters, or capture a new request via the intake pages."
            : "Capture a call, walk-in, or web submission to get started."}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        {hasFilters ? (
          <Button variant="outline" onClick={onClear} data-icon>
            <X data-icon="inline-start" />
            Clear filters
          </Button>
        ) : (
          <Button
            render={<Link to="/intake/call" />}
            nativeButton={false}
            variant="outline"
            data-icon
          >
            <ListChecks data-icon="inline-start" />
            Capture a call
          </Button>
        )}
      </EmptyContent>
    </Empty>
  );
}
