import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Clock,
  Database,
  HardDrive,
  KeyRound,
  Server,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";

interface CheckResult {
  ok: boolean;
  latency_ms: number;
  error?: string;
}

interface HealthResponse {
  status: "ok" | "degraded";
  environment: string;
  version: string;
  checks: Record<string, CheckResult>;
  total_ms: number;
}

async function fetchHealth(): Promise<HealthResponse> {
  const r = await fetch("/api/v1/health");
  if (!r.ok) throw new Error(`Health check failed: ${r.status}`);
  return r.json();
}

const CHECK_META: Record<
  string,
  { label: string; description: string; icon: React.ComponentType<{ className?: string }> }
> = {
  database: {
    label: "PostgreSQL",
    description: "Primary data store",
    icon: Database,
  },
  redis: {
    label: "Redis",
    description: "Cache + distributed locks",
    icon: Server,
  },
  minio: {
    label: "MinIO",
    description: "Object storage (S3)",
    icon: HardDrive,
  },
  keycloak: {
    label: "Keycloak",
    description: "OIDC identity provider",
    icon: KeyRound,
  },
};

export default function HealthPage() {
  const { data, isLoading, error, refetch, isRefetching, dataUpdatedAt } =
    useQuery({
      queryKey: ["health", "page"],
      queryFn: fetchHealth,
      refetchInterval: 15_000,
    });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        isRefetching={isRefetching}
        onRefresh={() => refetch()}
        dataUpdatedAt={dataUpdatedAt}
      />

      {isLoading ? (
        <SkeletonRows />
      ) : error ? (
        <ErrorState onRetry={() => refetch()} />
      ) : data ? (
        <>
          <SummaryCard data={data} />
          <div className="grid gap-3 sm:grid-cols-2">
            {Object.entries(data.checks).map(([name, check]) => (
              <CheckCard key={name} name={name} check={check} />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

function PageHeader({
  isRefetching,
  onRefresh,
  dataUpdatedAt,
}: {
  isRefetching: boolean;
  onRefresh: () => void;
  dataUpdatedAt: number;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Activity className="size-5 text-primary" />
          <h1 className="text-2xl font-semibold tracking-tight">System health</h1>
        </div>
        <p className="text-sm text-muted-foreground">
          Polled every 15 s. Dependency latencies and per-check status for the
          platform.
        </p>
      </div>
      <div className="flex items-center gap-2">
        {dataUpdatedAt > 0 ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="size-3.5" />
            Updated {new Date(dataUpdatedAt).toLocaleTimeString()}
          </span>
        ) : null}
        <Button
          variant="outline"
          onClick={onRefresh}
          disabled={isRefetching}
          data-icon
        >
          <RefreshCw
            data-icon="inline-start"
            className={cn(isRefetching && "animate-spin")}
          />
          Refresh
        </Button>
      </div>
    </div>
  );
}

function SummaryCard({ data }: { data: HealthResponse }) {
  const isOk = data.status === "ok";

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div
            className={cn(
              "grid size-12 place-items-center rounded-full",
              isOk
                ? "bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30"
                : "bg-warning/15 text-warning-foreground ring-1 ring-inset ring-warning/30",
            )}
          >
            {isOk ? (
              <CheckCircle2 className="size-6" />
            ) : (
              <AlertCircle className="size-6" />
            )}
          </div>
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <span className="text-lg font-semibold capitalize">
                {data.status}
              </span>
              <Badge
                variant="secondary"
                className={cn(
                  isOk
                    ? "bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30"
                    : "bg-warning/15 text-warning-foreground ring-1 ring-inset ring-warning/30",
                )}
              >
                {Object.values(data.checks).filter((c) => c.ok).length}/
                {Object.keys(data.checks).length} checks passing
              </Badge>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>
                Environment <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{data.environment}</code>
              </span>
              <Separator orientation="vertical" className="h-3" />
              <span>
                Version <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{data.version}</code>
              </span>
              <Separator orientation="vertical" className="h-3" />
              <span>
                Total{" "}
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                  {data.total_ms.toFixed(1)} ms
                </code>
              </span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function CheckCard({ name, check }: { name: string; check: CheckResult }) {
  const meta = CHECK_META[name] ?? {
    label: name,
    description: "",
    icon: Server,
  };
  const isOk = check.ok;

  return (
    <Card data-size="sm">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span
              className={cn(
                "grid size-9 place-items-center rounded-md",
                isOk
                  ? "bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30"
                  : "bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30",
              )}
            >
              <meta.icon className="size-4" />
            </span>
            <div>
              <CardTitle className="text-sm">{meta.label}</CardTitle>
              {meta.description ? (
                <CardDescription className="text-[11px]">
                  {meta.description}
                </CardDescription>
              ) : null}
            </div>
          </div>
          <Badge
            variant="secondary"
            className={cn(
              isOk
                ? "bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30"
                : "bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30",
            )}
          >
            {isOk ? (
              <CheckCircle2 className="size-3" />
            ) : (
              <XCircle className="size-3" />
            )}
            {isOk ? "OK" : "FAIL"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-end justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
              Latency
            </span>
            <span className="font-mono text-2xl font-semibold tabular-nums">
              {check.latency_ms.toFixed(1)}
              <span className="text-sm font-normal text-muted-foreground">
                {" "}
                ms
              </span>
            </span>
          </div>
          {check.error ? (
            <span className="max-w-[60%] text-right text-xs text-destructive">
              {check.error}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function SkeletonRows() {
  return (
    <div className="flex flex-col gap-3">
      <Skeleton className="h-24 w-full" />
      <div className="grid gap-3 sm:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-6">
        <div className="grid size-10 place-items-center rounded-full bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30">
          <AlertCircle className="size-5" />
        </div>
        <div className="flex-1">
          <p className="text-sm font-medium">Could not reach the API</p>
          <p className="text-xs text-muted-foreground">
            Is the backend running? Check that the dev compose stack is up.
          </p>
        </div>
        <Button variant="outline" onClick={onRetry} data-icon>
          <RefreshCw data-icon="inline-start" />
          Retry
        </Button>
      </CardContent>
    </Card>
  );
}
