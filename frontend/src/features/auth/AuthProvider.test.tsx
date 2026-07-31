import { useState } from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useQuery } from "@tanstack/react-query";
import type { KeycloakProfile, KeycloakTokenParsed } from "keycloak-js";
import { useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import { api, domainCapabilities } from "@/lib/api";
import { AuthProvider, useAuth } from "./AuthProvider";
import { getKeycloak, initKeycloak, isDevAuthEnabled } from "./keycloak";

vi.mock("./keycloak", () => ({
  DEV_AUTH_ENABLED: false,
  getKeycloak: vi.fn(),
  initKeycloak: vi.fn(),
  isDevAuthEnabled: vi.fn(),
}));

const RETURN_TO_KEY = "mhc.auth.returnTo";

const PRIMARY_DESIGNATION_ROLES = [
  "master",
  "deputy-master",
  "assistant-master",
  "assistant-accountant",
  "accountant",
  "senior-accountant",
  "principal-accountant",
  "financial-controller",
  "estate-examiner",
  "records-clerk",
  "data-clerk",
] as const;

interface FakeKeycloak {
  token?: string;
  tokenParsed?: KeycloakTokenParsed;
  loadUserProfile: ReturnType<typeof vi.fn>;
  updateToken: ReturnType<typeof vi.fn>;
  login: ReturnType<typeof vi.fn>;
  logout: ReturnType<typeof vi.fn>;
}

function makeKeycloak(): FakeKeycloak {
  return {
    token: "access-token",
    tokenParsed: {
      sub: "subject-123",
      preferred_username: "ignored-claim-name",
      groups: ["ops-agents", "report-viewers"],
      exp: 1_900_000_000,
    },
    loadUserProfile: vi.fn().mockResolvedValue({
      id: "subject-123",
      username: "a.agent",
      firstName: "Anele",
      lastName: "Agent",
      email: "anele@example.test",
      enabled: true,
      emailVerified: true,
      totp: false,
      createdTimestamp: 1_700_000_000,
      attributes: {},
    } satisfies KeycloakProfile),
    updateToken: vi.fn().mockResolvedValue(true),
    login: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
  };
}

function AuthProbe() {
  const auth = useAuth();
  const [token, setToken] = useState<string | null>(null);

  return (
    <div>
      <output aria-label="state">{auth.state}</output>
      <output aria-label="user">{JSON.stringify(auth.user)}</output>
      <output aria-label="expiry">{auth.expiresAt ?? "none"}</output>
      <output aria-label="dev-auth">{String(auth.isDevAuth)}</output>
      <output aria-label="token">{token ?? "none"}</output>
      <button onClick={() => void auth.login("/tickets?priority=P1")}>login</button>
      <button onClick={() => void auth.getAccessToken(true).then(setToken)}>
        refresh token
      </button>
      <button
        onClick={() =>
          void Promise.all([
            auth.getAccessToken(true),
            auth.getAccessToken(true),
          ]).then((tokens) => setToken(tokens.join(",")))
        }
      >
        refresh twice
      </button>
    </div>
  );
}

function ProtectedQueryProbe() {
  const query = useQuery({
    queryKey: ["protected-probe"],
    queryFn: () => api<{ ok: boolean }>("/tickets/"),
    retry: false,
  });
  return <output>{query.data?.ok ? "protected ready" : "protected waiting"}</output>;
}

function LoginPathProbe({ returnTo }: { returnTo: string }) {
  const auth = useAuth();
  return <button onClick={() => void auth.login(returnTo)}>login path</button>;
}

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="location">{location.pathname}</output>;
}

function OperationalNavigationProbe() {
  const { user } = useAuth();
  const domains = domainCapabilities(user?.groups ?? []).queueDomains;

  return domains.includes("operational") ? (
    <nav aria-label="Operational ticket workspace">Queue</nav>
  ) : (
    <output aria-label="Operational ticket workspace unavailable">
      No operational navigation
    </output>
  );
}

describe("AuthProvider", () => {
  let keycloak: FakeKeycloak;

  beforeEach(() => {
    sessionStorage.clear();
    keycloak = makeKeycloak();
    vi.mocked(getKeycloak).mockReturnValue(keycloak as never);
    vi.mocked(isDevAuthEnabled).mockReturnValue(false);
    vi.mocked(initKeycloak).mockResolvedValue({
      status: "unauthenticated",
    });
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("renders loading while session initialization is pending", async () => {
    let finishInitialization!: (value: { status: "unauthenticated" }) => void;
    vi.mocked(initKeycloak).mockReturnValue(
      new Promise((resolve) => {
        finishInitialization = resolve;
      }),
    );

    renderWithProviders(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );

    expect(screen.getByLabelText("state")).toHaveTextContent("loading");
    finishInitialization({ status: "unauthenticated" });
    await waitFor(() =>
      expect(screen.getByLabelText("state")).toHaveTextContent(
        "unauthenticated",
      ),
    );
  });

  it("exposes the authenticated identity and token expiry", async () => {
    vi.mocked(initKeycloak).mockResolvedValue({
      status: "authenticated",
      token: "access-token",
    });

    renderWithProviders(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByLabelText("state")).toHaveTextContent("authenticated"),
    );
    expect(screen.getByLabelText("user")).toHaveTextContent(
      JSON.stringify({
        subject: "subject-123",
        username: "a.agent",
        displayName: "Anele Agent",
        groups: ["ops-agents", "report-viewers"],
      }),
    );
    expect(screen.getByLabelText("expiry")).toHaveTextContent("1900000000");
    expect(keycloak.loadUserProfile).toHaveBeenCalledOnce();
  });

  it.each(PRIMARY_DESIGNATION_ROLES)(
    "retains the %s realm role for authenticated operational navigation only",
    async (role) => {
      keycloak.tokenParsed = {
        ...keycloak.tokenParsed,
        groups: [],
        realm_access: { roles: [role, "offline_access"] },
      };
      vi.mocked(initKeycloak).mockResolvedValue({
        status: "authenticated",
        token: "access-token",
      });

      renderWithProviders(
        <AuthProvider>
          <AuthProbe />
          <OperationalNavigationProbe />
        </AuthProvider>,
      );

      await waitFor(() =>
        expect(screen.getByLabelText("state")).toHaveTextContent(
          "authenticated",
        ),
      );
      const identity = JSON.parse(
        screen.getByLabelText("user").textContent ?? "{}",
      ) as Record<string, unknown>;
      expect(identity.groups).toEqual([role]);
      expect(identity).not.toHaveProperty("can_assign");
      expect(identity).not.toHaveProperty("office");
      expect(identity).not.toHaveProperty("service");
      expect(identity).not.toHaveProperty("queue");
      expect(identity).not.toHaveProperty("confidentiality");
      expect(
        screen.getByRole("navigation", {
          name: "Operational ticket workspace",
        }),
      ).toBeInTheDocument();
    },
  );

  it("waits for a protected consumer to request login", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByLabelText("state")).toHaveTextContent(
        "unauthenticated",
      ),
    );
    expect(keycloak.login).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "login" }));
    expect(keycloak.login).toHaveBeenCalledOnce();
  });

  it("refreshes for at least 30 seconds before returning a forced token", async () => {
    const user = userEvent.setup();
    vi.mocked(initKeycloak).mockResolvedValue({
      status: "authenticated",
      token: "access-token",
    });
    keycloak.updateToken.mockImplementation(async () => {
      keycloak.token = "fresh-token";
      return true;
    });
    renderWithProviders(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("state")).toHaveTextContent("authenticated"),
    );

    await user.click(screen.getByRole("button", { name: "refresh token" }));

    expect(keycloak.updateToken).toHaveBeenCalledWith(30);
    expect(screen.getByLabelText("token")).toHaveTextContent("fresh-token");
  });

  it("coalesces concurrent forced token refreshes", async () => {
    const user = userEvent.setup();
    vi.mocked(initKeycloak).mockResolvedValue({
      status: "authenticated",
      token: "access-token",
    });
    keycloak.updateToken.mockImplementation(async () => {
      keycloak.token = "fresh-token";
      return true;
    });
    renderWithProviders(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("state")).toHaveTextContent("authenticated"),
    );

    await user.click(screen.getByRole("button", { name: "refresh twice" }));

    expect(keycloak.updateToken).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("token")).toHaveTextContent(
      "fresh-token,fresh-token",
    );
  });

  it("does not start a protected query before deferred initialization settles", async () => {
    let finishInitialization!: (value: {
      status: "authenticated";
      token: string;
    }) => void;
    vi.mocked(initKeycloak).mockReturnValue(
      new Promise((resolve) => {
        finishInitialization = resolve;
      }),
    );
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    renderWithProviders(
      <AuthProvider>
        <ProtectedQueryProbe />
      </AuthProvider>,
    );

    await waitFor(() => expect(initKeycloak).toHaveBeenCalledOnce());
    expect(fetchMock).not.toHaveBeenCalled();
    expect(keycloak.updateToken).not.toHaveBeenCalled();
    expect(keycloak.login).not.toHaveBeenCalled();

    finishInitialization({ status: "authenticated", token: "access-token" });
    expect(await screen.findByText("protected ready")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("clears its API adapter on unmount and registers a fresh one on remount", async () => {
    vi.mocked(initKeycloak).mockResolvedValue({
      status: "authenticated",
      token: "access-token",
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const first = renderWithProviders(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("state")).toHaveTextContent("authenticated"),
    );

    first.unmount();
    await expect(api("/tickets/")).rejects.toThrow(/authentication/i);
    expect(fetchMock).not.toHaveBeenCalled();

    renderWithProviders(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("state")).toHaveTextContent("authenticated"),
    );
    await expect(api("/tickets/")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("returns the explicit development identity and raw token only when enabled", async () => {
    const user = userEvent.setup();
    vi.mocked(isDevAuthEnabled).mockReturnValue(true);
    vi.mocked(initKeycloak).mockResolvedValue({
      status: "authenticated",
      token: "dev:demo:ops-agents",
      profile: { username: "demo" },
    });
    renderWithProviders(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByLabelText("state")).toHaveTextContent("authenticated"),
    );
    expect(screen.getByLabelText("dev-auth")).toHaveTextContent("true");
    expect(screen.getByLabelText("user")).toHaveTextContent(
      JSON.stringify({
        subject: "dev:demo",
        username: "demo",
        displayName: "Demo Agent",
        groups: ["ops-agents"],
      }),
    );
    expect(keycloak.loadUserProfile).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "refresh token" }));
    expect(screen.getByLabelText("token")).toHaveTextContent(
      "dev:demo:ops-agents",
    );
  });

  it("stores a local return path before redirecting to Keycloak", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByLabelText("state")).toHaveTextContent(
        "unauthenticated",
      ),
    );

    await user.click(screen.getByRole("button", { name: "login" }));

    expect(sessionStorage.getItem(RETURN_TO_KEY)).toBe(
      "/tickets?priority=P1",
    );
    expect(keycloak.login).toHaveBeenCalledWith({
      redirectUri: `${window.location.origin}/login`,
    });
  });

  it.each([
    "//evil.example/path",
    "/\\evil.example/path",
    "https://evil.example/path",
    "tickets without a leading slash",
    "http://[malformed",
  ])("clears a previous return path for invalid input %s", async (returnTo) => {
    const user = userEvent.setup();
    sessionStorage.setItem(RETURN_TO_KEY, "/previous");
    renderWithProviders(
      <AuthProvider>
        <LoginPathProbe returnTo={returnTo} />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(initKeycloak).toHaveBeenCalledOnce(),
    );

    await user.click(screen.getByRole("button", { name: "login path" }));

    expect(sessionStorage.getItem(RETURN_TO_KEY)).toBeNull();
  });

  it("stores a normalized local pathname, encoded query, and hash", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AuthProvider>
        <LoginPathProbe
          returnTo="/tickets/../queue?return=%2Ftickets%3Fpriority%3DP1#summary"
        />
      </AuthProvider>,
    );
    await waitFor(() => expect(initKeycloak).toHaveBeenCalledOnce());

    await user.click(screen.getByRole("button", { name: "login path" }));

    expect(sessionStorage.getItem(RETURN_TO_KEY)).toBe(
      "/queue?return=%2Ftickets%3Fpriority%3DP1#summary",
    );
  });

  it("consumes a stored local return path once after authentication", async () => {
    sessionStorage.setItem(RETURN_TO_KEY, "/tickets?priority=P1");
    vi.mocked(initKeycloak).mockResolvedValue({
      status: "authenticated",
      token: "access-token",
    });
    renderWithProviders(
      <AuthProvider>
        <AuthProbe />
        <LocationProbe />
      </AuthProvider>,
      { route: "/login" },
    );

    await waitFor(() =>
      expect(screen.getByLabelText("location")).toHaveTextContent("/tickets"),
    );
    expect(sessionStorage.getItem(RETURN_TO_KEY)).toBeNull();
  });
});

it("keeps development authentication disabled in production mode", async () => {
  vi.resetModules();
  vi.doUnmock("./keycloak");
  vi.stubEnv("MODE", "production");
  vi.stubEnv("VITE_DEV_AUTH", "1");

  const productionAdapter = await import("./keycloak");

  expect(productionAdapter.isDevAuthEnabled()).toBe(false);
  vi.unstubAllEnvs();
});
