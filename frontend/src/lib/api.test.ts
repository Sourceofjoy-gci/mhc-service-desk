import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  configureApiAuth,
  type ApiAuthAdapter,
} from "./api";

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
    configureApiAuth(adapter);
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

  it("redirects to login once when the retried request is still unauthorized", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: "unauthorized" }));

    await expect(api("/tickets/")).rejects.toMatchObject({
      status: 401,
      body: { detail: "expired" },
    });

    expect(adapter.refresh).toHaveBeenCalledTimes(1);
    expect(adapter.login).toHaveBeenCalledOnce();
    expect(adapter.login).toHaveBeenCalledWith("/tickets?priority=P1");
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
});
