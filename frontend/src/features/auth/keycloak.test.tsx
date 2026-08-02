import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const keycloakMock = vi.hoisted(() => {
  const instance = {
    init: vi.fn(),
    token: "access-token",
    tokenParsed: {
      sub: "subject-123",
      groups: ["ops-agents"],
      exp: 1_900_000_000,
    },
    profile: { username: "a.agent" },
    loadUserProfile: vi.fn().mockResolvedValue({ username: "a.agent" }),
    updateToken: vi.fn().mockResolvedValue(true),
    login: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
  };
  const constructor = vi.fn(function MockKeycloak() {
    return instance;
  });
  return { constructor, instance };
});

vi.mock("keycloak-js", () => ({ default: keycloakMock.constructor }));

const LIFECYCLE_KEY = Symbol.for("mhc-ticketing.keycloak-lifecycle");

function router(ui: React.ReactNode) {
  return (
    <MemoryRouter
      initialEntries={["/login"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      {ui}
    </MemoryRouter>
  );
}

describe("Keycloak initialization lifecycle", () => {
  beforeEach(() => {
    delete (globalThis as Record<symbol, unknown>)[LIFECYCLE_KEY];
    vi.resetModules();
    keycloakMock.constructor.mockClear();
    keycloakMock.instance.init.mockReset();
    keycloakMock.instance.loadUserProfile.mockClear();
  });

  it("coalesces repeated callers and caches a successful lifecycle", async () => {
    keycloakMock.instance.init.mockResolvedValue(false);
    const { initKeycloak } = await import("./keycloak");

    const first = initKeycloak();
    const second = initKeycloak();

    await expect(Promise.all([first, second])).resolves.toEqual([
      { status: "unauthenticated" },
      { status: "unauthenticated" },
    ]);
    await expect(initKeycloak()).resolves.toEqual({
      status: "unauthenticated",
    });
    expect(keycloakMock.instance.init).toHaveBeenCalledOnce();
  });

  it("initializes once for the current login page in StrictMode and across remounts", async () => {
    keycloakMock.instance.init.mockResolvedValue(false);
    const [{ AuthProvider }, { default: LoginPage }] = await Promise.all([
      import("./AuthProvider"),
      import("./LoginPage"),
    ]);

    const firstMount = render(
      router(
        <StrictMode>
          <AuthProvider>
            <LoginPage />
          </AuthProvider>
        </StrictMode>,
      ),
    );
    await screen.findByRole("button", { name: /sign in with keycloak/i });
    expect(keycloakMock.instance.init).toHaveBeenCalledOnce();

    firstMount.unmount();
    render(router(<AuthProvider><LoginPage /></AuthProvider>));
    await screen.findByRole("button", { name: /sign in with keycloak/i });
    expect(keycloakMock.instance.init).toHaveBeenCalledOnce();
  });

  it("allows a later caller to retry after a genuine initialization rejection", async () => {
    keycloakMock.instance.init
      .mockRejectedValueOnce(new Error("identity service unavailable"))
      .mockResolvedValueOnce(false);
    const { initKeycloak } = await import("./keycloak");

    await expect(initKeycloak()).resolves.toEqual({
      status: "error",
      error: "identity service unavailable",
    });
    await expect(initKeycloak()).resolves.toEqual({
      status: "unauthenticated",
    });
    expect(keycloakMock.instance.init).toHaveBeenCalledTimes(2);
  });

  it("returns a useful message when the Keycloak adapter rejects without an error", async () => {
    keycloakMock.instance.init.mockRejectedValue(undefined);
    const { initKeycloak } = await import("./keycloak");

    await expect(initKeycloak()).resolves.toEqual({
      status: "error",
      error: "Keycloak authentication failed. Please try again.",
    });
  });

  it("reuses a successful lifecycle after a module reload", async () => {
    keycloakMock.instance.init.mockResolvedValue(false);
    const firstModule = await import("./keycloak");
    await firstModule.initKeycloak();

    vi.resetModules();
    const reloadedModule = await import("./keycloak");
    await reloadedModule.initKeycloak();

    expect(keycloakMock.instance.init).toHaveBeenCalledOnce();
  });

  it("shares a pending initialization between callers", async () => {
    let settle!: (authenticated: boolean) => void;
    keycloakMock.instance.init.mockReturnValue(
      new Promise((resolve) => {
        settle = resolve;
      }),
    );
    const { initKeycloak } = await import("./keycloak");

    const first = initKeycloak();
    const second = initKeycloak();
    expect(keycloakMock.instance.init).toHaveBeenCalledOnce();

    settle(false);
    await expect(first).resolves.toEqual({ status: "unauthenticated" });
    await expect(second).resolves.toEqual({ status: "unauthenticated" });
  });
});
