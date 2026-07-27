import { useQuery } from "@tanstack/react-query";
import { useEffect, type MouseEvent as ReactMouseEvent } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
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
import { useAuth } from "@/features/auth/AuthProvider";
import PermissionPage from "@/features/auth/PermissionPage";
import {
  domainCapabilities,
  ticketsApi,
  type Domain,
  type TicketSummary,
} from "@/lib/api";
import { cursorFromPageLink, type Page } from "@/lib/collections";
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
];

const DOMAIN_OPTIONS = [
  { value: "operational", label: "Operational" },
  { value: "it", label: "IT" },
] as const;

const STATUS_SELECT_ITEMS = [
  { value: "all", label: "All statuses" },
  ...STATUS_OPTIONS,
];

const PRIORITY_SELECT_ITEMS = [
  { value: "all", label: "All priorities" },
  ...PRIORITY_OPTIONS.map((value) => ({ value, label: value })),
];

const EMPTY_PAGE: Page<TicketSummary> = {
  next: null,
  previous: null,
  results: [],
};

type SortKey = "priority" | "created" | "updated";

const SORT_KEYS = new Set<SortKey>(["priority", "created", "updated"]);
const STATUS_KEYS = new Set(STATUS_OPTIONS.map(({ value }) => value));
const PRIORITY_KEYS = new Set<string>(PRIORITY_OPTIONS);

export default function QueuePage() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { queueDomains: domains } = domainCapabilities(user?.groups ?? []);
  const requestedDomain = searchParams.get("domain");
  const domain = domains.includes(requestedDomain as Domain)
    ? (requestedDomain as Domain)
    : domains[0];
  const requestedStatus = searchParams.get("status");
  const status =
    requestedStatus && STATUS_KEYS.has(requestedStatus) ? requestedStatus : "";
  const requestedPriority = searchParams.get("priority");
  const priority =
    requestedPriority && PRIORITY_KEYS.has(requestedPriority)
      ? requestedPriority
      : "";
  const search = searchParams.get("search") ?? "";
  const requestedSort = searchParams.get("sort") as SortKey | null;
  const sort =
    requestedSort && SORT_KEYS.has(requestedSort) ? requestedSort : "priority";
  const cursor = searchParams.get("cursor") ?? "";
  const currentSearch = searchParams.toString();
  const canonicalParams = new URLSearchParams(searchParams);
  let hasStateCanonicalization = false;

  if (
    requestedDomain !== null &&
    (searchParams.getAll("domain").length !== 1 || requestedDomain !== domain)
  ) {
    if (domain) canonicalParams.set("domain", domain);
    else canonicalParams.delete("domain");
    hasStateCanonicalization = true;
  }
  if (
    searchParams.has("status") &&
    (searchParams.getAll("status").length !== 1 || !status)
  ) {
    if (status) canonicalParams.set("status", status);
    else canonicalParams.delete("status");
    hasStateCanonicalization = true;
  }
  if (
    searchParams.has("priority") &&
    (searchParams.getAll("priority").length !== 1 || !priority)
  ) {
    if (priority) canonicalParams.set("priority", priority);
    else canonicalParams.delete("priority");
    hasStateCanonicalization = true;
  }
  if (
    searchParams.has("sort") &&
    (searchParams.getAll("sort").length !== 1 || sort !== requestedSort)
  ) {
    canonicalParams.set("sort", sort);
    hasStateCanonicalization = true;
  }
  if (
    searchParams.has("cursor") &&
    (searchParams.getAll("cursor").length !== 1 || !cursor)
  ) {
    if (cursor) canonicalParams.set("cursor", cursor);
    else canonicalParams.delete("cursor");
  }
  if (hasStateCanonicalization) canonicalParams.delete("cursor");
  const canonicalSearch = canonicalParams.toString();
  const needsCanonicalization = canonicalSearch !== currentSearch;

  useEffect(() => {
    if (!needsCanonicalization) return;
    setSearchParams(new URLSearchParams(canonicalSearch), { replace: true });
  }, [canonicalSearch, needsCanonicalization, setSearchParams]);

  const updateParam = (
    key: "domain" | "status" | "priority" | "search" | "sort",
    value: string,
    replace = false,
  ) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("cursor");
    setSearchParams(next, { replace });
  };

  const params: Record<string, string> = {};
  if (domain) params.domain = domain;
  if (status) params.status = status;
  if (priority) params.priority = priority;
  if (search) params.search = search;
  params.sort = sort;
  if (cursor) params.cursor = cursor;

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["tickets", params],
    queryFn: () => ticketsApi.list(params),
    enabled: Boolean(domain) && !needsCanonicalization,
  });

  const page = data ?? EMPTY_PAGE;
  const items = page.results;
  const activeFilters = [requestedDomain, status, priority, search].filter(
    Boolean,
  ).length;

  const clearFilters = () => {
    setSearchParams(new URLSearchParams({ sort }));
  };

  const paginate = (serverCursor: string | null) => {
    if (!serverCursor) return;
    const next = new URLSearchParams(searchParams);
    next.set("cursor", serverCursor);
    setSearchParams(next);
  };

  const previousCursor = cursorFromPageLink(page.previous, cursor || null);
  const nextCursor = cursorFromPageLink(page.next, cursor || null);

  const retainQueueLocation = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    const target = event.target as Element;
    const ticketLink = target.closest<HTMLAnchorElement>(
      "a[data-ticket-number]",
    );
    if (!ticketLink) return;
    event.preventDefault();
    navigate(ticketLink.getAttribute("href") ?? ticketLink.pathname, {
      state: { returnTo: `${location.pathname}${location.search}` },
    });
  };

  if (!domain) return <PermissionPage />;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        count={items.length}
        isFetching={isFetching}
        onRefresh={() => refetch()}
        sort={sort}
        onSortChange={(value) => updateParam("sort", value)}
      />

      <FilterBar
        search={search}
        onSearch={(value) => updateParam("search", value, true)}
        status={status}
        onStatus={(value) => updateParam("status", value)}
        priority={priority}
        onPriority={(value) => updateParam("priority", value)}
        domain={domain}
        domains={domains}
        onDomain={(value) => updateParam("domain", value)}
        activeFilters={activeFilters}
        onClear={clearFilters}
      />

      {error ? (
        <ErrorState
          onRetry={() => refetch()}
          message="Could not load tickets. Make sure the backend is running and you have a valid dev token (VITE_DEV_AUTH=1)."
        />
      ) : isLoading ? (
        <QueueSkeleton />
      ) : items.length === 0 ? (
        <EmptyState hasFilters={activeFilters > 0} onClear={clearFilters} />
      ) : (
        <div
          className="grid grid-cols-tickets gap-3"
          onClickCapture={retainQueueLocation}
        >
          {items.map((ticket) => (
            <TicketCard key={ticket.id} ticket={ticket} />
          ))}
        </div>
      )}

      <Pagination
        previous={previousCursor}
        next={nextCursor}
        onNavigate={paginate}
      />
    </div>
  );
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
  domain,
  domains,
  onDomain,
  activeFilters,
  onClear,
}: {
  search: string;
  onSearch: (value: string) => void;
  status: string;
  onStatus: (value: string) => void;
  priority: string;
  onPriority: (value: string) => void;
  domain: Domain | undefined;
  domains: Domain[];
  onDomain: (value: Domain) => void;
  activeFilters: number;
  onClear: () => void;
}) {
  return (
    <FieldGroup className="grid gap-3 rounded-lg bg-card p-3 ring-1 ring-foreground/10 sm:grid-cols-[minmax(12rem,1fr)_repeat(3,minmax(8rem,auto))_auto] sm:items-center">
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
      {domains.length > 1 ? (
        <Field>
          <FieldLabel htmlFor="queue-domain" className="sr-only">
            Domain
          </FieldLabel>
          <Select
            items={DOMAIN_OPTIONS}
            value={domain}
            onValueChange={(value) => {
              if (value == null) return;
              onDomain(value as Domain);
            }}
          >
            <SelectTrigger id="queue-domain" className="w-full">
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
      ) : null}
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

function Pagination({
  previous,
  next,
  onNavigate,
}: {
  previous: string | null;
  next: string | null;
  onNavigate: (serverLink: string | null) => void;
}) {
  if (!previous && !next) return null;

  return (
    <nav
      aria-label="Queue pagination"
      className="flex items-center justify-between border-t pt-4"
    >
      <Button
        variant="outline"
        disabled={!previous}
        onClick={() => onNavigate(previous)}
      >
        Previous
      </Button>
      <p className="text-xs text-muted-foreground">More queue results</p>
      <Button
        variant="outline"
        disabled={!next}
        onClick={() => onNavigate(next)}
      >
        Next
      </Button>
    </nav>
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
