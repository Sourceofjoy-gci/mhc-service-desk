import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  KanbanSquare,
  ListChecks,
  Phone,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/AuthProvider";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface HealthResponse {
  status: string;
  environment: string;
  version: string;
  checks: Record<string, { ok: boolean; latency_ms: number }>;
}

const WORK_ACTIONS = [
  {
    label: "Open queue",
    description: "Triage, filter, and assign active tickets.",
    to: "/tickets",
    icon: ListChecks,
  },
  {
    label: "View Kanban",
    description: "Move work through the approved workflow.",
    to: "/kanban",
    icon: KanbanSquare,
  },
  {
    label: "Capture a call",
    description: "Record a phone enquiry while speaking to the requester.",
    to: "/intake/call",
    icon: Phone,
  },
  {
    label: "Capture a walk-in",
    description: "Create a ticket for an in-person request.",
    to: "/intake/walk-in",
    icon: UserRound,
  },
] as const;

const SYSTEM_ADMINISTRATOR_MEMBERSHIPS = new Set(["system-admins", "admin"]);

async function fetchHealth(): Promise<HealthResponse> {
  return api<HealthResponse>("/health");
}

export default function HomePage() {
  const { user } = useAuth();
  const canViewPlatformStatus =
    user?.groups.some((membership) => {
      const name = membership.split("/").filter(Boolean).at(-1) ?? membership;
      return SYSTEM_ADMINISTRATOR_MEMBERSHIPS.has(name);
    }) ?? false;
  const { data, isLoading } = useQuery({
    queryKey: ["health", "home"],
    queryFn: fetchHealth,
    enabled: canViewPlatformStatus,
    refetchInterval: 30_000,
  });

  return (
    <div className="flex flex-col gap-8">
      <header className="flex max-w-3xl flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">
          Staff workspace
        </h1>
        <p className="text-pretty text-sm text-muted-foreground sm:text-base">
          Start the next staff task, then use the queue and board to keep work
          moving.
        </p>
      </header>

      <div
        className={cn(
          "grid items-start gap-6",
          canViewPlatformStatus &&
            "lg:grid-cols-[minmax(0,1.6fr)_minmax(18rem,0.8fr)]",
        )}
      >
        <Card role="region" aria-labelledby="start-work-heading">
          <CardHeader>
            <CardTitle>
              <h2 id="start-work-heading">Start work</h2>
            </CardTitle>
            <CardDescription>
              Choose the workflow that matches what you need to do now.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col">
            {WORK_ACTIONS.map((action, index) => (
              <div key={action.to}>
                {index > 0 ? <Separator /> : null}
                <Link
                  to={action.to}
                  aria-label={action.label}
                  className="group flex min-h-16 items-center gap-3 rounded-lg px-2 py-3 text-foreground no-underline transition-colors hover:bg-muted hover:no-underline focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
                    <action.icon className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">
                      {action.label}
                    </span>
                    <span className="block text-sm text-muted-foreground">
                      {action.description}
                    </span>
                  </span>
                  <ArrowRight
                    className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </Link>
              </div>
            ))}
          </CardContent>
        </Card>

        {canViewPlatformStatus ? (
          <PlatformStatus data={data} isLoading={isLoading} />
        ) : null}
      </div>

      <Alert className="border-primary/20 bg-primary/5">
        <ShieldCheck aria-hidden />
        <AlertTitle>
          <h2>Operational and IT work stay separate</h2>
        </AlertTitle>
        <AlertDescription>
          Staff only see tickets for their authorised service desk. Referrals
          pass a sanitised summary to IT without exposing operational messages
          or attachments.
        </AlertDescription>
      </Alert>

      <div className="flex flex-wrap gap-2">
        <Button
          render={<Link to="/dashboard" />}
          nativeButton={false}
          variant="outline"
          className="no-underline hover:no-underline"
        >
          View dashboard
        </Button>
        {canViewPlatformStatus ? (
          <Button
            render={<Link to="/health" />}
            nativeButton={false}
            variant="ghost"
            className="no-underline hover:no-underline"
          >
            Service health
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function PlatformStatus({
  data,
  isLoading,
}: {
  data?: HealthResponse;
  isLoading: boolean;
}) {
  const checks = data?.checks ?? {};
  const entries = [
    { key: "database", label: "PostgreSQL" },
    { key: "redis", label: "Redis" },
    { key: "minio", label: "MinIO" },
    { key: "keycloak", label: "Keycloak" },
  ];

  return (
    <Card size="sm">
      <CardHeader>
        <div className="flex items-center justify-between gap-4">
          <CardTitle>
            <h2 className="flex items-center gap-2">
              <Activity className="size-4 text-primary" aria-hidden />
              Platform status
            </h2>
          </CardTitle>
          {data ? (
            <Badge
              variant="secondary"
              className={cn(
                data.status === "ok"
                  ? "bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30"
                  : "bg-warning/20 text-warning-foreground ring-1 ring-inset ring-warning/30",
              )}
            >
              {data.status === "ok" ? "Healthy" : data.status}
            </Badge>
          ) : isLoading ? (
            <Skeleton className="h-5 w-20" />
          ) : (
            <Badge variant="destructive">Unreachable</Badge>
          )}
        </div>
        <CardDescription>
          {data
            ? `${data.environment} · v${data.version}`
            : isLoading
              ? "Checking API…"
              : "Platform status unavailable"}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {entries.map((entry) => {
          const check = checks[entry.key];
          const statusLabel = check
            ? check.ok
              ? "Healthy"
              : "Failed"
            : isLoading
              ? "Checking"
              : "Unknown";
          return (
            <div
              key={entry.key}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "size-2 rounded-full",
                    check?.ok
                      ? "bg-success"
                      : check
                        ? "bg-destructive"
                        : "bg-muted-foreground/40",
                  )}
                  aria-hidden
                />
                <span>{entry.label}</span>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span
                  className={cn(
                    "text-xs font-medium",
                    check?.ok
                      ? "text-success-foreground"
                      : check
                        ? "text-destructive"
                        : "text-muted-foreground",
                  )}
                >
                  {statusLabel}
                </span>
                {check ? (
                  <span className="font-mono text-xs text-muted-foreground">
                    {check.latency_ms.toFixed(1)} ms
                  </span>
                ) : isLoading ? (
                  <Skeleton className="h-3 w-12" />
                ) : (
                  <span className="text-xs text-muted-foreground">—</span>
                )}
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
