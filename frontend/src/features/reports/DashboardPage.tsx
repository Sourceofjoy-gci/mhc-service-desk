import { useQuery } from "@tanstack/react-query";
import { AlertCircleIcon, BarChart3Icon } from "lucide-react";
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { PriorityBadge, StatusBadge } from "@/components/domain-badges";
import { useAuth } from "@/features/auth/AuthProvider";
import PermissionPage from "@/features/auth/PermissionPage";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import {
  admittedDomains,
  ApiError,
  ticketsApi,
  type Domain,
} from "../../lib/api";

const knownPriorityCodes = new Set(["P1", "P2", "P3", "P4"]);
const knownStatusCodes = new Set([
  "new",
  "triage",
  "assigned",
  "in_progress",
  "waiting_requester",
  "waiting_internal",
  "waiting_it",
  "quality_review",
  "resolved",
  "closed",
  "cancelled",
  "rejected",
  "duplicate",
  "spam",
]);

const DASHBOARD_DOMAIN_OPTIONS = [
  { value: "operational", label: "Operational" },
  { value: "it", label: "IT" },
] as const;

export default function DashboardPage() {
  const { user } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const domains = admittedDomains(user?.groups ?? []);
  const requestedDomain = searchParams.get("domain");
  const domain = domains.includes(requestedDomain as Domain)
    ? (requestedDomain as Domain)
    : domains[0];

  useEffect(() => {
    if (!domain || requestedDomain === domain) return;
    const next = new URLSearchParams(searchParams);
    next.set("domain", domain);
    setSearchParams(next, { replace: true });
  }, [domain, requestedDomain, searchParams, setSearchParams]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard", domain],
    queryFn: () => ticketsApi.dashboard(domain!),
    enabled: Boolean(domain),
    refetchInterval: 30_000,
  });

  if (!domain) return <PermissionPage />;

  if (isLoading) {
    return <DashboardSkeleton />;
  }

  if (error instanceof ApiError && error.status === 403) {
    return <PermissionPage />;
  }

  if (error || !data) {
    return (
      <Alert variant="destructive">
        <AlertCircleIcon aria-hidden />
        <AlertTitle>Dashboard unavailable</AlertTitle>
        <AlertDescription>
          Could not load dashboard. Try again in a moment.
        </AlertDescription>
      </Alert>
    );
  }

  const d = data;
  const hasNoBreakdowns =
    d.by_priority.length === 0 && d.by_status.length === 0;

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            {domain === "it" ? "IT" : "Operational"} dashboard
          </h1>
          <p className="text-sm text-muted-foreground">
            Current ticket volumes and service-level attention points.
          </p>
        </div>
        {domains.length > 1 ? (
          <Field className="w-44">
            <FieldLabel htmlFor="dashboard-domain" className="sr-only">
              Dashboard domain
            </FieldLabel>
            <Select
              items={DASHBOARD_DOMAIN_OPTIONS}
              value={domain}
              onValueChange={(value) => {
                if (value == null) return;
                const next = new URLSearchParams(searchParams);
                next.set("domain", value);
                setSearchParams(next);
              }}
            >
              <SelectTrigger id="dashboard-domain" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  {DASHBOARD_DOMAIN_OPTIONS.map((option) => (
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

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard
          label="Open"
          description="Active tickets"
          value={d.totals.open}
        />
        <MetricCard
          label="Today"
          description="Created today"
          value={d.totals.today}
        />
        <MetricCard
          label="This week"
          description="Created this week"
          value={d.totals.this_week}
        />
        <MetricCard
          label="Unassigned"
          description="Awaiting an owner"
          value={d.unassigned}
        />
        <MetricCard
          label={domain === "it" ? "P1/P2 open" : "Breached SLA"}
          description={
            domain === "it" ? "High-priority active" : "Needs attention"
          }
          value={domain === "it" ? (d.p1p2 ?? 0) : (d.breached_sla ?? 0)}
          isDestructive={domain === "operational" && (d.breached_sla ?? 0) > 0}
        />
      </div>

      {hasNoBreakdowns ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <BarChart3Icon aria-hidden />
            </EmptyMedia>
            <EmptyTitle>No dashboard breakdowns yet</EmptyTitle>
            <EmptyDescription>
              Priority and status volumes will appear when tickets are
              available.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card className="rounded-lg!">
            <CardHeader>
              <CardTitle>
                <h2>By priority</h2>
              </CardTitle>
              <CardDescription>
                Current ticket volume by priority.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Priority</TableHead>
                    <TableHead className="text-right">Tickets</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.by_priority.map((row) => (
                    <TableRow key={row.priority}>
                      <TableCell>
                        {knownPriorityCodes.has(row.priority) ? (
                          <PriorityBadge code={row.priority} />
                        ) : (
                          row.priority
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {row.count}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card className="rounded-lg!">
            <CardHeader>
              <CardTitle>
                <h2>By status</h2>
              </CardTitle>
              <CardDescription>
                Current ticket volume by workflow status.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Tickets</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.by_status.map((row) => (
                    <TableRow key={row.status__code}>
                      <TableCell>
                        {knownStatusCodes.has(row.status__code) ? (
                          <StatusBadge
                            code={row.status__code}
                            label={row.status__name}
                          />
                        ) : (
                          row.status__name
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {row.count}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}
    </section>
  );
}

function DashboardSkeleton() {
  return (
    <section
      className="flex flex-col gap-6"
      aria-busy="true"
      aria-label="Loading dashboard"
    >
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-5 w-80" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }, (_, index) => (
          <Card key={index} className="rounded-lg!">
            <CardHeader>
              <Skeleton className="h-5 w-24" />
              <Skeleton className="h-4 w-32" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-9 w-16" />
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 2 }, (_, index) => (
          <Card key={index} className="rounded-lg!">
            <CardHeader>
              <Skeleton className="h-5 w-28" />
              <Skeleton className="h-4 w-48" />
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

function MetricCard({
  label,
  description,
  value,
  isDestructive = false,
}: {
  label: string;
  description: string;
  value: number;
  isDestructive?: boolean;
}) {
  return (
    <Card className="rounded-lg!">
      <CardHeader>
        <CardTitle>
          <h2>{label}</h2>
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <p
          className={cn(
            "text-3xl font-semibold tabular-nums",
            isDestructive && "text-destructive",
          )}
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
