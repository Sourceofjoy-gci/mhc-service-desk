import { useQuery } from "@tanstack/react-query";
import { ticketsApi } from "../../lib/api";

export default function DashboardPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => ticketsApi.dashboard(),
    refetchInterval: 30_000,
  });

  if (isLoading) return <p className="text-ink-500">Loading…</p>;
  if (error || !data) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        Could not load dashboard.
      </div>
    );
  }

  const d = data;
  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold">Operational dashboard</h1>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Open" value={d.totals.open} />
        <Stat label="Today" value={d.totals.today} />
        <Stat label="This week" value={d.totals.this_week} />
        <Stat label="Unassigned" value={d.unassigned} />
        <Stat label="Breached SLA" value={d.breached_sla} tone={d.breached_sla > 0 ? "danger" : "ok"} />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-md border border-ink-100 bg-white p-4">
          <h2 className="text-sm font-semibold text-ink-700">By priority</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {d.by_priority.map((row) => (
              <li key={row.priority} className="flex justify-between">
                <span>{row.priority}</span>
                <span className="font-mono">{row.count}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-md border border-ink-100 bg-white p-4">
          <h2 className="text-sm font-semibold text-ink-700">By status</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {d.by_status.map((row) => (
              <li key={row.status__code} className="flex justify-between">
                <span>{row.status__name}</span>
                <span className="font-mono">{row.count}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "ok" | "danger" }) {
  return (
    <div className="rounded-md border border-ink-100 bg-white p-4">
      <div className="text-xs text-ink-500">{label}</div>
      <div
        className={
          tone === "danger" ? "mt-1 text-2xl font-semibold text-red-700" : "mt-1 text-2xl font-semibold text-ink-900"
        }
      >
        {value}
      </div>
    </div>
  );
}
