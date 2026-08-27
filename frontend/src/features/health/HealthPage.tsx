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
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const SUCCESS_BADGE_CLASS = "bg-success text-success-foreground";
const WARNING_BADGE_CLASS = "bg-warning text-warning-foreground";

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
  return api<HealthResponse>("/health", { auth: false });
}

const CHECK_META: Record<
  string,
  {
    label: string;
    description: string;
    icon: React.ComponentType<{ className?: string }>;
  }
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
          <h1 className="text-2xl font-semibold tracking-tight">
            System health
          </h1>
        </div>
        <p className="text-sm text-muted-foreground">
          Polled every 15 s. Dependency latencies and per-check status for the
          platform.
        </p>
      </div>
      <div className="flex items-center gap-2">
        {dataUpdatedAt > 0 ? (
          <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="size-4" />
            Updated {new Date(dataUpdatedAt).toLocaleTimeString()}
          </span>
        ) : null}
        <Button variant="outline" onClick={onRefresh} disabled={isRefetching}>
          {isRefetching ? (
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

function SummaryCard({ data }: { data: HealthResponse }) {
  const isOk = data.status === "ok";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="grid size-10 place-items-center rounded-lg bg-muted text-primary">
            <Activity />
          </div>
          <div>
            <CardTitle>
              <h2>Platform status</h2>
            </CardTitle>
            <CardDescription>
              {Object.values(data.checks).filter((check) => check.ok).length}/
              {Object.keys(data.checks).length} checks passing
            </CardDescription>
          </div>
        </div>
        <CardAction>
          <Badge
            variant="secondary"
            className={cn(isOk ? SUCCESS_BADGE_CLASS : WARNING_BADGE_CLASS)}
          >
            {isOk ? "Operational" : "Degraded"}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div className="flex flex-col gap-1">
            <dt className="text-muted-foreground">Environment</dt>
            <dd className="font-mono tabular-nums">{data.environment}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-muted-foreground">Version</dt>
            <dd className="font-mono tabular-nums">{data.version}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="text-muted-foreground">Total</dt>
            <dd className="font-mono tabular-nums">
              {data.total_ms.toFixed(1)} ms
            </dd>
          </div>
        </dl>
        {!isOk ? (
          <Alert>
            <AlertCircle />
            <AlertTitle>System status is degraded</AlertTitle>
            <AlertDescription>
              One or more dependency checks need attention.
            </AlertDescription>
          </Alert>
        ) : null}
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
    <Card size="sm">
      <CardHeader>
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-lg bg-muted text-muted-foreground">
            <meta.icon />
          </span>
          <div>
            <CardTitle>
              <h2>{meta.label}</h2>
            </CardTitle>
            {meta.description ? (
              <CardDescription>{meta.description}</CardDescription>
            ) : null}
          </div>
        </div>
        <CardAction>
          <Badge
            variant={isOk ? "secondary" : "destructive"}
            className={cn(isOk && SUCCESS_BADGE_CLASS)}
          >
            {isOk ? <CheckCircle2 aria-hidden /> : <XCircle aria-hidden />}
            {isOk ? "OK" : "FAIL"}
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent>
        <div className="flex items-end justify-between gap-2">
          <div className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wider text-muted-foreground">
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
    <div className="flex flex-col items-start gap-4">
      <Alert variant="destructive">
        <AlertCircle />
        <AlertTitle>Could not reach the API</AlertTitle>
        <AlertDescription>
          Is the backend running? Check that the dev compose stack is up.
        </AlertDescription>
      </Alert>
      <Button variant="outline" onClick={onRetry}>
        <RefreshCw data-icon="inline-start" />
        Retry
      </Button>
    </div>
  );
}
