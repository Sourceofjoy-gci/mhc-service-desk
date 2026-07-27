import { StrictMode } from "react";
import { screen, waitFor } from "@testing-library/react";
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
  it.each(["/login", "/public", "/health"])(
    "%s renders without staff navigation",
    (path) => {
      renderApp(path, makeAuth());

      expect(
        screen.queryByRole("navigation", { name: /ticket workspace/i }),
      ).not.toBeInTheDocument();
    },
  );

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

  it("renders the authenticated staff shell with provider identity", async () => {
    const user = userEvent.setup();
    renderApp(
      "/intake/call",
      makeAuth({ state: "authenticated", user: STAFF_USER }),
    );

    expect(
      screen.getByRole("navigation", { name: /ticket workspace/i }),
    ).toBeInTheDocument();
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
});
