import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ticketsApi, type TicketSummary } from "../../lib/api";
import { TicketCard } from "./TicketCard";

export default function QueuePage() {
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [search, setSearch] = useState("");

  const params: Record<string, string> = {};
  if (status) params.status = status;
  if (priority) params.priority = priority;
  if (search) params.search = search;

  const { data, isLoading, error, refetch, isRefetching } = useQuery({
    queryKey: ["tickets", params],
    queryFn: () => ticketsApi.list(params),
  });

  const items: TicketSummary[] = data ?? [];

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">Queue</h1>
        <button
          onClick={() => refetch()}
          className="rounded-md border border-ink-100 bg-white px-3 py-1.5 text-sm text-ink-700 hover:bg-ink-50"
          disabled={isRefetching}
        >
          {isRefetching ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          placeholder="Search number, title, matter…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-md border border-ink-100 bg-white px-3 py-1.5 text-sm"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-md border border-ink-100 bg-white px-3 py-1.5 text-sm"
        >
          <option value="">All statuses</option>
          <option value="new">New</option>
          <option value="triage">Triage</option>
          <option value="assigned">Assigned</option>
          <option value="in_progress">In Progress</option>
          <option value="waiting_requester">Waiting for Requester</option>
          <option value="waiting_internal">Waiting for Internal</option>
          <option value="waiting_it">Waiting for IT</option>
          <option value="quality_review">Quality Review</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Closed</option>
        </select>
        <select
          value={priority}
          onChange={(e) => setPriority(e.target.value)}
          className="rounded-md border border-ink-100 bg-white px-3 py-1.5 text-sm"
        >
          <option value="">All priorities</option>
          <option value="P1">P1</option>
          <option value="P2">P2</option>
          <option value="P3">P3</option>
          <option value="P4">P4</option>
        </select>
      </div>

      {isLoading && <p className="text-ink-500">Loading…</p>}
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          Could not load tickets. Make sure the backend is running and you have
          a valid dev token (VITE_DEV_AUTH=1).
        </div>
      )}

      {data && (
        <>
          <p className="text-sm text-ink-500">
            {items.length} ticket{items.length === 1 ? "" : "s"}
          </p>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
            {items.map((t) => (
              <TicketCard key={t.id} ticket={t} />
            ))}
          </div>
          {items.length === 0 && (
            <div className="rounded-md border border-ink-100 bg-white p-6 text-center text-sm text-ink-500">
              No tickets match your filters.
            </div>
          )}
        </>
      )}
    </section>
  );
}
