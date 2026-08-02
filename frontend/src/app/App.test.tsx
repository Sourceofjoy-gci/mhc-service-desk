import { StrictMode } from "react";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthContextValue, AuthUser } from "@/features/auth/AuthProvider";
import { ThemeProvider } from "@/components/theme-provider";
import { renderWithProviders } from "@/test/render";
import App from "./App";

const authHarness = vi.hoisted(() => ({
  current: null as AuthContextValue | null,
}));

vi.mock("@/features/auth/AuthProvider", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/features/auth/AuthProvider")>();
  return {
    ...original,
    useAuth: () => {
      if (!authHarness.current) throw new Error("Test auth state is missing");
      return authHarness.current;
    },
  };
});

const STAFF_USER: AuthUser = {
  subject: "subject-123",
  username: "a.agent",
  displayName: "Anele Agent",
  groups: ["ops-agents"],
};

function makeAuth(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    state: "unauthenticated",
    user: null,
    error: null,
    expiresAt: null,
    isDevAuth: false,
    getAccessToken: vi.fn().mockResolvedValue(null),
    login: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

function renderApp(
  path: string,
  auth: AuthContextValue,
  { strict = false }: { strict?: boolean } = {},
) {
  authHarness.current = auth;
  const app = (
    <ThemeProvider>
      <App />
    </ThemeProvider>
  );
  return renderWithProviders(strict ? <StrictMode>{app}</StrictMode> : app, {
    route: path,
  });
}

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
});

describe("App route boundaries", () => {
  it.each([
    ["/login", "Agent sign-in"],
    ["/health", "System health"],
  ])(
    "%s renders its public content without staff navigation",
    (path, heading) => {
      renderApp(path, makeAuth());

      expect(
        screen.getByRole("navigation", { name: /public services/i }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: heading }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("navigation", { name: /ticket workspace/i }),
      ).not.toBeInTheDocument();
    },
  );

  it("does not expose the public intake form", () => {
    renderApp("/public", makeAuth());

    expect(
      screen.getByRole("heading", { name: /page not found/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /submit a request/i }),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("main")).getByRole("link", {
        name: /staff sign-in/i,
      }),
    ).toBeInTheDocument();
  });

  it("protects the ticket queue, preserves its return path, and redirects once in StrictMode", async () => {
    const auth = makeAuth();

    renderApp("/tickets?priority=P1", auth, { strict: true });

    await waitFor(() =>
      expect(auth.login).toHaveBeenCalledWith("/tickets?priority=P1"),
    );
    expect(auth.login).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("heading", { name: "Queue" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: /ticket workspace/i }),
    ).not.toBeInTheDocument();
  });

  it("protects ticket tracking and preserves the requested reference", async () => {
    const auth = makeAuth();

    renderApp("/ticket-tracking?reference=O00123", auth);

    await waitFor(() =>
      expect(auth.login).toHaveBeenCalledWith(
        "/ticket-tracking?reference=O00123",
      ),
    );
    expect(
      screen.queryByRole("heading", { name: "Track a ticket" }),
    ).not.toBeInTheDocument();
  });

  it("shows an accessible redirect failure and retries once per deliberate attempt", async () => {
    const user = userEvent.setup();
    const firstAttempt = deferred();
    const secondAttempt = deferred();
    const login = vi
      .fn()
      .mockReturnValueOnce(firstAttempt.promise)
      .mockReturnValueOnce(secondAttempt.promise);
    const auth = makeAuth({ login });
    const view = renderApp("/tickets?priority=P1", auth, { strict: true });

    await waitFor(() => expect(login).toHaveBeenCalledTimes(1));
    await act(async () => {
      firstAttempt.reject(new Error("Identity redirect was blocked"));
      await firstAttempt.promise.catch(() => undefined);
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Identity redirect was blocked",
    );
    expect(
      screen.queryByRole("navigation", { name: /ticket workspace/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Queue" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /retry sign-in/i }));

    expect(screen.getByRole("status")).toHaveAccessibleName(
      /redirecting to sign in/i,
    );
    await waitFor(() => expect(login).toHaveBeenCalledTimes(2));
    view.unmount();
    await act(async () => {
      secondAttempt.reject(new Error("Late redirect failure"));
      await secondAttempt.promise.catch(() => undefined);
    });
  });

  it("does not flash protected content while authentication is loading", () => {
    renderApp("/intake/call", makeAuth({ state: "loading" }));

    expect(screen.getByRole("status")).toHaveAccessibleName(
      /checking your session/i,
    );
    expect(
      screen.queryByRole("heading", { name: /call-centre capture/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: /ticket workspace/i }),
    ).not.toBeInTheDocument();
  });

  it("renders an accessible authentication error without staff content", () => {
    renderApp(
      "/intake/call",
      makeAuth({ state: "error", error: "Identity service unavailable" }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Identity service unavailable",
    );
    expect(
      screen.queryByRole("heading", { name: /call-centre capture/i }),
    ).not.toBeInTheDocument();
  });

  it("normalizes the identity used by the user-menu name and initials", () => {
    const identityCases = [
      {
        displayName: "   ",
        username: "  backup.agent  ",
        label: "backup.agent",
        initials: "BA",
      },
      {
        displayName: "Anele",
        username: "a.agent",
        label: "Anele",
        initials: "AN",
      },
      {
        displayName: "  Anele Agent  ",
        username: "a.agent",
        label: "Anele Agent",
        initials: "AA",
      },
      {
        displayName: "  Łukasz Żółć  ",
        username: "l.zolc",
        label: "Łukasz Żółć",
        initials: "ŁŻ",
      },
      {
        displayName: "",
        username: " ",
        label: "Signed-in user",
        initials: "SU",
      },
    ];

    for (const identity of identityCases) {
      const { unmount } = renderApp(
        "/intake/call",
        makeAuth({
          state: "authenticated",
          user: {
            ...STAFF_USER,
            displayName: identity.displayName,
            username: identity.username,
          },
        }),
      );

      const menu = screen.getByRole("button", {
        name: `User menu for ${identity.label}`,
      });
      expect(menu).toHaveTextContent(identity.initials);
      unmount();
    }
  });

  it("renders the authenticated staff shell with provider identity", async () => {
    const user = userEvent.setup();
    renderApp(
      "/intake/call",
      makeAuth({ state: "authenticated", user: STAFF_USER }),
    );

    expect(
      screen.getByRole("navigation", { name: /ticket workspace/i }),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("navigation", { name: /ticket workspace/i }),
      ).getByRole("link", { name: "Track ticket" }),
    ).toHaveAttribute("href", "/ticket-tracking");
    const menu = screen.getByRole("button", {
      name: /user menu for anele agent/i,
    });
    expect(menu).toHaveTextContent("AA");

    menu.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByText("Anele Agent")).toBeInTheDocument();
    expect(screen.getByText("a.agent")).toBeInTheDocument();
    expect(screen.queryByText("Development access")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /search/i }),
    ).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
  });

  it("shows development access only for development authentication", () => {
    renderApp(
      "/intake/call",
      makeAuth({
        state: "authenticated",
        user: STAFF_USER,
        isDevAuth: true,
      }),
    );

    expect(screen.getByText("Development access")).toBeInTheDocument();
  });

  it("logs out through the auth provider", async () => {
    const user = userEvent.setup();
    const auth = makeAuth({ state: "authenticated", user: STAFF_USER });
    renderApp("/intake/call", auth);

    screen.getByRole("button", { name: /user menu for anele agent/i }).focus();
    await user.keyboard("{Enter}");
    await user.click(
      await screen.findByRole("menuitem", { name: /sign out/i }),
    );

    expect(auth.logout).toHaveBeenCalledTimes(1);
  });

  it("prevents duplicate staff logout and exposes a rejected logout", async () => {
    const user = userEvent.setup();
    const logoutAttempt = deferred();
    const logout = vi.fn().mockReturnValue(logoutAttempt.promise);
    renderApp(
      "/intake/call",
      makeAuth({ state: "authenticated", user: STAFF_USER, logout }),
    );

    screen.getByRole("button", { name: /user menu for anele agent/i }).focus();
    await user.keyboard("{Enter}");
    await user.click(
      await screen.findByRole("menuitem", { name: /^sign out$/i }),
    );

    const pendingItem = await screen.findByRole("menuitem", {
      name: /signing out/i,
    });
    expect(pendingItem).toHaveAttribute("aria-disabled", "true");
    await user.click(pendingItem);
    expect(logout).toHaveBeenCalledTimes(1);

    await act(async () => {
      logoutAttempt.reject(new Error("Logout endpoint unavailable"));
      await logoutAttempt.promise.catch(() => undefined);
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Logout endpoint unavailable",
    );
  });

  it("renders forbidden as a public permission state without initiating login", () => {
    const auth = makeAuth();
    renderApp("/forbidden", auth);

    expect(
      screen.getByRole("heading", { name: /access not permitted/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("403")).toBeInTheDocument();
    expect(auth.login).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("navigation", { name: /ticket workspace/i }),
    ).not.toBeInTheDocument();
  });

  it("uses the auth provider to start an explicit sign-in", async () => {
    const user = userEvent.setup();
    const auth = makeAuth();
    renderApp("/login", auth);

    await user.click(
      screen.getByRole("button", { name: /sign in with keycloak/i }),
    );

    expect(auth.login).toHaveBeenCalledWith("/");
  });

  it("renders an accessible LoginPage loading state", () => {
    renderApp("/login", makeAuth({ state: "loading" }));

    const status = screen.getByRole("status", {
      name: /checking authentication status/i,
    });
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-busy", "true");
  });

  it("renders LoginPage unauthenticated guidance and action", () => {
    renderApp("/login", makeAuth());

    expect(
      screen.getByText(/redirected to the keycloak realm/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign in with keycloak/i }),
    ).toBeEnabled();
  });

  it("renders LoginPage authenticated identity and sign-out action", () => {
    renderApp(
      "/login",
      makeAuth({
        state: "authenticated",
        user: STAFF_USER,
        expiresAt: 1_900_000_000,
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Signed in as Anele Agent",
    );
    expect(screen.getByRole("button", { name: /sign out/i })).toBeEnabled();
  });

  it("renders provider initialization errors without a nonfunctional retry action", () => {
    renderApp(
      "/login",
      makeAuth({ state: "error", error: "Keycloak initialization failed" }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Keycloak initialization failed",
    );
    expect(
      screen.queryByRole("button", { name: /try sign-in again/i }),
    ).not.toBeInTheDocument();
  });

  it("renders truthful development access without a no-op sign-out", () => {
    renderApp(
      "/login",
      makeAuth({
        state: "authenticated",
        user: STAFF_USER,
        isDevAuth: true,
      }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Local development access is active. Sign-out is unavailable in this mode.",
    );
    expect(
      screen.queryByRole("button", { name: /sign out/i }),
    ).not.toBeInTheDocument();
  });

  it("prevents duplicate LoginPage sign-in and exposes a rejected action", async () => {
    const user = userEvent.setup();
    const loginAttempt = deferred();
    const login = vi.fn().mockReturnValue(loginAttempt.promise);
    renderApp("/login", makeAuth({ login }));

    await user.click(
      screen.getByRole("button", { name: /sign in with keycloak/i }),
    );

    const pendingButton = screen.getByRole("button", { name: /signing in/i });
    expect(pendingButton).toBeDisabled();
    await user.click(pendingButton);
    expect(login).toHaveBeenCalledTimes(1);

    await act(async () => {
      loginAttempt.reject(new Error("Popup was blocked"));
      await loginAttempt.promise.catch(() => undefined);
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Popup was blocked");
    expect(
      screen.getByRole("button", { name: /sign in with keycloak/i }),
    ).toBeEnabled();
  });

  it("prevents duplicate LoginPage sign-out and exposes a rejected action", async () => {
    const user = userEvent.setup();
    const logoutAttempt = deferred();
    const logout = vi.fn().mockReturnValue(logoutAttempt.promise);
    renderApp(
      "/login",
      makeAuth({ state: "authenticated", user: STAFF_USER, logout }),
    );

    await user.click(screen.getByRole("button", { name: /^sign out$/i }));

    const pendingButton = screen.getByRole("button", { name: /signing out/i });
    expect(pendingButton).toBeDisabled();
    await user.click(pendingButton);
    expect(logout).toHaveBeenCalledTimes(1);

    await act(async () => {
      logoutAttempt.reject(new Error("Logout request failed"));
      await logoutAttempt.promise.catch(() => undefined);
    });

    expect(
      screen.getByText("Logout request failed").closest('[role="alert"]'),
    ).toBeInTheDocument();
  });

  it("renders unknown routes in the public shell without initiating login", () => {
    const auth = makeAuth();
    renderApp("/tickets/unknown/extra", auth);

    expect(
      screen.getByRole("heading", { name: /page not found/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: /public services/i }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("main")).getByRole("link", {
        name: /staff sign-in/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: /ticket workspace/i }),
    ).not.toBeInTheDocument();
    expect(auth.login).not.toHaveBeenCalled();
  });
});
