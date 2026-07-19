import { useQuery } from "@tanstack/react-query";

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

export default function HealthPage() {
  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 15_000,
  });

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">System Health</h1>
        <button
          onClick={() => refetch()}
          className="rounded-md border border-ink-100 bg-white px-3 py-1.5 text-sm text-ink-700 hover:bg-ink-50"
          disabled={isRefetching}
        >
          {isRefetching ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {isLoading && <p className="text-ink-500">Loading…</p>}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Could not reach the API. Is the backend running?
        </div>
      )}

      {data && (
        <div className="space-y-4">
          <div
            className={`rounded-md border p-3 text-sm ${
              data.status === "ok"
                ? "border-green-200 bg-green-50 text-green-800"
                : "border-amber-200 bg-amber-50 text-amber-800"
            }`}
          >
            <strong className="capitalize">{data.status}</strong> · environment{" "}
            <code>{data.environment}</code> · version <code>{data.version}</code> · total{" "}
            {data.total_ms} ms
          </div>

          <table className="w-full text-left text-sm">
            <thead className="border-b border-ink-100 text-ink-500">
              <tr>
                <th className="py-2">Check</th>
                <th className="py-2">State</th>
                <th className="py-2 text-right">Latency</th>
                <th className="py-2">Detail</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.checks).map(([name, c]) => (
                <tr key={name} className="border-b border-ink-100">
                  <td className="py-2 font-medium">{name}</td>
                  <td className="py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        c.ok
                          ? "bg-green-100 text-green-800"
                          : "bg-red-100 text-red-800"
                      }`}
                    >
                      {c.ok ? "OK" : "FAIL"}
                    </span>
                  </td>
                  <td className="py-2 text-right tabular-nums">{c.latency_ms} ms</td>
                  <td className="py-2 text-ink-500">{c.error ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
