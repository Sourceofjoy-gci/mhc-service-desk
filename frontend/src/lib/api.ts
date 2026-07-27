/**
 * API client for the MHC e-Ticketing backend.
 *
 * Authentication is supplied by AuthProvider so request handling remains
 * independent of Keycloak and development identity details.
 */

import { normalizePage, type Page } from "./collections";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "") + "/api/v1";

export interface ApiAuthAdapter {
  getAccessToken(forceRefresh?: boolean): Promise<string | null>;
  refresh(): Promise<boolean>;
  login(returnTo: string): Promise<void>;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  auth?: boolean;
  retry401?: boolean;
  headers?: Record<string, string>;
}

let authAdapter: ApiAuthAdapter | null = null;

export function configureApiAuth(adapter: ApiAuthAdapter): () => void {
  authAdapter = adapter;
  return () => {
    if (authAdapter === adapter) authAdapter = null;
  };
}

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
  breached_sla?: number;
  p1p2?: number;
}

export interface AttachmentUploadResult {
  id: string;
  filename: string;
  size_bytes: number;
  scan_status: "pending" | "clean" | "infected" | "error";
  scan_signature: string;
}

export interface AttachmentUploadResponse {
  results: AttachmentUploadResult[];
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

export class ApiAuthUnavailableError extends Error {
  constructor() {
    super("Authentication is not ready for protected API requests");
  }
}

export class ApiLinkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiLinkError";
  }
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const usesAuth = opts.auth !== false;
  const requestAuth = authAdapter;
  const isFormData =
    typeof FormData !== "undefined" && opts.body instanceof FormData;
  const headers: Record<string, string> = { ...opts.headers };
  if (!isFormData && !hasHeader(headers, "Content-Type")) {
    headers["Content-Type"] = "application/json";
  }
  if (usesAuth) {
    if (!requestAuth) throw new ApiAuthUnavailableError();
    const token = await requestAuth.getAccessToken();
    if (!token) throw new ApiAuthUnavailableError();
    headers.Authorization = asBearerToken(token);
  }

  const r = await fetch(API_BASE + path, {
    method: opts.method ?? "GET",
    headers,
    body:
      opts.body === undefined
        ? undefined
        : isFormData
          ? (opts.body as FormData)
          : JSON.stringify(opts.body),
    signal: opts.signal,
  });
  if (!r.ok) {
    let body: unknown = null;
    try { body = await r.json(); } catch { /* non-JSON */ }
    const error = new ApiError(r.status, body);
    if (r.status === 401 && usesAuth && requestAuth) {
      let refreshed = false;
      if (opts.retry401 !== false) {
        try {
          refreshed = await requestAuth.refresh();
        } catch {
          refreshed = false;
        }
      }
      if (refreshed) {
        try {
          return await api<T>(path, { ...opts, retry401: false });
        } catch (retryError) {
          if (retryError instanceof ApiError && retryError.status === 401) {
            throw error;
          }
          throw retryError;
        }
      }
      try {
        await requestAuth.login(
          window.location.pathname + window.location.search,
        );
      } catch {
        // A redirect can interrupt the login promise; callers still receive
        // the API failure that initiated reauthentication.
      }
    }
    throw error;
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export async function apiUrl<T>(absoluteOrRelativeUrl: string): Promise<T> {
  const apiBaseUrl = new URL(
    API_BASE.endsWith("/") ? API_BASE : `${API_BASE}/`,
    window.location.origin,
  );
  let serverUrl: URL;
  try {
    serverUrl = new URL(absoluteOrRelativeUrl, apiBaseUrl);
  } catch {
    throw new ApiLinkError("Server link is malformed");
  }
  const apiPathPrefix = apiBaseUrl.pathname.replace(/\/$/, "");

  if (
    serverUrl.pathname !== apiPathPrefix &&
    !serverUrl.pathname.startsWith(`${apiPathPrefix}/`)
  ) {
    throw new ApiLinkError("Server link is outside the configured API path");
  }

  const path = serverUrl.pathname.slice(apiPathPrefix.length) || "/";
  return api<T>(`${path}${serverUrl.search}`);
}

function hasHeader(headers: Record<string, string>, name: string): boolean {
  return Object.keys(headers).some((key) => key.toLowerCase() === name.toLowerCase());
}

function asBearerToken(token: string): string {
  return `Bearer ${token.replace(/^Bearer\s+/i, "")}`;
}

export const ticketsApi = {
  list: async (
    params: Record<string, string> = {},
  ): Promise<Page<TicketSummary>> => {
    const qs = new URLSearchParams(params).toString();
    const value = await api<unknown>(
      `/tickets/${qs ? "?" + qs : ""}`,
    );
    return normalizePage(value);
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
  dashboard: (domain: Domain) =>
    api<DashboardData>(`/reports/dashboard/${domain}`),
  uploadAttachments: (number: string, files: readonly File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    return api<AttachmentUploadResponse>(`/tickets/${number}/attachments/`, {
      method: "POST",
      body: form,
    });
  },
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
    channel?: string;
  }) =>
    api<{
      ticket_number: string;
      domain: string;
      title: string;
      priority: string;
      message: string;
    }>(`/tickets/public/intake/`, { method: "POST", body: data, auth: false }),
};

export const servicesApi = {
  list: async (): Promise<Page<unknown>> =>
    normalizePage(await api<unknown>("/catalogue/services/")),
};

const OPERATIONAL_GROUPS = new Set([
  "agent-operational",
  "ops-agents",
  "supervisor-operational",
  "ops-supervisors",
]);
const IT_GROUPS = new Set(["agent-it", "it-agents", "lead-it", "it-leads"]);
const ALL_DOMAIN_GROUPS = new Set([
  "admin",
  "system-admins",
  "auditor",
  "auditors",
]);
const RESTRICTED_QUEUE_GROUPS = new Set(["security-responders"]);

export interface DomainCapabilities {
  queueDomains: Domain[];
  dashboardDomains: Domain[];
}

export function domainCapabilities(
  groups: readonly string[],
): DomainCapabilities {
  const names = new Set(
    groups.map((group) => group.split("/").filter(Boolean).at(-1) ?? group),
  );
  if ([...names].some((group) => ALL_DOMAIN_GROUPS.has(group))) {
    return {
      queueDomains: ["operational", "it"],
      dashboardDomains: ["operational", "it"],
    };
  }

  const domains: Domain[] = [];
  if ([...names].some((group) => OPERATIONAL_GROUPS.has(group))) {
    domains.push("operational");
  }
  if ([...names].some((group) => IT_GROUPS.has(group))) domains.push("it");
  return {
    queueDomains: [...names].some((group) =>
      RESTRICTED_QUEUE_GROUPS.has(group),
    )
      ? ["operational", "it"]
      : domains,
    dashboardDomains: domains,
  };
}
