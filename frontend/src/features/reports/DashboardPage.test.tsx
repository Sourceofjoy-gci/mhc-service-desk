import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthContextValue, AuthUser } from "@/features/auth/AuthProvider";
import { ApiError, type DashboardData } from "@/lib/api";
import DashboardPage from "./DashboardPage";

const harness = vi.hoisted(() => ({
  auth: null as AuthContextValue | null,
  dashboard: vi.fn(),
}));

vi.mock("@/features/auth/AuthProvider", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/features/auth/AuthProvider")>();
  return {
    ...original,
    useAuth: () => {
      if (!harness.auth) throw new Error("Missing test auth state");
      return harness.auth;
    },
  };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: { ...original.ticketsApi, dashboard: harness.dashboard },
  };
});

const DASHBOARD: DashboardData = {
  totals: { open: 7, today: 2, this_week: 5 },
  by_priority: [{ priority: "P1", count: 2 }],
  by_status: [{ status__code: "triage", status__name: "Triage", count: 3 }],
  unassigned: 1,
  breached_sla: 1,
};

function makeAuth(groups: string[]): AuthContextValue {
  const user: AuthUser = {
    subject: "subject-1",
    username: "analyst",
    displayName: "Report Analyst",
    groups,
  };
  return {
    state: "authenticated",
    user,
    error: null,
    expiresAt: null,
    isDevAuth: false,
    getAccessToken: vi.fn().mockResolvedValue("token"),
    login: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn().mockResolvedValue(undefined),
  };
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

function renderDashboard({
  route = "/dashboard",
  groups = ["ops-agents"],
}: {
  route?: string;
  groups?: string[];
} = {}) {
  harness.auth = makeAuth(groups);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[route]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <DashboardPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  harness.dashboard.mockReset().mockResolvedValue(DASHBOARD);
});

describe("dashboard domain state", () => {
  it("defaults an Operational identity to the Operational dashboard", async () => {
    renderDashboard({ groups: ["ops-agents"] });

    expect(
      await screen.findByRole("heading", { name: "Operational dashboard" }),
    ).toBeInTheDocument();
    expect(harness.dashboard).toHaveBeenCalledWith("operational");
    expect(screen.queryByLabelText("Dashboard domain")).not.toBeInTheDocument();
  });

  it("defaults an IT identity to the IT dashboard", async () => {
    harness.dashboard.mockResolvedValue({
      ...DASHBOARD,
      breached_sla: undefined,
      p1p2: 4,
    });
    renderDashboard({ groups: ["it-agents"] });

    expect(
      await screen.findByRole("heading", { name: "IT dashboard" }),
    ).toBeInTheDocument();
    expect(harness.dashboard).toHaveBeenCalledWith("it");
    expect(screen.getByText("P1/P2 open")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("lets an administrator select either admitted domain through the URL", async () => {
    const user = userEvent.setup();
    renderDashboard({ groups: ["system-admins"] });

    await screen.findByRole("heading", { name: "Operational dashboard" });
    await user.click(screen.getByLabelText("Dashboard domain"));
    await user.click(await screen.findByRole("option", { name: "IT" }));

    expect(screen.getByTestId("location")).toHaveTextContent("?domain=it");
    await waitFor(() =>
      expect(harness.dashboard).toHaveBeenLastCalledWith("it"),
    );
  });

  it("constrains an invalid URL domain to the identity's admitted domain", async () => {
    renderDashboard({
      groups: ["it-agents"],
      route: "/dashboard?domain=operational",
    });

    await waitFor(() => expect(harness.dashboard).toHaveBeenCalledWith("it"));
    expect(screen.getByTestId("location")).toHaveTextContent("?domain=it");
  });
});

describe("dashboard permission state", () => {
  it("renders PermissionPage for a 403 without initiating login", async () => {
    harness.dashboard.mockRejectedValue(
      new ApiError(403, { detail: "domain_scope_required" }),
    );
    renderDashboard({ groups: ["ops-agents"] });

    expect(
      await screen.findByRole("heading", { name: "Access not permitted" }),
    ).toBeInTheDocument();
    expect(screen.getByText("403")).toBeInTheDocument();
    expect(harness.auth?.login).not.toHaveBeenCalled();
  });
});
