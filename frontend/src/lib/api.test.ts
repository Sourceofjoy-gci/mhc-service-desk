import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  configureApiAuth,
  ticketsApi,
  type ApiAuthAdapter,
  type TicketTrackingResult,
} from "./api";

const TRACKING_RESULT: TicketTrackingResult = {
  reference: "O00123",
  title: "Estate status enquiry",
  tracking_status: "In Progress",
  status_updated_at: "2026-08-02T10:15:00Z",
  created_at: "2026-08-02T09:00:00Z",
  updated_at: "2026-08-02T10:15:00Z",
  office: "Mbabane (Main)",
  service: "Estate registration or reference",
  progress: [
    { status: "Submitted", occurred_at: "2026-08-02T09:00:00Z" },
    { status: "In Progress", occurred_at: "2026-08-02T10:15:00Z" },
  ],
};

function jsonResponse(status: number, body: unknown = {}) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestHeaders(call: unknown[]): Headers {
  const init = call[1] as RequestInit;
  return new Headers(init.headers);
}

describe("API authentication", () => {
  let adapter: ApiAuthAdapter;
  let disposeAuth: unknown;

  beforeEach(() => {
    window.history.replaceState({}, "", "/tickets?priority=P1");
    adapter = {
      getAccessToken: vi
        .fn()
        .mockResolvedValueOnce("old-token")
        .mockResolvedValueOnce("new-token"),
      refresh: vi.fn().mockResolvedValue(true),
      login: vi.fn().mockResolvedValue(undefined),
    };
    disposeAuth = configureApiAuth(adapter);
  });

  afterEach(() => {
    if (typeof disposeAuth === "function") disposeAuth();
  });

  it("retries one authenticated 401 with the refreshed token", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await expect(api<{ ok: boolean }>("/tickets/")).resolves.toEqual({
      ok: true,
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestHeaders(fetchMock.mock.calls[0]).get("Authorization")).toBe(
      "Bearer old-token",
    );
    expect(requestHeaders(fetchMock.mock.calls[1]).get("Authorization")).toBe(
      "Bearer new-token",
    );
    expect(adapter.refresh).toHaveBeenCalledTimes(1);
  });

  it("does not restart sign-in when a freshly refreshed token is still rejected", async () => {
    // A 401 that survives a successful refresh is the backend rejecting the
    // identity, not an expired session. Signing in again returns the same
    // token and the same 401, which is what made the app redirect forever.
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "unauthorized" }));

    await expect(api("/tickets/")).rejects.toMatchObject({
      status: 401,
      body: { detail: "expired" },
    });

    expect(adapter.refresh).toHaveBeenCalledTimes(1);
    expect(adapter.login).not.toHaveBeenCalled();
  });

  it("restarts sign-in when the session cannot be refreshed", async () => {
    adapter.refresh = vi.fn().mockResolvedValue(false);
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse(401, { detail: "expired" }),
    );

    await expect(api("/tickets/")).rejects.toMatchObject({ status: 401 });

    expect(adapter.refresh).toHaveBeenCalledTimes(1);
    expect(adapter.login).toHaveBeenCalledOnce();
    expect(adapter.login).toHaveBeenCalledWith("/tickets?priority=P1");
  });

  it("starts at most one sign-in redirect while the page is still loaded", async () => {
    adapter.getAccessToken = vi.fn().mockResolvedValue("old-token");
    adapter.refresh = vi.fn().mockResolvedValue(false);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse(401, { detail: "expired" }),
    );

    await expect(api("/tickets/")).rejects.toMatchObject({ status: 401 });
    await expect(api("/tickets/")).rejects.toMatchObject({ status: 401 });

    expect(adapter.login).toHaveBeenCalledOnce();
  });

  it("does not redirect to login for forbidden responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse(403, { detail: "forbidden" }),
    );

    try {
      await api("/tickets/");
      throw new Error("Expected the forbidden request to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({ status: 403 });
    }
    expect(adapter.refresh).not.toHaveBeenCalled();
    expect(adapter.login).not.toHaveBeenCalled();
  });

  it("omits authorization for public requests", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await api("/health", { auth: false });

    expect(requestHeaders(fetchMock.mock.calls[0]).has("Authorization")).toBe(
      false,
    );
    expect(adapter.getAccessToken).not.toHaveBeenCalled();
  });

  it("authenticates staff intake submissions", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse(201, {
        ticket_number: "OP-260730-000001",
        domain: "operational",
        title: "Callback request",
        priority: "P3",
        message: "Created",
      }),
    );

    await ticketsApi.publicIntake({
      request_type_code: "CALLBACK",
      service_code: "GEN-INFO",
      office_code: "MHC-MBA",
      title: "Callback request",
      description: "Please call the requester",
      requester_name: "Tester",
      consent: true,
      channel: "call",
    });

    expect(requestHeaders(fetchMock.mock.calls[0]).get("Authorization")).toBe(
      "Bearer old-token",
    );
  });

  it("encodes the ticket reference for authenticated tracking lookup", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, TRACKING_RESULT));

    await ticketsApi.track("O00123");

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/tickets/tracking/?reference=O00123",
    );
    expect(requestHeaders(fetchMock.mock.calls[0]).get("Authorization")).toBe(
      "Bearer old-token",
    );
  });

  it("lets the browser set multipart boundaries for FormData", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(204));
    const body = new FormData();
    body.set("file", new File(["contents"], "proof.txt"));

    await api("/tickets/MHC-1/attachments/", { method: "POST", body });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(body);
    expect(requestHeaders(fetchMock.mock.calls[0]).has("Content-Type")).toBe(
      false,
    );
  });

  it("uploads attachments through the protected helper with browser-owned multipart headers", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { results: [] }));
    const first = new File(["first"], "first.txt", { type: "text/plain" });
    const second = new File(["second"], "second.txt", { type: "text/plain" });

    await ticketsApi.uploadAttachments("MHC-1", [first, second]);

    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/tickets/MHC-1/attachments/",
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    expect(Array.from((init.body as FormData).getAll("files"))).toEqual([
      first,
      second,
    ]);
    expect(requestHeaders(fetchMock.mock.calls[0]).get("Authorization")).toBe(
      "Bearer old-token",
    );
    expect(requestHeaders(fetchMock.mock.calls[0]).has("Content-Type")).toBe(
      false,
    );
  });

  it("refreshes and retries an attachment upload only once", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(200, { results: [] }));

    await ticketsApi.uploadAttachments("MHC-2", [
      new File(["proof"], "proof.txt"),
    ]);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestHeaders(fetchMock.mock.calls[1]).get("Authorization")).toBe(
      "Bearer new-token",
    );
    expect(adapter.refresh).toHaveBeenCalledOnce();
  });
});

describe("API adapter lifecycle", () => {
  it("an old disposer cannot clear a newer adapter", async () => {
    const oldAdapter: ApiAuthAdapter = {
      getAccessToken: vi.fn().mockResolvedValue("old-token"),
      refresh: vi.fn().mockResolvedValue(true),
      login: vi.fn().mockResolvedValue(undefined),
    };
    const newAdapter: ApiAuthAdapter = {
      getAccessToken: vi.fn().mockResolvedValue("new-token"),
      refresh: vi.fn().mockResolvedValue(true),
      login: vi.fn().mockResolvedValue(undefined),
    };
    const disposeOld = configureApiAuth(oldAdapter) as unknown as () => void;
    const disposeNew = configureApiAuth(newAdapter) as unknown as () => void;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    disposeOld();
    await api("/tickets/");

    expect(requestHeaders(fetchMock.mock.calls[0]).get("Authorization")).toBe(
      "Bearer new-token",
    );
    disposeNew();
  });

  it("fails protected requests closed after disposal while public calls remain usable", async () => {
    const adapter: ApiAuthAdapter = {
      getAccessToken: vi.fn().mockResolvedValue("token"),
      refresh: vi.fn().mockResolvedValue(true),
      login: vi.fn().mockResolvedValue(undefined),
    };
    const dispose = configureApiAuth(adapter) as unknown as () => void;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { status: "ok" }));

    dispose();

    await expect(api("/tickets/")).rejects.toThrow(/authentication/i);
    expect(fetchMock).not.toHaveBeenCalled();

    await expect(api("/health", { auth: false })).resolves.toEqual({
      status: "ok",
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
