/**
 * API client for the MHC e-Ticketing backend.
 *
 * Dev-mode note: when `VITE_DEV_AUTH` is "1", requests use a stub Bearer
 * token format `dev:<username>:<groups>` which the backend accepts in DEBUG.
 * In production, remove the dev header and use Keycloak OIDC.
 */

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "") + "/api/v1";

export const DEV_AUTH_TOKEN =
  import.meta.env.VITE_DEV_AUTH === "1" &&
  import.meta.env.MODE === "development"
    ? "Bearer dev:demo:ops-agents"
    : null;

export type Domain = "operational" | "it";
export type Priority = "P1" | "P2" | "P3" | "P4";

export interface TicketSummary {
  id: string;
  number: string;
  domain: Domain;
  title: string;
  channel: string;
  priority: Priority;
  confidentiality: string;
  status_code: string;
  status_name: string;
  status_public: string;
  requester_name: string;
  office_code: string;
  service_code: string;
  assignee: string | null;
  waiting_reason: string;
  created_at: string;
  updated_at: string;
  age_hours: number;
  sla_health: "on_track" | "at_risk" | "breached" | "paused" | "none";
}

export interface TicketMessage {
  id: string;
  direction: "inbound" | "outbound";
  author_label: string;
  body_text: string;
  delivery_status: string;
  created_at: string;
}

export interface TicketNote {
  id: string;
  author_subject: string;
  body: string;
  created_at: string;
}

export interface TicketDetail extends TicketSummary {
  description: string;
  requester: { id: string; full_name: string; email: string | null; phone_e164: string | null };
  service: string;
  request_type: string;
  office: string;
  matter_reference: string;
  tags: string[];
  custom_fields: Record<string, unknown>;
  resolution_code: string;
  resolution_summary: string;
  acknowledged_at: string | null;
  first_responded_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  messages: TicketMessage[];
  notes: TicketNote[];
}

export interface KanbanData {
  columns: Record<string, TicketSummary[]>;
}

export interface DashboardData {
  totals: { open: number; today: number; this_week: number };
  by_priority: { priority: string; count: number }[];
  by_status: { status__code: string; status__name: string; count: number }[];
  unassigned: number;
  breached_sla: number;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (DEV_AUTH_TOKEN) headers.Authorization = DEV_AUTH_TOKEN;
  const r = await fetch(API_BASE + path, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });
  if (!r.ok) {
    let body: unknown = null;
    try { body = await r.json(); } catch { /* non-JSON */ }
    throw new ApiError(r.status, body);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export const ticketsApi = {
  list: (params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(params).toString();
    return api<TicketSummary[]>(`/tickets/${qs ? "?" + qs : ""}`);
  },
  get: (number: string) => api<TicketDetail>(`/tickets/${number}/`),
  kanban: (domain: Domain) => api<KanbanData>(`/tickets/kanban/?domain=${domain}`),
  transition: (number: string, to_status: string, reason = "") =>
    api<TicketDetail>(`/tickets/${number}/transition/`, {
      method: "POST",
      body: { to_status, reason },
    }),
  addMessage: (number: string, body_text: string) =>
    api<{ id: string }>(`/tickets/${number}/messages/`, {
      method: "POST",
      body: { body_text },
    }),
  addNote: (number: string, body: string) =>
    api<{ id: string }>(`/tickets/${number}/notes/`, {
      method: "POST",
      body: { body },
    }),
  dashboard: () => api<DashboardData>(`/tickets/dashboard/operational/`),
  publicIntake: (data: {
    request_type_code: string;
    service_code: string;
    office_code: string;
    title: string;
    description: string;
    requester_name: string;
    requester_email?: string;
    requester_phone?: string;
    matter_reference?: string;
    consent: boolean;
  }) =>
    api<{
      ticket_number: string;
      domain: string;
      title: string;
      priority: string;
      message: string;
    }>(`/tickets/public/intake/`, { method: "POST", body: data }),
};

export const servicesApi = {
  list: () => api<unknown[]>("/catalogue/services/"),
};
