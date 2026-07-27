import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiLinkError,
  configureApiAuth,
  apiUrl,
  domainCapabilities,
  servicesApi,
  ticketsApi,
  type ApiAuthAdapter,
} from "./api";
import {
  CollectionContractError,
  cursorFromPageLink,
  normalizePage,
} from "./collections";

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

  it.each([
    null,
    {},
    { next: null, previous: null, results: null },
    { next: 4, previous: null, results: [] },
    { next: null, results: [] },
  ])("rejects malformed collection payload %#", (value) => {
    expect(() => normalizePage(value)).toThrow(CollectionContractError);
  });
});

describe("cursorFromPageLink", () => {
  it.each([
    [null, "current", null],
    ["", "current", null],
    ["http://[", "current", null],
    ["/api/v1/tickets/", "current", null],
    ["/api/v1/tickets/?cursor=", "current", null],
    ["/api/v1/tickets/?cursor=current", "current", null],
    ["/api/v1/tickets/?cursor=next%2Bopaque", "current", "next+opaque"],
  ])("safely parses %#", (link, current, expected) => {
    expect(cursorFromPageLink(link, current)).toBe(expected);
  });
});

describe("domainCapabilities", () => {
  const operationalAliases = [
    "agent-operational",
    "ops-agents",
    "supervisor-operational",
    "ops-supervisors",
  ];
  const itAliases = ["agent-it", "it-agents", "lead-it", "it-leads"];
  const allDomainAliases = ["admin", "system-admins", "auditor", "auditors"];

  it.each(operationalAliases)("admits operational alias %s", (group) => {
    expect(domainCapabilities([group])).toEqual({
      queueDomains: ["operational"],
      dashboardDomains: ["operational"],
    });
  });

  it.each(itAliases)("admits IT alias %s", (group) => {
    expect(domainCapabilities([group])).toEqual({
      queueDomains: ["it"],
      dashboardDomains: ["it"],
    });
  });

  it.each(allDomainAliases)("admits unrestricted alias %s", (group) => {
    expect(domainCapabilities([group])).toEqual({
      queueDomains: ["operational", "it"],
      dashboardDomains: ["operational", "it"],
    });
  });

  it.each([...operationalAliases, ...itAliases, ...allDomainAliases])(
    "recognizes the basename of full-path claim %s",
    (group) => {
      expect(domainCapabilities([`/realm/client/${group}`])).toEqual(
        domainCapabilities([group]),
      );
    },
  );

  it("separates restricted queue visibility from dashboard access", () => {
    expect(domainCapabilities(["security-responders"])).toEqual({
      queueDomains: ["operational", "it"],
      dashboardDomains: [],
    });
    expect(domainCapabilities(["/realm/client/security-responders"])).toEqual({
      queueDomains: ["operational", "it"],
      dashboardDomains: [],
    });
  });

  it("combines ordinary domain roles and rejects unknown roles", () => {
    expect(domainCapabilities(["ops-agents", "it-agents"])).toEqual({
      queueDomains: ["operational", "it"],
      dashboardDomains: ["operational", "it"],
    });
    expect(domainCapabilities(["unknown-role"])).toEqual({
      queueDomains: [],
      dashboardDomains: [],
    });
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

  afterEach(() => {
    disposeAuth();
    vi.restoreAllMocks();
  });

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

  it.each([
    [ticketsApi.list, null],
    [servicesApi.list, { next: null, previous: null, results: null }],
  ])("rejects malformed collection responses at the network boundary", async (request, body) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse(body));

    await expect(request()).rejects.toBeInstanceOf(CollectionContractError);
  });

  it.each(["http://[", "/outside/tickets/?cursor=opaque"])(
    "rejects an unusable server link %s with a controlled error",
    async (link) => {
      await expect(apiUrl(link)).rejects.toBeInstanceOf(ApiLinkError);
    },
  );
});
