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

export interface TicketCapabilities {
  can_update_work_state: boolean;
  can_self_assign: boolean;
  self_assignee_id: string | null;
  can_reassign: boolean;
  can_change_confidentiality: boolean;
}

export interface AvailableTransition {
  to_status: string;
  label: string;
  requires_resolution: boolean;
  requires_reason: boolean;
}

export interface SlaClock {
  state: "not_started" | "running" | "paused" | "met" | "breached";
  due_at: string | null;
  remaining_seconds: number;
  overdue_seconds: number;
}

export interface AttachmentMetadata {
  id: string;
  filename: string;
  size_bytes: number;
  content_type: string;
  uploaded_by: string;
  uploaded_at: string;
  scan_status: "pending" | "clean" | "infected" | "error";
  download_available: boolean;
}

export interface ActivityItem {
  id: string;
  type:
    | "message"
    | "internal_note"
    | "status_transition"
    | "work_state"
    | "attachment"
    | "relationship";
  occurred_at: string;
  actor: { subject: string; display_name: string } | null;
  visibility: "requester" | "internal";
  payload: Record<string, unknown>;
}

export interface TicketAssignee {
  id: string;
  username: string;
  display_name: string;
}

export interface TicketRelationship {
  id: string;
  kind: string;
  ticket_number: string;
  direction: "incoming" | "outgoing";
}

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
  available_transition_codes?: string[];
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
  reopened_at: string | null;
  assignee_detail: { id: string; display_name: string } | null;
  team: string;
  blocked_reason: string;
  next_action: string;
  next_action_at: string | null;
  available_transitions: AvailableTransition[];
  capabilities: TicketCapabilities;
  sla_clocks: {
    first_response: SlaClock;
    resolution: SlaClock;
  };
  relationships: TicketRelationship[];
  attachments: AttachmentMetadata[];
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

export interface AttachmentUploadResult extends AttachmentMetadata {
  scan_signature: string;
}

export interface AttachmentUploadResponse {
  results: AttachmentUploadResult[];
}

export interface ApiProblem {
  code: string;
  detail: string;
  fields: Record<string, string[]>;
  correlation_id: string;
}

export interface TicketWorkStateUpdate {
  updated_at: string;
  assignee?: string | null;
  team?: string;
  waiting_reason?: string;
  blocked_reason?: string;
  next_action?: string;
  next_action_at?: string | null;
  confidentiality?: string;
}

export interface TicketTransitionRequest {
  to_status: string;
  updated_at: string;
  reason?: string;
  resolution_code?: string;
  resolution_summary?: string;
}

export interface AttachmentDownload {
  url: string;
  filename: string;
  expires_in: number;
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

function isApiProblem(value: unknown): value is ApiProblem {
  if (typeof value !== "object" || value === null) return false;
  const body = value as Record<string, unknown>;
  if (
    typeof body.code !== "string" ||
    typeof body.detail !== "string" ||
    typeof body.correlation_id !== "string" ||
    typeof body.fields !== "object" ||
    body.fields === null ||
    Array.isArray(body.fields)
  ) {
    return false;
  }
  return Object.values(body.fields).every(
    (messages) =>
      Array.isArray(messages) &&
      messages.every((message) => typeof message === "string"),
  );
}

export function apiProblem(error: unknown): ApiProblem | null {
  return error instanceof ApiError && isApiProblem(error.body)
    ? error.body
    : null;
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

function transitionTicket(
  number: string,
  values: TicketTransitionRequest,
): Promise<TicketDetail>;
/** @deprecated Use the structured payload with `updated_at`. */
function transitionTicket(
  number: string,
  toStatus: string,
  reason?: string,
): Promise<TicketDetail>;
function transitionTicket(
  number: string,
  values: TicketTransitionRequest | string,
  reason = "",
): Promise<TicketDetail> {
  return api<TicketDetail>(`/tickets/${number}/transition/`, {
    method: "POST",
    body:
      typeof values === "string"
        ? { to_status: values, reason }
        : values,
  });
}

export const attachmentsApi = {
  list: (number: string) =>
    api<{ results: AttachmentMetadata[] }>(
      `/tickets/${number}/attachments/`,
    ),
  upload: (number: string, files: readonly File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    return api<AttachmentUploadResponse>(`/tickets/${number}/attachments/`, {
      method: "POST",
      body: form,
    });
  },
  download: (id: string) =>
    api<AttachmentDownload>(`/attachments/${id}/download/`),
};

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
  updateWorkState: (number: string, values: TicketWorkStateUpdate) =>
    api<TicketDetail>(`/tickets/${number}/work-state/`, {
      method: "PATCH",
      body: values,
    }),
  transition: transitionTicket,
  activity: (number: string) =>
    api<{ results: ActivityItem[] }>(`/tickets/${number}/activity/`),
  assignees: (number: string) =>
    api<{ results: TicketAssignee[] }>(`/tickets/${number}/assignees/`),
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
  uploadAttachments: attachmentsApi.upload,
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
