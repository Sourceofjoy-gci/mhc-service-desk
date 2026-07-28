import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as apiClient from "./api";

function jsonResponse(status: number, body: unknown = {}) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function request(call: unknown[]): { url: unknown; init: RequestInit } {
  return { url: call[0], init: call[1] as RequestInit };
}

interface LifecycleTicketsApi {
  updateWorkState(
    number: string,
    values: Record<string, unknown>,
  ): Promise<unknown>;
  transition(number: string, values: Record<string, unknown>): Promise<unknown>;
  activity(number: string): Promise<unknown>;
  assignees(number: string): Promise<unknown>;
}

interface LifecycleAttachmentsApi {
  list(number: string): Promise<unknown>;
  upload(number: string, files: readonly File[]): Promise<unknown>;
  download(id: string): Promise<unknown>;
}

describe("ticket lifecycle API contracts", () => {
  let disposeAuth: () => void;
  const ticketsApi = apiClient.ticketsApi as unknown as LifecycleTicketsApi;

  beforeEach(() => {
    disposeAuth = apiClient.configureApiAuth({
      getAccessToken: vi.fn().mockResolvedValue("staff-token"),
      refresh: vi.fn().mockResolvedValue(false),
      login: vi.fn().mockResolvedValue(undefined),
    });
  });

  afterEach(() => {
    disposeAuth();
  });

  it("PATCHes work-state values with the concurrency timestamp intact", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200));
    const values = {
      updated_at: "2026-07-27T08:00:00Z",
      next_action: "Call requester",
      next_action_at: "2026-07-28T08:00:00Z",
    };

    await ticketsApi.updateWorkState("OP-202607-000001", values);

    const { url, init } = request(fetchMock.mock.calls[0]);
    expect(url).toBe(
      "/api/v1/tickets/OP-202607-000001/work-state/",
    );
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual(values);
  });

  it("POSTs the complete transition payload without dropping resolution data", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200));
    const values = {
      to_status: "resolved",
      updated_at: "2026-07-27T08:00:00Z",
      reason: "Completed",
      resolution_code: "INFO_PROVIDED",
      resolution_summary:
        "The requester received the required information.",
    };

    await ticketsApi.transition("OP-202607-000001", values);

    const { url, init } = request(fetchMock.mock.calls[0]);
    expect(url).toBe(
      "/api/v1/tickets/OP-202607-000001/transition/",
    );
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(values);
  });

  it("loads activity and eligible assignees from ticket subresources", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { results: [] }))
      .mockResolvedValueOnce(jsonResponse(200, { results: [] }));

    await ticketsApi.activity("OP-202607-000001");
    await ticketsApi.assignees("OP-202607-000001");

    expect(request(fetchMock.mock.calls[0])).toMatchObject({
      url: "/api/v1/tickets/OP-202607-000001/activity/",
      init: { method: "GET" },
    });
    expect(request(fetchMock.mock.calls[1])).toMatchObject({
      url: "/api/v1/tickets/OP-202607-000001/assignees/",
      init: { method: "GET" },
    });
  });

  it("lists and uploads attachments through the ticket collection", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, { results: [] }))
      .mockResolvedValueOnce(jsonResponse(201, { results: [] }));
    const attachmentsApi = (
      apiClient as unknown as { attachmentsApi: LifecycleAttachmentsApi }
    ).attachmentsApi;
    const first = new File(["first"], "first.txt", { type: "text/plain" });
    const second = new File(["second"], "second.txt", { type: "text/plain" });

    await attachmentsApi.list("OP-202607-000001");
    await attachmentsApi.upload("OP-202607-000001", [first, second]);

    expect(request(fetchMock.mock.calls[0])).toMatchObject({
      url: "/api/v1/tickets/OP-202607-000001/attachments/",
      init: { method: "GET" },
    });
    const upload = request(fetchMock.mock.calls[1]);
    expect(upload.url).toBe(
      "/api/v1/tickets/OP-202607-000001/attachments/",
    );
    expect(upload.init.method).toBe("POST");
    expect(upload.init.body).toBeInstanceOf(FormData);
    expect(Array.from((upload.init.body as FormData).getAll("files"))).toEqual([
      first,
      second,
    ]);
    expect(new Headers(upload.init.headers).has("Content-Type")).toBe(false);
  });

  it("requests a signed attachment download from the attachment resource", async () => {
    const response = {
      url: "https://files.example/signed",
      filename: "proof.pdf",
      expires_in: 60,
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(200, response));
    const attachmentsApi = (
      apiClient as unknown as { attachmentsApi: LifecycleAttachmentsApi }
    ).attachmentsApi;

    await expect(attachmentsApi.download("attachment-1")).resolves.toEqual(
      response,
    );
    expect(request(fetchMock.mock.calls[0])).toMatchObject({
      url: "/api/v1/attachments/attachment-1/download/",
      init: { method: "GET" },
    });
  });
});

describe("canonical API problems", () => {
  it("exposes only complete canonical error bodies", () => {
    const apiProblem = (
      apiClient as unknown as {
        apiProblem(error: unknown): unknown;
      }
    ).apiProblem;
    const problem = {
      code: "stale_ticket",
      detail: "The ticket was updated by another user.",
      fields: { updated_at: ["2026-07-27T09:00:00Z"] },
      correlation_id: "corr-123",
    };

    expect(apiProblem(new apiClient.ApiError(409, problem))).toEqual(problem);
    expect(
      apiProblem(
        new apiClient.ApiError(400, {
          code: "invalid_work_state",
          detail: "Work state is invalid.",
          fields: { next_action: "Must be text." },
          correlation_id: "corr-124",
        }),
      ),
    ).toBeNull();
    expect(apiProblem(new Error("network"))).toBeNull();
  });
});
