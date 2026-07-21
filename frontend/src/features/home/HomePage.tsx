import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  Globe,
  HeartPulse,
  KanbanSquare,
  LayoutDashboard,
  ListChecks,
  Mail,
  Phone,
  Shield,
  Smartphone,
  Users,
  Workflow,
} from "lucide-react";
import { Link } from "react-router-dom";
import { BrandLockup } from "@/components/brand";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

// health fetch is inline to avoid pulling the api lib here
interface HealthResponse {
  status: string;
  environment: string;
  version: string;
  checks: Record<string, { ok: boolean; latency_ms: number }>;
}

async function fetchHealth(): Promise<HealthResponse> {
  const r = await fetch("/api/v1/health");
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export default function HomePage() {
  const { data, isLoading } = useQuery({
    queryKey: ["health", "home"],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  });

  return (
    <div className="flex flex-col gap-10">
      <Hero data={data} isLoading={isLoading} />
      <DomainSeparation />
      <Channels />
      <Operations />
      <Cta />
    </div>
  );
}

function Hero({
  data,
  isLoading,
}: {
  data?: HealthResponse;
  isLoading: boolean;
}) {
  return (
    <section className="relative overflow-hidden rounded-2xl bg-primary p-6 text-primary-foreground sm:p-10">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-30"
        style={{
          backgroundImage:
            "radial-gradient(circle at 85% 15%, var(--gold), transparent 38%), radial-gradient(circle at 10% 100%, var(--background), transparent 45%)",
        }}
      />
      <div className="relative grid gap-8 lg:grid-cols-[1.4fr_1fr] lg:items-center">
        <div className="flex flex-col gap-6">
          <Badge variant="secondary" className="w-fit">
            <Shield data-icon="inline-start" />
            MHC Unified e-Ticketing · M2–M6 ready
          </Badge>
          <div className="flex flex-col gap-3">
            <h1 className="text-balance text-3xl font-semibold tracking-tight sm:text-4xl lg:text-5xl">
              Capture every request.
              <br />
              <span className="text-gold">Route with rigour.</span>
            </h1>
            <p className="max-w-2xl text-pretty text-base text-primary-foreground/80 sm:text-lg">
              Operational and IT service desks with strict separation. Every
              request becomes a traceable ticket with Kanban workflow, SLA
              tracking, audit trail, and a requester-safe public entry point.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to="/tickets"
              className={cn(
                buttonVariants({ variant: "secondary" }),
                "no-underline hover:no-underline",
              )}
            >
              Open the queue
              <ArrowRight data-icon="inline-end" />
            </Link>
            <Link
              to="/kanban"
              className={cn(
                buttonVariants({ variant: "outline" }),
                "no-underline hover:no-underline",
              )}
            >
              <KanbanSquare data-icon="inline-start" />
              Kanban board
            </Link>
            <Link
              to="/public"
              className={cn(
                buttonVariants({ variant: "ghost" }),
                "text-primary-foreground no-underline hover:bg-primary-foreground/10 hover:text-primary-foreground hover:no-underline",
              )}
            >
              <Globe data-icon="inline-start" />
              Public form
            </Link>
          </div>
        </div>

        <PlatformStatus data={data} isLoading={isLoading} />
      </div>
    </section>
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
    <Card size="sm" className="self-start lg:self-center">
      <CardHeader>
        <div className="flex items-center justify-between gap-4">
          <CardTitle className="flex items-center gap-2">
            <Activity className="size-4 text-primary" aria-hidden />
            Platform status
          </CardTitle>
          {data ? (
            <Badge
              variant="secondary"
              className={cn(
                data.status === "ok"
                  ? "bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30"
                  : "bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30",
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
          {data ? `${data.environment} · v${data.version}` : "Pinging API…"}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {entries.map((entry) => {
          const check = checks[entry.key];
          return (
            <div
              key={entry.key}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "size-1.5 rounded-full",
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
          );
        })}
      </CardContent>
    </Card>
  );
}

function DomainSeparation() {
  return (
    <section className="flex flex-col gap-4">
      <SectionHeader
        eyebrow="Two service desks, one platform"
        title="Strict OP/IT separation"
        description="Operational agents and IT engineers work in the same application, but they never see each other's tickets. The sanitised IT-child pattern lets a referrer pass context without leaking content."
      />
      <div className="grid gap-6 md:grid-cols-2">
        <article className="flex items-start gap-3 py-2">
          <Users
            className="mt-0.5 size-5 shrink-0 text-info-foreground"
            aria-hidden
          />
          <div className="flex flex-col gap-2">
            <div>
              <h3 className="font-medium">Operational desk</h3>
              <p className="text-sm text-muted-foreground">
                Estates, wills, walk-ins, calls
              </p>
            </div>
            <p className="text-sm text-muted-foreground">
              Front-of-house work. Requesters see only this surface. Tickets
              start here, are triaged by ops, and either resolve or hand off to
              IT via a sanitised child.
            </p>
          </div>
        </article>
        <article className="flex items-start gap-3 py-2">
          <Workflow className="mt-0.5 size-5 shrink-0 text-gold" aria-hidden />
          <div className="flex flex-col gap-2">
            <div>
              <h3 className="font-medium">IT desk</h3>
              <p className="text-sm text-muted-foreground">
                Internal work orders, monitoring alerts
              </p>
            </div>
            <p className="text-sm text-muted-foreground">
              Technical work, isolated from the operational parent. The child
              receives a sanitised summary — never the parent's message body or
              attachments. Status only syncs back as a safe summary.
            </p>
          </div>
        </article>
      </div>
    </section>
  );
}

function Channels() {
  const channels = [
    { label: "Public form", icon: Globe, to: "/public" },
    { label: "Call centre", icon: Phone, to: "/intake/call" },
    { label: "Walk-in", icon: Users, to: "/intake/walk-in" },
    { label: "Email", icon: Mail, to: "/tickets" },
    { label: "WhatsApp", icon: Smartphone, to: "/tickets" },
    { label: "Monitoring", icon: Activity, to: "/tickets" },
  ];

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader
        eyebrow="One platform, every channel"
        title="Multi-channel intake"
        description="Each originating channel is recorded on the ticket. Idempotency and threading ensure a noisy email thread or a flapping alert never produces duplicates."
      />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-6">
        {channels.map((channel) => (
          <Link
            key={channel.label}
            to={channel.to}
            className={cn(
              buttonVariants({ variant: "outline" }),
              "h-auto min-h-16 flex-col items-start gap-1 py-3 text-left no-underline hover:no-underline",
            )}
          >
            <channel.icon data-icon="inline-start" />
            <span>{channel.label}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function Operations() {
  const cards = [
    {
      title: "Queue",
      description:
        "Filter by status, priority, channel, office. Saved filters in URL.",
      to: "/tickets",
      icon: ListChecks,
    },
    {
      title: "Kanban",
      description:
        "Drag-and-drop board with dnd-kit. Keyboard accessible. Server-validated transitions.",
      to: "/kanban",
      icon: KanbanSquare,
    },
    {
      title: "Dashboard",
      description:
        "Open totals, today's volume, by-priority breakdown, breach count, unassigned backlog.",
      to: "/dashboard",
      icon: LayoutDashboard,
    },
    {
      title: "Health",
      description:
        "DB, Redis, MinIO, Keycloak latencies. Liveness + readiness probes for the platform.",
      to: "/health",
      icon: HeartPulse,
    },
  ];

  return (
    <section className="flex flex-col gap-4">
      <SectionHeader
        eyebrow="Day-to-day operations"
        title="Built for triage"
        description="Information-dense screens, keyboard-first, and a curated action set. No decoration that doesn't earn its place."
      />
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <Link
            key={card.to}
            to={card.to}
            className="group block text-card-foreground no-underline hover:no-underline focus-visible:outline-none"
          >
            <Card className="h-full transition-[transform,box-shadow] group-hover:-translate-y-0.5 group-hover:shadow-sm group-focus-visible:ring-3 group-focus-visible:ring-ring/50">
              <CardHeader>
                <div className="flex items-center justify-between text-primary">
                  <card.icon className="size-5" aria-hidden />
                  <ArrowRight
                    className="size-4 text-muted-foreground"
                    aria-hidden
                  />
                </div>
                <CardTitle>{card.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  {card.description}
                </p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </section>
  );
}

function Cta() {
  return (
    <>
      <Separator />
      <section className="relative overflow-hidden py-8">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-10"
          style={{
            backgroundImage:
              "linear-gradient(135deg, var(--primary) 0%, transparent 50%, var(--gold) 100%)",
          }}
        />
        <div className="relative flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-col gap-2">
            <BrandLockup size="md" />
            <p className="text-sm text-muted-foreground">
              Judiciary of Eswatini · Operational and IT service desks
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              to="/login"
              className={cn(
                buttonVariants(),
                "no-underline hover:no-underline",
              )}
            >
              <Shield data-icon="inline-start" />
              Sign in
            </Link>
            <Link
              to="/health"
              className={cn(
                buttonVariants({ variant: "outline" }),
                "no-underline hover:no-underline",
              )}
            >
              <Activity data-icon="inline-start" />
              Health
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}

function SectionHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-semibold uppercase tracking-wider text-primary">
        {eyebrow}
      </span>
      <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">
        {title}
      </h2>
      <p className="max-w-3xl text-sm text-muted-foreground sm:text-base">
        {description}
      </p>
    </div>
  );
}
