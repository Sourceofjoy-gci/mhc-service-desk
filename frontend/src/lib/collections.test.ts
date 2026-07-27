import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  configureApiAuth,
  apiUrl,
  servicesApi,
  ticketsApi,
  type ApiAuthAdapter,
} from "./api";
import { normalizePage } from "./collections";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("normalizePage", () => {
  it("normalizes a legacy array", () => {
    expect(normalizePage([{ id: "1" }])).toEqual({
      next: null,
      previous: null,
      results: [{ id: "1" }],
    });
  });

  it("preserves a canonical page", () => {
    const page = {
      next: "/api/v1/tickets/?cursor=n",
      previous: null,
      results: [{ id: "1" }],
    };

    expect(normalizePage(page)).toEqual(page);
  });
});

describe("collection API adapters", () => {
  let disposeAuth: () => void;

  beforeEach(() => {
    const adapter: ApiAuthAdapter = {
      getAccessToken: vi.fn().mockResolvedValue("access-token"),
      refresh: vi.fn().mockResolvedValue(false),
      login: vi.fn().mockResolvedValue(undefined),
    };
    disposeAuth = configureApiAuth(adapter);
  });

  afterEach(() => disposeAuth());

  it("normalizes legacy ticket and service collections at their API boundaries", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([{ code: "GEN-INFO" }]));

    await expect(ticketsApi.list()).resolves.toEqual({
      next: null,
      previous: null,
      results: [],
    });
    await expect(servicesApi.list()).resolves.toEqual({
      next: null,
      previous: null,
      results: [{ code: "GEN-INFO" }],
    });
  });

  it("rebases an absolute server link through the configured authenticated API", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ results: [] }));

    await apiUrl(
      "https://untrusted.example/api/v1/tickets/?cursor=opaque%2Bcursor",
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/v1/tickets/?cursor=opaque%2Bcursor",
    );
    expect(
      new Headers((fetchMock.mock.calls[0][1] as RequestInit).headers).get(
        "Authorization",
      ),
    ).toBe("Bearer access-token");
  });
});
