import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthContextValue, AuthUser } from "@/features/auth/AuthProvider";
import type { Page } from "@/lib/collections";
import type { TicketSummary } from "@/lib/api";
import QueuePage from "./QueuePage";

const harness = vi.hoisted(() => ({
  auth: null as AuthContextValue | null,
  list: vi.fn(),
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
    ticketsApi: { ...original.ticketsApi, list: harness.list },
  };
});

const TICKET: TicketSummary = {
  id: "ticket-1",
  number: "OP-202607-000001",
  domain: "operational",
  title: "Estate query",
  channel: "web",
  priority: "P1",
  confidentiality: "normal",
  status_code: "triage",
  status_name: "Triage",
  status_public: "In review",
  requester_name: "Nandi Dlamini",
  office_code: "MHC-MBA",
  service_code: "EST-REG",
  assignee: null,
  waiting_reason: "",
  created_at: "2026-07-26T08:00:00Z",
  updated_at: "2026-07-27T08:00:00Z",
  age_hours: 24,
  sla_health: "at_risk",
};

const PAGE: Page<TicketSummary> = {
  next: null,
  previous: null,
  results: [TICKET],
};

function makeAuth(groups: string[]): AuthContextValue {
  const user: AuthUser = {
    subject: "subject-1",
    username: "agent",
    displayName: "Queue Agent",
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

function TicketLocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="ticket-location">
      {JSON.stringify({ pathname: location.pathname, state: location.state })}
    </output>
  );
}

function renderQueue({
  route = "/tickets",
  groups = ["ops-agents"],
  page = PAGE,
}: {
  route?: string;
  groups?: string[];
  page?: Page<TicketSummary>;
} = {}) {
  harness.auth = makeAuth(groups);
  harness.list.mockResolvedValue(page);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[route]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route
            path="/tickets"
            element={
              <>
                <QueuePage />
                <LocationProbe />
              </>
            }
          />
          <Route path="/tickets/:number" element={<TicketLocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function choose(label: string, option: string) {
  const user = userEvent.setup();
  await user.click(screen.getByLabelText(label));
  await user.click(await screen.findByRole("option", { name: option }));
}

beforeEach(() => {
  harness.list.mockReset();
});

describe("queue URL state", () => {
  it("hydrates controls from the URL and sends every server filter with the opaque cursor", async () => {
    renderQueue({
      route:
        "/tickets?domain=operational&status=triage&priority=P1&search=estate&sort=updated&cursor=abc",
    });

    expect(screen.getByLabelText("Search tickets")).toHaveValue("estate");
    expect(screen.getByLabelText("Filter by status")).toHaveTextContent(
      "Triage",
    );
    expect(screen.getByLabelText("Filter by priority")).toHaveTextContent("P1");
    expect(screen.getByLabelText("Sort tickets")).toHaveTextContent(
      "Recently updated",
    );
    await waitFor(() =>
      expect(harness.list).toHaveBeenCalledWith({
        domain: "operational",
        status: "triage",
        priority: "P1",
        search: "estate",
        sort: "updated",
        cursor: "abc",
      }),
    );
  });

  it("removes the cursor when search, priority, sort, or domain changes", async () => {
    renderQueue({
      route:
        "/tickets?domain=operational&priority=P1&sort=priority&cursor=opaque",
      groups: ["ops-agents", "it-agents"],
    });
    const search = screen.getByLabelText("Search tickets");

    await userEvent.setup().type(search, "estate");
    expect(screen.getByTestId("location")).toHaveTextContent(
      "domain=operational&priority=P1&sort=priority&search=estate",
    );

    await choose("Filter by priority", "P2");
    expect(screen.getByTestId("location")).not.toHaveTextContent("cursor=");

    await choose("Sort tickets", "Newest first");
    expect(screen.getByTestId("location")).not.toHaveTextContent("cursor=");

    await choose("Domain", "IT");
    expect(screen.getByTestId("location")).toHaveTextContent("domain=it");
    expect(screen.getByTestId("location")).not.toHaveTextContent("cursor=");
  });

  it("clears filters while preserving only the selected sort", async () => {
    const user = userEvent.setup();
    renderQueue({
      route:
        "/tickets?domain=operational&status=triage&priority=P1&search=estate&sort=updated&cursor=abc",
    });

    await user.click(screen.getByRole("button", { name: /clear \(4\)/i }));

    expect(screen.getByTestId("location")).toHaveTextContent("?sort=updated");
  });

  it("copies server cursors for next and previous navigation and retains returnTo on ticket links", async () => {
    const user = userEvent.setup();
    renderQueue({
      route: "/tickets?domain=operational&sort=updated",
      page: {
        next: "https://api.example/api/v1/tickets/?cursor=next%2Bopaque",
        previous: "/api/v1/tickets/?cursor=previous%2Fopaque",
        results: [TICKET],
      },
    });

    await screen.findByText("Estate query");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "domain=operational&sort=updated&cursor=next%2Bopaque",
    );
    await waitFor(() =>
      expect(harness.list).toHaveBeenLastCalledWith({
        domain: "operational",
        sort: "updated",
        cursor: "next+opaque",
      }),
    );

    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "cursor=previous%2Fopaque",
    );

    await user.click(screen.getByRole("link", { name: /estate query/i }));
    expect(screen.getByTestId("ticket-location")).toHaveTextContent(
      '"returnTo":"/tickets?domain=operational&sort=updated&cursor=previous%2Fopaque"',
    );
  });

  it("canonicalizes invalid filters and sort before making one constrained request", async () => {
    renderQueue({
      route:
        "/tickets?domain=finance&status=bogus&priority=P0&sort=random&cursor=opaque&search=estate",
      groups: ["system-admins"],
    });

    await waitFor(() =>
      expect(harness.list).toHaveBeenCalledWith({
        domain: "operational",
        search: "estate",
        sort: "priority",
      }),
    );
    expect(harness.list).toHaveBeenCalledTimes(1);
    const location = screen.getByTestId("location").textContent ?? "";
    const canonical = new URLSearchParams(location);
    expect(Object.fromEntries(canonical)).toEqual({
      domain: "operational",
      sort: "priority",
      search: "estate",
    });
  });

  it("treats malformed, missing, empty, and current cursor links as unavailable", async () => {
    renderQueue({
      route: "/tickets?cursor=current",
      page: {
        next: "http://[",
        previous: "/api/v1/tickets/?cursor=current",
        results: [TICKET],
      },
    });

    await screen.findByText("Estate query");
    expect(
      screen.queryByRole("navigation", { name: "Queue pagination" }),
    ).not.toBeInTheDocument();
  });

  it("replaces page results and removes stale pagination links on the last page", async () => {
    const lastTicket = {
      ...TICKET,
      id: "ticket-2",
      number: "OP-202607-000002",
      title: "Last page ticket",
    };
    harness.auth = makeAuth(["ops-agents"]);
    harness.list.mockImplementation((params: Record<string, string>) =>
      Promise.resolve(
        params.cursor
          ? { next: null, previous: null, results: [lastTicket] }
          : {
              next: "/api/v1/tickets/?cursor=next-page",
              previous: null,
              results: [TICKET],
            },
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={["/tickets"]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Routes>
            <Route path="/tickets" element={<QueuePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const user = userEvent.setup();
    await screen.findByText("Estate query");
    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Last page ticket")).toBeInTheDocument();
    expect(screen.queryByText("Estate query")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Queue pagination" }),
    ).not.toBeInTheDocument();
  });
});

describe("queue domain constraints", () => {
  it("does not offer cross-domain selection to a single-domain ordinary user", async () => {
    renderQueue({
      groups: ["it-agents"],
      route: "/tickets?domain=operational",
    });

    expect(screen.queryByLabelText("Domain")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(harness.list).toHaveBeenCalledWith({
        domain: "it",
        sort: "priority",
      }),
    );
    expect(harness.list).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("location")).toHaveTextContent("?domain=it");
  });

  it.each([["system-admins"], ["auditors"], ["ops-agents", "it-agents"]])(
    "offers both admitted domains to %s identities",
    async (...groups) => {
      renderQueue({ groups });

      await userEvent.setup().click(screen.getByLabelText("Domain"));
      expect(
        await screen.findByRole("option", { name: "Operational" }),
      ).toBeInTheDocument();
      expect(screen.getByRole("option", { name: "IT" })).toBeInTheDocument();
    },
  );

  it("offers both restricted queues to security responders", async () => {
    renderQueue({ groups: ["security-responders"] });

    await userEvent.setup().click(screen.getByLabelText("Domain"));
    expect(
      await screen.findByRole("option", { name: "Operational" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "IT" })).toBeInTheDocument();
    await waitFor(() =>
      expect(harness.list).toHaveBeenCalledWith({
        domain: "operational",
        sort: "priority",
      }),
    );
  });

  it.each([{ groups: [] }, { groups: ["unknown-role"] }])(
    "renders permission state without a list request for groups $groups",
    async ({ groups }) => {
      renderQueue({ groups });

      expect(
        await screen.findByRole("heading", { name: "Access not permitted" }),
      ).toBeInTheDocument();
      expect(harness.list).not.toHaveBeenCalled();
    },
  );
});
