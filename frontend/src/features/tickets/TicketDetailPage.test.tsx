import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  type Location,
} from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  type ActivityItem,
  type AssignmentResponse,
  type TicketAssignee,
  type TicketDetail,
} from "@/lib/api";
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
  assign: vi.fn(),
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
      assign: harness.assign,
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
    self_assignee_detail: null,
    can_assign: false,
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
  category: "workflow",
  occurred_at: "2026-07-27T09:00:00Z",
  actor: { subject: "agent-1", display_name: "Case Agent" },
  visibility: "internal",
  payload: {
    from: "triage",
    to: "assigned",
    reason: "Assigned to Estates",
  },
};

const CREATED_CUSTODY_ACTIVITY: ActivityItem = {
  id: "custody:created",
  type: "custody_event",
  category: "custody",
  occurred_at: "2026-07-27T08:00:00Z",
  actor: { subject: "ticket-intake", display_name: "Ticket intake" },
  visibility: "internal",
  payload: {
    action: "created",
    previous_owner: null,
    new_owner: null,
    previous_queue: null,
    new_queue: null,
    previous_status: null,
    new_status: { code: "new", label: "New" },
    actor_kind: "system",
    source_process: "ticket.intake",
    reason: "Online submission received",
  },
};

const NEW_ASSIGNEE: TicketAssignee = {
  id: "agent-2",
  username: "thandi.mokoena",
  display_name: "Thandi Mokoena",
  designations: ["Accountant"],
  team_labels: ["Finance"],
};

function assignmentResponse(ticket: TicketDetail): AssignmentResponse {
  return {
    ticket,
    receipt: {
      ticket_number: ticket.number,
      action: "reassigned",
      previous_assignee: {
        id: "agent-1",
        display_name: "Case Agent",
        designations: ["Estate Examiner"],
        team_labels: ["Estate Administration"],
      },
      new_assignee: {
        id: NEW_ASSIGNEE.id,
        display_name: NEW_ASSIGNEE.display_name,
        designations: NEW_ASSIGNEE.designations,
        team_labels: NEW_ASSIGNEE.team_labels,
      },
      occurred_at: "2026-07-27T09:22:00Z",
      performed_by: {
        kind: "user",
        subject: "deputy-master-1",
        display_name: "Deputy Master Dlamini",
      },
    },
  };
}

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
  harness.assign.mockReset();
  harness.attachmentList.mockReset().mockResolvedValue({ results: [] });
});

describe("ticket operator workspace", () => {
  it("renders the internal custody category and system provenance on ticket detail", async () => {
    harness.activity.mockResolvedValue({
      results: [CREATED_CUSTODY_ACTIVITY],
    });

    renderDetail();

    expect(
      await screen.findByRole("article", {
        name: "Custody event: Ticket created",
      }),
    ).toBeVisible();
    expect(screen.getByText("Chain of custody")).toBeVisible();
    expect(screen.getByText("System process: ticket.intake")).toBeVisible();
    expect(screen.getByText("Online submission received")).toBeVisible();
  });

  it("renders ticket essentials above the activity and operations workspace", async () => {
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
    expect(
      screen.queryByRole("link", { name: "Jump to ticket context" }),
    ).not.toBeInTheDocument();

    const action = screen.getByRole("button", { name: "Start work" });
    const activity = screen.getByRole("heading", { name: "Activity" });
    const operations = screen.getByRole("heading", { name: "Operations" });
    const essentials = screen.getByRole("region", {
      name: "Ticket essentials",
    });
    expect(action).toBeVisible();
    expect(activity).toBeVisible();
    expect(screen.getByTestId("ticket-header-actions")).toContainElement(
      action,
    );
    expect(
      screen.queryByRole("heading", { name: "Add to activity" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "Reply message" }),
    ).toHaveAttribute("placeholder", "Type your reply…");
    expect(operations).toBeVisible();
    expect(screen.getByRole("heading", { name: "SLA" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Relationships" }),
    ).toBeVisible();
    expect(
      within(essentials).getByRole("heading", { name: "Attachments" }),
    ).toBeVisible();
    expect(
      within(essentials).getByRole("heading", { name: "Requester" }),
    ).toBeVisible();
    expect(
      within(essentials).getByRole("heading", { name: "Classification" }),
    ).toBeVisible();
    expect(
      within(essentials).getByRole("link", { name: "naledi@example.test" }),
    ).toHaveAttribute("href", "mailto:naledi@example.test");
    expect(
      within(essentials).getByRole("link", { name: "+27115550123" }),
    ).toHaveAttribute("href", "tel:+27115550123");
    expect(screen.getByText("EST-42")).toBeVisible();

    expect(
      action.compareDocumentPosition(essentials) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      essentials.compareDocumentPosition(activity) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      activity.compareDocumentPosition(operations) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByTestId("ticket-essentials-grid")).toHaveClass(
      "xl:grid-cols-3",
    );
    expect(essentials).not.toHaveClass("w-screen");
    const workspace = screen.getByTestId("ticket-workspace-layout");
    expect(workspace).toHaveClass(
      "xl:grid-cols-[minmax(0,1.9fr)_minmax(21rem,1fr)]",
    );
    expect(workspace).not.toHaveClass("py-5");
    expect(screen.getByTestId("ticket-detail-page")).toHaveClass(
      "xl:w-[calc(100vw-8rem)]",
    );
    const operationsRail = screen.getByTestId("ticket-operations-rail");
    const activityCard = screen.getByTestId("ticket-activity-card");
    const activityStream = screen.getByTestId("ticket-activity-scroll");

    expect(operationsRail).not.toHaveClass(
      "xl:sticky",
      "xl:h-[calc(100vh-20rem)]",
      "xl:overflow-y-auto",
    );
    expect(activityCard).not.toHaveClass("xl:h-[calc(100vh-20rem)]");
    expect(activityStream).not.toHaveClass("xl:flex-1", "xl:overflow-y-auto");
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

  it("shows the new owner from the exact cache before dependent refetches resolve", async () => {
    const candidateRefetch = deferred<{ results: TicketAssignee[] }>();
    const activityRefetch = deferred<{ results: ActivityItem[] }>();
    const transferable = {
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_assign: true,
        can_reassign: true,
      },
    };
    const updated = {
      ...transferable,
      assignee: NEW_ASSIGNEE.id,
      assignee_detail: {
        id: NEW_ASSIGNEE.id,
        display_name: NEW_ASSIGNEE.display_name,
      },
      updated_at: "2026-07-27T09:22:00Z",
    };
    harness.get.mockResolvedValue(transferable);
    harness.assignees
      .mockResolvedValueOnce({ results: [NEW_ASSIGNEE] })
      .mockReturnValueOnce(candidateRefetch.promise);
    harness.activity
      .mockResolvedValueOnce({ results: [INITIAL_ACTIVITY] })
      .mockReturnValueOnce(activityRefetch.promise);
    harness.assign.mockResolvedValue(assignmentResponse(updated));
    const user = userEvent.setup();
    const { queryClient } = renderDetail();

    await screen.findByRole("heading", { name: transferable.title });
    expect(queryClient.getQueryData(["ticket", transferable.number])).toEqual(
      transferable,
    );
    const replaceExact = vi.spyOn(queryClient, "setQueryData");
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await user.click(
      screen.getByRole("combobox", { name: "Eligible team member" }),
    );
    fireEvent.click(
      await screen.findByRole("option", { name: /Thandi Mokoena/ }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Move to finance review",
    );
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() =>
      expect(screen.getByText("Current owner").parentElement).toHaveTextContent(
        NEW_ASSIGNEE.display_name,
      ),
    );
    expect(queryClient.getQueryData(["ticket", updated.number])).toEqual(
      updated,
    );
    expect(replaceExact).toHaveBeenCalledWith(
      ["ticket", updated.number],
      updated,
    );
    expect(invalidate.mock.calls.map(([filters]) => filters)).toEqual([
      { queryKey: ["tickets"] },
      { queryKey: ["kanban"] },
      { queryKey: ["dashboard"] },
      { queryKey: ["ticket", updated.number, "assignees"] },
      { queryKey: ["ticket-activity", updated.number] },
    ]);
    const replacementOrder = replaceExact.mock.invocationCallOrder[0];
    expect(
      invalidate.mock.invocationCallOrder.every(
        (invalidationOrder) => replacementOrder < invalidationOrder,
      ),
    ).toBe(true);
    expect(harness.get).toHaveBeenCalledTimes(1);
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
    });
    await waitFor(() => expect(harness.activity).toHaveBeenCalledTimes(2));
    expect(harness.get).toHaveBeenCalledTimes(2);
  });

  it("refreshes the exact activity stream after a successful reply", async () => {
    const createdActivity: ActivityItem = {
      id: "activity-2",
      type: "message",
      category: "public_reply",
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
    await user.type(reply, "The estate file is ready.");
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
        <MemoryRouter initialEntries={["/tickets?status=triage&cursor=opaque"]}>
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
