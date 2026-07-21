import { Link } from "react-router-dom";
import {
  ArrowRight,
  Shield,
  Workflow,
  Activity,
  Users,
  KanbanSquare,
  Phone,
  Globe,
  HeartPulse,
  ListChecks,
  LayoutDashboard,
  Mail,
  Smartphone,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { BrandLockup } from "@/components/brand";
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
    <section className="relative overflow-hidden rounded-2xl border border-border/60 bg-gradient-to-br from-card via-card to-muted/40 p-6 sm:p-10">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-0 opacity-[0.18] dark:opacity-[0.08]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 20% 0%, var(--primary), transparent 40%), radial-gradient(circle at 90% 30%, var(--gold), transparent 50%)",
        }}
      />
      <div className="relative grid gap-8 lg:grid-cols-[1.4fr_1fr] lg:items-center">
        <div className="flex flex-col gap-5">
          <Badge
            variant="secondary"
            className="w-fit gap-1.5 text-xs font-medium"
          >
            <Shield className="size-3" />
            MHC Unified e-Ticketing · M2–M6 ready
          </Badge>
          <div className="flex flex-col gap-3">
            <h1 className="text-balance text-3xl font-semibold tracking-tight sm:text-4xl lg:text-5xl">
              Capture every request.
              <br />
              <span className="text-primary">Route with rigour.</span>
            </h1>
            <p className="max-w-2xl text-pretty text-base text-muted-foreground sm:text-lg">
              Operational and IT service desks with strict separation. Every
              request becomes a traceable ticket with Kanban workflow, SLA
              tracking, audit trail, and a requester-safe public entry point.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button render={<Link to="/tickets" />} data-icon>
              Open the queue
              <ArrowRight data-icon="inline-end" />
            </Button>
            <Button variant="outline" render={<Link to="/kanban" />} data-icon>
              <KanbanSquare data-icon="inline-start" />
              Kanban board
            </Button>
            <Button
              variant="ghost"
              render={<Link to="/public" />}
              className="text-muted-foreground"
              data-icon
            >
              <Globe data-icon="inline-start" />
              Public form
            </Button>
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
    <Card className="self-start lg:self-center" data-size="sm">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm font-medium">
            <Activity className="size-4 text-primary" />
            Platform status
          </CardTitle>
          {data ? (
            <Badge
              variant="secondary"
              className={
                data.status === "ok"
                  ? "bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30"
                  : "bg-destructive/10 text-destructive ring-1 ring-inset ring-destructive/30"
              }
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
      <CardContent className="flex flex-col gap-2.5">
        {entries.map((entry) => {
          const check = checks[entry.key];
          return (
            <div
              key={entry.key}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <div className="flex items-center gap-2">
                <span
                  className={
                    check?.ok
                      ? "size-1.5 rounded-full bg-success"
                      : check
                        ? "size-1.5 rounded-full bg-destructive"
                        : "size-1.5 rounded-full bg-muted-foreground/40"
                  }
                  aria-hidden
                />
                <span className="text-foreground">{entry.label}</span>
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
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <span className="grid size-9 place-items-center rounded-md bg-info/15 text-info-foreground ring-1 ring-inset ring-info/30">
                <Users className="size-4" />
              </span>
              <div>
                <CardTitle>Operational desk</CardTitle>
                <CardDescription>Estates, wills, walk-ins, calls</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Front-of-house work. Requesters see only this surface. Tickets
            start here, are triaged by ops, and either resolve or hand off
            to IT via a sanitised child.
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <span className="grid size-9 place-items-center rounded-md bg-gold/20 text-gold-foreground ring-1 ring-inset ring-gold/30">
                <Workflow className="size-4" />
              </span>
              <div>
                <CardTitle>IT desk</CardTitle>
                <CardDescription>
                  Internal work orders, monitoring alerts
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Technical work, isolated from the operational parent. The child
            receives a sanitised summary — never the parent's message body
            or attachments. Status only syncs back as a safe summary.
          </CardContent>
        </Card>
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
        {channels.map((c) => (
          <Button
            key={c.label}
            variant="outline"
            render={<Link to={c.to} />}
            className="h-auto flex-col items-start gap-1.5 py-3 text-left"
          >
            <c.icon className="size-4 text-primary" />
            <span className="text-sm font-medium">{c.label}</span>
          </Button>
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
            className="group rounded-xl border border-border/60 bg-card p-4 text-card-foreground no-underline transition-all hover:border-primary/40 hover:shadow-sm"
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="grid size-9 place-items-center rounded-md bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
                <card.icon className="size-4" />
              </span>
              <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
            </div>
            <h3 className="text-sm font-semibold">{card.title}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {card.description}
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}

function Cta() {
  return (
    <Card className="overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-20"
        style={{
          backgroundImage:
            "linear-gradient(135deg, var(--primary) 0%, transparent 50%, var(--gold) 100%)",
        }}
      />
      <CardContent className="flex flex-col items-start gap-4 p-6 sm:flex-row sm:items-center sm:justify-between sm:p-8">
        <div className="flex flex-col gap-2">
          <BrandLockup size="md" />
          <p className="text-sm text-muted-foreground">
            Judiciary of Eswatini · Operational and IT service desks
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button render={<Link to="/login" />} data-icon>
            <Shield data-icon="inline-start" />
            Sign in
          </Button>
          <Button
            variant="outline"
            render={<Link to="/health" />}
            data-icon
          >
            <Activity data-icon="inline-start" />
            Health
          </Button>
        </div>
      </CardContent>
    </Card>
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
    <div className="flex flex-col gap-1.5">
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
