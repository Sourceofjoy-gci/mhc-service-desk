import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  type Location,
} from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ActivityItem, type TicketDetail } from "@/lib/api";
import { TicketCard } from "./TicketCard";
import TicketDetailPage from "./TicketDetailPage";

const harness = vi.hoisted(() => ({
  get: vi.fn(),
  activity: vi.fn(),
  addMessage: vi.fn(),
  addNote: vi.fn(),
  transition: vi.fn(),
  updateWorkState: vi.fn(),
  assignees: vi.fn(),
  attachmentList: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      get: harness.get,
      activity: harness.activity,
      addMessage: harness.addMessage,
      addNote: harness.addNote,
      transition: harness.transition,
      updateWorkState: harness.updateWorkState,
      assignees: harness.assignees,
    },
    attachmentsApi: {
      ...original.attachmentsApi,
      list: harness.attachmentList,
    },
  };
});

const TICKET: TicketDetail = {
  id: "ticket-1",
  number: "OP-202607-000001",
  domain: "operational",
  title: "Estate follow-up",
  channel: "web",
  priority: "P2",
  confidentiality: "normal",
  status_code: "assigned",
  status_name: "Assigned",
  status_public: "In progress",
  requester_name: "Naledi Dube",
  office_code: "JHB",
  service_code: "ESTATES",
  assignee: "agent-1",
  waiting_reason: "requester",
  created_at: "2026-07-27T08:00:00Z",
  updated_at: "2026-07-27T09:15:00Z",
  age_hours: 1.25,
  sla_health: "on_track",
  available_transition_codes: ["in_progress"],
  description: "Please confirm the estate status.",
  requester: {
    id: "requester-1",
    full_name: "Naledi Dube",
    email: "naledi@example.test",
    phone_e164: "+27115550123",
  },
  service: "Estates",
  request_type: "Follow-up",
  office: "Johannesburg",
  matter_reference: "EST-42",
  tags: [],
  custom_fields: {},
  resolution_code: "",
  resolution_summary: "",
  acknowledged_at: "2026-07-27T08:15:00Z",
  first_responded_at: null,
  resolved_at: null,
  closed_at: null,
  reopened_at: null,
  assignee_detail: { id: "agent-1", display_name: "Case Agent" },
  team: "Estates",
  blocked_reason: "",
  next_action: "Review file",
  next_action_at: "2026-07-28T08:00:00Z",
  available_transitions: [
    {
      to_status: "in_progress",
      label: "Start work",
      requires_resolution: false,
      requires_reason: false,
    },
  ],
  capabilities: {
    can_update_work_state: true,
    can_self_assign: false,
    self_assignee_id: null,
    can_reassign: false,
    can_change_confidentiality: false,
    can_add_message: true,
    can_add_note: true,
    can_upload_attachment: true,
  },
  sla_clocks: {
    first_response: {
      state: "running",
      due_at: "2026-07-27T10:00:00Z",
      remaining_seconds: 2700,
      overdue_seconds: 0,
    },
    resolution: {
      state: "running",
      due_at: "2026-07-28T08:00:00Z",
      remaining_seconds: 81900,
      overdue_seconds: 0,
    },
  },
  relationships: [
    {
      id: "relationship-1",
      kind: "related",
      ticket_number: "IT-202607-000042",
      direction: "outgoing",
    },
    {
      id: "relationship-2",
      kind: "duplicate",
      ticket_number: "//outside.example/path",
      direction: "incoming",
    },
  ],
  attachments: [],
  messages: [],
  notes: [],
};

const INITIAL_ACTIVITY: ActivityItem = {
  id: "activity-1",
  type: "status_transition",
  occurred_at: "2026-07-27T09:00:00Z",
  actor: { subject: "agent-1", display_name: "Case Agent" },
  visibility: "internal",
  payload: {
    from: "triage",
    to: "assigned",
    reason: "Assigned to Estates",
  },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {JSON.stringify({ pathname: location.pathname, state: location.state })}
    </output>
  );
}

function renderDetail({
  state,
}: {
  state?: Location["state"];
} = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter
        initialEntries={[
          {
            pathname: `/tickets/${TICKET.number}`,
            state,
          },
        ]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/tickets/:number" element={<TicketDetailPage />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  return { ...result, queryClient };
}

beforeEach(() => {
  harness.get.mockReset().mockResolvedValue(TICKET);
  harness.activity.mockReset().mockResolvedValue({
    results: [INITIAL_ACTIVITY],
  });
  harness.addMessage.mockReset().mockResolvedValue({ id: "message-1" });
  harness.addNote.mockReset().mockResolvedValue({ id: "note-1" });
  harness.transition.mockReset();
  harness.updateWorkState.mockReset();
  harness.assignees.mockReset().mockResolvedValue({ results: [] });
  harness.attachmentList.mockReset().mockResolvedValue({ results: [] });
});

describe("ticket operator workspace", () => {
  it("renders the lifecycle workspace in action-first mobile order with preserved context", async () => {
    renderDetail();

    expect(
      await screen.findByRole("heading", { name: "Estate follow-up" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to queue" })).toHaveAttribute(
      "href",
      "/tickets",
    );
    expect(screen.getByText(TICKET.number)).toBeVisible();
    expect(screen.getByText("Assigned")).toBeVisible();
    expect(screen.getByText("P2")).toBeVisible();
    expect(screen.getAllByText("Web").length).toBeGreaterThan(0);
    expect(screen.getByText(TICKET.description)).toBeVisible();

    const action = screen.getByRole("button", { name: "Start work" });
    const activity = screen.getByRole("heading", { name: "Activity" });
    const operations = screen.getByRole("heading", { name: "Operations" });
    expect(action).toBeVisible();
    expect(activity).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Add to activity" }),
    ).toBeVisible();
    expect(operations).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Service targets" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Relationships" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "Attachments" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Requester" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Classification" }),
    ).toBeVisible();
    expect(screen.getByText("naledi@example.test")).toBeVisible();
    expect(screen.getByText("EST-42")).toBeVisible();

    expect(
      action.compareDocumentPosition(activity) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      activity.compareDocumentPosition(operations) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByTestId("ticket-workspace-layout")).toHaveClass(
      "lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]",
    );
  });

  it("replaces the exact ticket cache only after a transition succeeds", async () => {
    const pending = deferred<TicketDetail>();
    const refreshed = {
      ...TICKET,
      status_code: "in_progress",
      status_name: "In Progress",
      updated_at: "2026-07-27T09:16:00Z",
    };
    harness.transition.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    const { queryClient } = renderDetail();

    await screen.findByRole("heading", { name: TICKET.title });
    await user.click(screen.getByRole("button", { name: "Start work" }));
    await user.click(
      screen.getByRole("button", { name: "Confirm Start work" }),
    );

    expect(queryClient.getQueryData(["ticket", TICKET.number])).toEqual(TICKET);
    await act(async () => pending.resolve(refreshed));

    await waitFor(() =>
      expect(queryClient.getQueryData(["ticket", TICKET.number])).toEqual(
        refreshed,
      ),
    );
    expect(screen.getByText("In Progress")).toBeVisible();
  });

  it("replaces the exact ticket cache only after an operations update succeeds", async () => {
    const pending = deferred<TicketDetail>();
    const refreshed = {
      ...TICKET,
      team: "Litigation",
      updated_at: "2026-07-27T09:17:00Z",
    };
    harness.updateWorkState.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    const { queryClient } = renderDetail();

    const team = await screen.findByRole("textbox", { name: "Team" });
    await user.clear(team);
    await user.type(team, "Litigation");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(queryClient.getQueryData(["ticket", TICKET.number])).toEqual(TICKET);
    await act(async () => pending.resolve(refreshed));

    await waitFor(() =>
      expect(queryClient.getQueryData(["ticket", TICKET.number])).toEqual(
        refreshed,
      ),
    );
    expect(screen.getByRole("textbox", { name: "Team" })).toHaveValue(
      "Litigation",
    );
  });

  it("refetches the exact ticket and activity when an operator accepts a stale reload", async () => {
    const refreshed = {
      ...TICKET,
      title: "Estate follow-up reloaded",
      updated_at: "2026-07-27T09:18:00Z",
    };
    harness.get.mockResolvedValueOnce(TICKET).mockResolvedValueOnce(refreshed);
    harness.updateWorkState.mockRejectedValue(
      new ApiError(409, {
        code: "stale_ticket",
        detail: "The ticket changed.",
        fields: { updated_at: [refreshed.updated_at] },
        correlation_id: "corr-stale-workspace",
      }),
    );
    const user = userEvent.setup();
    const { queryClient } = renderDetail();
    const refetch = vi.spyOn(queryClient, "refetchQueries");
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    const team = await screen.findByRole("textbox", { name: "Team" });
    await user.clear(team);
    await user.type(team, "Litigation");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.click(await screen.findByRole("button", { name: "Reload" }));

    await screen.findByRole("heading", { name: refreshed.title });
    expect(refetch).toHaveBeenCalledWith({
      queryKey: ["ticket", TICKET.number],
      exact: true,
    });
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["ticket-activity", TICKET.number],
      exact: true,
    });
    await waitFor(() => expect(harness.activity).toHaveBeenCalledTimes(2));
    expect(harness.get).toHaveBeenCalledTimes(2);
  });

  it("refreshes the exact activity stream after a successful reply", async () => {
    const createdActivity: ActivityItem = {
      id: "activity-2",
      type: "message",
      occurred_at: "2026-07-27T09:20:00Z",
      actor: { subject: "agent-1", display_name: "Case Agent" },
      visibility: "requester",
      payload: {
        body_text: "The estate file is ready.",
        direction: "outbound",
        delivery_status: "sent",
      },
    };
    harness.activity
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({ results: [createdActivity] });
    const user = userEvent.setup();
    renderDetail();

    await screen.findByText("No activity yet");
    const reply = screen.getByRole("textbox", { name: "Reply message" });
    await user.type(
      reply,
      "The estate file is ready.",
    );
    await user.click(screen.getByRole("button", { name: "Send reply" }));

    expect(await screen.findByText("The estate file is ready.")).toBeVisible();
    await waitFor(() => expect(reply).toHaveValue(""));
    expect(harness.activity).toHaveBeenCalledTimes(2);
    expect(harness.get).toHaveBeenCalledTimes(1);
  });

  it("refreshes the exact activity stream after a successful transition", async () => {
    harness.activity
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({ results: [INITIAL_ACTIVITY] });
    harness.transition.mockResolvedValue({
      ...TICKET,
      status_code: "in_progress",
      status_name: "In Progress",
      updated_at: "2026-07-27T09:20:00Z",
    });
    const user = userEvent.setup();
    renderDetail();

    await screen.findByText("No activity yet");
    await user.click(screen.getByRole("button", { name: "Start work" }));
    await user.click(
      screen.getByRole("button", { name: "Confirm Start work" }),
    );

    await waitFor(() => expect(harness.activity).toHaveBeenCalledTimes(2));
    expect(harness.get).toHaveBeenCalledTimes(1);
  });

  it("refreshes the exact activity stream after a successful work-state update", async () => {
    harness.activity
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({ results: [INITIAL_ACTIVITY] });
    harness.updateWorkState.mockResolvedValue({
      ...TICKET,
      team: "Litigation",
      updated_at: "2026-07-27T09:21:00Z",
    });
    const user = userEvent.setup();
    renderDetail();

    await screen.findByText("No activity yet");
    const team = screen.getByRole("textbox", { name: "Team" });
    await user.clear(team);
    await user.type(team, "Litigation");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(harness.activity).toHaveBeenCalledTimes(2));
    expect(harness.get).toHaveBeenCalledTimes(1);
  });

  it("hides all mutation controls when server capabilities make the ticket read-only", async () => {
    harness.get.mockResolvedValue({
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_update_work_state: false,
        can_self_assign: false,
        can_reassign: false,
        can_change_confidentiality: false,
        can_add_message: false,
        can_add_note: false,
        can_upload_attachment: false,
      },
    });
    renderDetail();

    await screen.findByRole("heading", { name: TICKET.title });
    expect(
      screen.queryByRole("heading", { name: "Add to activity" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Reply message" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Internal note" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Choose files")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Upload" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Attachments" })).toBeVisible();
  });

  it("encodes relationship ticket numbers so links cannot escape the ticket route", async () => {
    renderDetail();

    expect(
      await screen.findByRole("link", { name: "IT-202607-000042" }),
    ).toHaveAttribute("href", "/tickets/IT-202607-000042");
    expect(
      screen.getByRole("link", { name: "//outside.example/path" }),
    ).toHaveAttribute("href", "/tickets/%2F%2Foutside.example%2Fpath");
  });
});

describe("ticket detail route states", () => {
  it.each([
    {
      returnTo: "/tickets?status=triage&cursor=opaque#current-queue",
      expected: "/tickets?status=triage&cursor=opaque#current-queue",
    },
    {
      returnTo: "/tickets/path?sort=updated#focused-ticket",
      expected: "/tickets/path?sort=updated#focused-ticket",
    },
    {
      returnTo: "/tickets/queue/../path?sort=updated#focused-ticket",
      expected: "/tickets/path?sort=updated#focused-ticket",
    },
    {
      returnTo: "/tickets/100%25-complete?x=1#h",
      expected: "/tickets/100%25-complete?x=1#h",
    },
  ])(
    "normalizes an admitted queue route while preserving search and hash",
    async ({ returnTo, expected }) => {
      renderDetail({ state: { returnTo } });

      expect(
        await screen.findByRole("link", { name: "Back to queue" }),
      ).toHaveAttribute("href", expected);
    },
  );

  it.each([
    "https://outside.example/tickets",
    "//outside.example/tickets",
    "http://[",
    "",
    "/dashboard",
    "/ticketsevil?status=triage",
    "/tickets/../dashboard",
    "/tickets/a/../../admin",
    "/tickets/%2e%2e/dashboard",
    "/tickets/%2E./dashboard",
    "/tickets/.%2e/dashboard",
    "/tickets/%252e%252e/dashboard",
    "/tickets/%2e%2e%2fadmin",
    "/tickets/%2e%2e%5cadmin",
    "/tickets/%00admin",
    "/tickets/%0d%0aadmin",
    "/tickets/%2500admin",
    "/tickets/%257fadmin",
    "/tickets/100%-complete",
    "/tickets/%ZZ",
  ])("rejects unsafe or unrelated return location %s", async (returnTo) => {
    renderDetail({ state: { returnTo } });

    expect(
      await screen.findByRole("link", { name: "Back to queue" }),
    ).toHaveAttribute("href", "/tickets");
  });

  it.each([
    { label: "null", returnTo: null },
    { label: "number", returnTo: 42 },
    { label: "object", returnTo: { pathname: "/tickets" } },
    { label: "array", returnTo: ["/tickets"] },
  ])("rejects a non-string $label return location", async ({ returnTo }) => {
    renderDetail({ state: { returnTo } });

    expect(
      await screen.findByRole("link", { name: "Back to queue" }),
    ).toHaveAttribute("href", "/tickets");
  });

  it("carries the current queue path and search state from a ticket card", async () => {
    const queryClient = new QueryClient();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={["/tickets?status=triage&cursor=opaque"]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Routes>
            <Route path="/tickets" element={<TicketCard ticket={TICKET} />} />
            <Route path="/tickets/:number" element={<LocationProbe />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("link", { name: /estate follow-up/i }));

    expect(screen.getByTestId("location")).toHaveTextContent(
      '"returnTo":"/tickets?status=triage&cursor=opaque"',
    );
  });
});

describe("ticket detail load states", () => {
  it("renders an accessible loading state while the ticket is pending", () => {
    harness.get.mockReturnValue(deferred<TicketDetail>().promise);
    renderDetail();

    expect(screen.getByLabelText("Loading ticket")).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(
      screen.queryByRole("heading", { name: TICKET.title }),
    ).not.toBeInTheDocument();
  });

  it.each([
    { status: 401, title: "Authentication required" },
    { status: 403, title: "Ticket access denied" },
    { status: 404, title: "Ticket not found" },
    { status: 500, title: "Could not load ticket" },
  ])(
    "renders a distinct accessible $status state",
    async ({ status, title }) => {
      harness.get.mockRejectedValue(
        new ApiError(status, {
          code: `ticket_error_${status}`,
          detail: `Safe detail for ${status}.`,
          fields: {},
          correlation_id: `corr-ticket-${status}`,
        }),
      );
      renderDetail();

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(title);
      expect(alert).toHaveTextContent(`Safe detail for ${status}.`);
      expect(alert).toHaveTextContent(`corr-ticket-${status}`);
      expect(
        screen.getByRole("link", { name: "Back to queue" }),
      ).toHaveAttribute("href", "/tickets");
    },
  );
});
