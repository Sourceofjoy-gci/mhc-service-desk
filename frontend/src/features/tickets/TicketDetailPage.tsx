import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ticketsApi, type TicketDetail } from "../../lib/api";
import AttachmentUploader from "./AttachmentUploader";

export default function TicketDetailPage() {
  const { number } = useParams<{ number: string }>();
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["ticket", number],
    queryFn: () => ticketsApi.get(number!),
    enabled: !!number,
  });

  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");

  const addMessage = useMutation({
    mutationFn: (body_text: string) => ticketsApi.addMessage(number!, body_text),
    onSuccess: () => {
      setReply("");
      qc.invalidateQueries({ queryKey: ["ticket", number] });
    },
  });

  const addNote = useMutation({
    mutationFn: (body: string) => ticketsApi.addNote(number!, body),
    onSuccess: () => {
      setNote("");
      qc.invalidateQueries({ queryKey: ["ticket", number] });
    },
  });

  if (isLoading) return <p className="text-ink-500">Loading…</p>;
  if (error || !data)
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        Could not load ticket {number}.{" "}
        <Link to="/tickets" className="underline">
          Back to queue
        </Link>
      </div>
    );

  const t = data as TicketDetail;

  return (
    <section className="space-y-6">
      <div>
        <Link to="/tickets" className="text-sm">
          ← Back to queue
        </Link>
      </div>

      <header className="rounded-md border border-ink-100 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="font-mono text-xs text-ink-500">{t.number}</div>
            <h1 className="text-xl font-semibold text-ink-900">{t.title}</h1>
            <div className="mt-1 text-sm text-ink-500">
              {t.requester.full_name} · {t.office} · {t.service} · {t.request_type}
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 text-sm">
            <span className="rounded-full bg-brand-50 px-3 py-1 text-brand-700">
              {t.status_name}
            </span>
            <span className="text-ink-500">priority {t.priority}</span>
            <span className="text-ink-500">{t.age_hours.toFixed(1)}h old</span>
          </div>
        </div>
        {t.description && (
          <p className="mt-3 whitespace-pre-line text-sm text-ink-700">{t.description}</p>
        )}
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-4">
          <div className="rounded-md border border-ink-100 bg-white p-4">
            <h2 className="text-sm font-semibold text-ink-700">Conversation</h2>
            {t.messages.length === 0 ? (
              <p className="mt-2 text-sm text-ink-500">No messages yet.</p>
            ) : (
              <ul className="mt-3 space-y-3">
                {t.messages.map((m) => (
                  <li
                    key={m.id}
                    className={
                      m.direction === "outbound"
                        ? "rounded-md bg-brand-50 p-3"
                        : "rounded-md bg-ink-50 p-3"
                    }
                  >
                    <div className="text-xs text-ink-500">
                      {m.direction === "outbound" ? "↑ Reply" : "↓ Inbound"} ·{" "}
                      {m.author_label || "system"} ·{" "}
                      {new Date(m.created_at).toLocaleString()}
                    </div>
                    <p className="mt-1 whitespace-pre-line text-sm text-ink-900">{m.body_text}</p>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-4 space-y-2">
              <textarea
                value={reply}
                onChange={(e) => setReply(e.target.value)}
                placeholder="Reply to the requester…"
                rows={3}
                className="w-full rounded-md border border-ink-100 bg-white p-2 text-sm"
              />
              <div className="flex justify-end">
                <button
                  onClick={() => addMessage.mutate(reply)}
                  disabled={!reply.trim() || addMessage.isPending}
                  className="rounded-md bg-brand-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
                >
                  {addMessage.isPending ? "Sending…" : "Send reply"}
                </button>
              </div>
            </div>
          </div>

          <div className="rounded-md border border-ink-100 bg-amber-50 p-4">
            <h2 className="text-sm font-semibold text-ink-700">Internal notes</h2>
            <p className="mt-1 text-xs text-ink-500">
              Notes are never visible to the requester.
            </p>
            {t.notes.length === 0 ? (
              <p className="mt-2 text-sm text-ink-500">No notes yet.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {t.notes.map((n) => (
                  <li key={n.id} className="rounded-md bg-white p-2 text-sm">
                    <div className="text-xs text-ink-500">
                      {n.author_subject} · {new Date(n.created_at).toLocaleString()}
                    </div>
                    <p className="mt-1 whitespace-pre-line">{n.body}</p>
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-3 space-y-2">
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Add an internal note…"
                rows={2}
                className="w-full rounded-md border border-ink-100 bg-white p-2 text-sm"
              />
              <div className="flex justify-end">
                <button
                  onClick={() => addNote.mutate(note)}
                  disabled={!note.trim() || addNote.isPending}
                  className="rounded-md bg-amber-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
                >
                  {addNote.isPending ? "Saving…" : "Add note"}
                </button>
              </div>
            </div>
          </div>

          <AttachmentUploader ticketNumber={t.number} />
        </div>

        <aside className="space-y-4">
          <div className="rounded-md border border-ink-100 bg-white p-4 text-sm">
            <h3 className="font-semibold text-ink-700">Requester</h3>
            <p className="mt-2 text-ink-900">{t.requester.full_name}</p>
            {t.requester.email && <p className="text-ink-500">{t.requester.email}</p>}
            {t.requester.phone_e164 && <p className="text-ink-500">{t.requester.phone_e164}</p>}
          </div>
          <div className="rounded-md border border-ink-100 bg-white p-4 text-sm">
            <h3 className="font-semibold text-ink-700">Classification</h3>
            <dl className="mt-2 space-y-1 text-ink-500">
              <div className="flex justify-between">
                <dt>Channel</dt>
                <dd className="text-ink-900">{t.channel}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Office</dt>
                <dd className="text-ink-900">{t.office}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Service</dt>
                <dd className="text-ink-900">{t.service}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Type</dt>
                <dd className="text-ink-900">{t.request_type}</dd>
              </div>
              {t.matter_reference && (
                <div className="flex justify-between">
                  <dt>Matter</dt>
                  <dd className="font-mono text-ink-900">{t.matter_reference}</dd>
                </div>
              )}
            </dl>
          </div>
        </aside>
      </div>
    </section>
  );
}
