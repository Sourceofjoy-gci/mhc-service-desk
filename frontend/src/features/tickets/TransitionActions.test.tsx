import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type TicketAssignee, type TicketDetail } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { TransitionActions } from "./TransitionActions";

const harness = vi.hoisted(() => ({
  transition: vi.fn(),
  get: vi.fn(),
  escalationSupervisors: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      transition: harness.transition,
      get: harness.get,
      escalationSupervisors: harness.escalationSupervisors,
    },
  };
});

const TICKET: TicketDetail = {
  id: "ticket-1",
  number: "MHC-2026-000001",
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
  waiting_reason: "",
  created_at: "2026-07-27T08:00:00Z",
  updated_at: "2026-07-27T09:15:00Z",
  age_hours: 1.25,
  sla_health: "on_track",
  available_transition_codes: ["in_progress", "waiting_requester", "resolved"],
  description: "Please confirm the estate status.",
  requester: {
    id: "requester-1",
    full_name: "Naledi Dube",
    email: "naledi@example.test",
    phone_e164: null,
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
  next_action_at: null,
  available_transitions: [
    {
      to_status: "in_progress",
      label: "Start work",
      requires_resolution: false,
      requires_reason: false,
    },
    {
      to_status: "waiting_requester",
      label: "Wait on requester",
      requires_resolution: false,
      requires_reason: true,
    },
    {
      to_status: "resolved",
      label: "Resolve",
      requires_resolution: true,
      requires_reason: false,
    },
  ],
  capabilities: {
    can_update_work_state: true,
    can_self_assign: false,
    self_assignee_id: null,
    self_assignee_detail: null,
    can_assign: true,
    can_reassign: true,
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
  relationships: [],
  attachments: [],
  messages: [],
  notes: [],
};

const ASSISTANT_MASTER: TicketAssignee = {
  id: "00000000-0000-0000-0000-000000000099",
  username: "assistant.dlamini",
  display_name: "Lindiwe Dlamini",
  designations: ["Assistant Master"],
  team_labels: ["Office Leadership"],
  role_summaries: ["Approves workflow progress."],
};

const DEPUTY_MASTER: TicketAssignee = {
  id: "00000000-0000-0000-0000-000000000100",
  username: "deputy.mabuza",
  display_name: "Musa Mabuza",
  designations: ["Deputy Master"],
  team_labels: ["Executive Review"],
  role_summaries: ["Provides senior approval and oversight."],
};

const ESCALATABLE_TICKET: TicketDetail = {
  ...TICKET,
  available_transition_codes: [
    ...TICKET.available_transition_codes,
    "escalated",
  ],
  available_transitions: [
    ...TICKET.available_transitions,
    {
      to_status: "escalated",
      label: "Escalate",
      requires_resolution: false,
      requires_reason: true,
    },
  ],
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

function renderActions(
  ticket: TicketDetail = TICKET,
  onUpdated = vi.fn(),
  onActivityChanged = vi.fn(),
) {
  const rendered = renderWithProviders(
    <TransitionActions
      ticket={ticket}
      onUpdated={onUpdated}
      onActivityChanged={onActivityChanged}
    />,
  );
  return { onUpdated, onActivityChanged, ...rendered };
}

async function openResolve(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Resolve" }));
  return {
    code: screen.getByRole("textbox", { name: "Resolution code" }),
    summary: screen.getByRole("textbox", { name: "Resolution summary" }),
  };
}

async function selectSupervisor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByRole("combobox", { name: "Escalate to supervisor" }),
  );
  await screen.findByRole("option", { name: /Lindiwe Dlamini/ });
  await user.keyboard("{ArrowDown}");
  await user.keyboard("{Enter}");
}

beforeEach(() => {
  harness.transition.mockReset();
  harness.get.mockReset();
  harness.escalationSupervisors.mockReset();
  harness.escalationSupervisors.mockResolvedValue({ results: [] });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("server-driven transition actions", () => {
  it("shows escalation supervision only for the escalation action", async () => {
    const user = userEvent.setup();
    renderActions(ESCALATABLE_TICKET);

    expect(harness.escalationSupervisors).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Start work" }));
    expect(
      screen.queryByRole("combobox", { name: "Escalate to supervisor" }),
    ).not.toBeInTheDocument();
    expect(harness.escalationSupervisors).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Escalate" }));

    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toBeVisible();
    await waitFor(() =>
      expect(harness.escalationSupervisors).toHaveBeenCalledWith(
        TICKET.number,
        "",
      ),
    );
  });

  it("debounces typed supervisor search but resets it immediately on cancel", async () => {
    harness.escalationSupervisors.mockResolvedValue({
      results: [ASSISTANT_MASTER],
    });
    const user = userEvent.setup();
    renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await waitFor(() =>
      expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
        TICKET.number,
        "",
      ),
    );
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    await user.type(
      await screen.findByRole("combobox", {
        name: "Search Escalate to supervisor",
      }),
      "deputy & master",
    );
    await waitFor(
      () =>
        expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
          TICKET.number,
          "deputy & master",
        ),
      { timeout: 1_000 },
    );

    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Escalate" }));

    expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
      TICKET.number,
      "",
    );
  });

  it("waits 250 ms and collapses typed supervisor search into one lookup", async () => {
    harness.escalationSupervisors.mockResolvedValue({
      results: [ASSISTANT_MASTER],
    });
    const user = userEvent.setup();
    renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    const search = await screen.findByRole("combobox", {
      name: "Search Escalate to supervisor",
    });
    harness.escalationSupervisors.mockClear();

    vi.useFakeTimers();
    try {
      for (const value of ["d", "de", "dep", "depu", "deput", "deputy"]) {
        fireEvent.change(search, { target: { value } });
      }

      await act(async () => {
        await vi.advanceTimersByTimeAsync(249);
      });
      expect(harness.escalationSupervisors).not.toHaveBeenCalled();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      expect(harness.escalationSupervisors).toHaveBeenCalledTimes(1);
      expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
        TICKET.number,
        "deputy",
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("requires and submits a named escalation supervisor", async () => {
    harness.escalationSupervisors.mockResolvedValue({
      results: [ASSISTANT_MASTER],
    });
    harness.transition.mockResolvedValue({
      ...ESCALATABLE_TICKET,
      status_code: "escalated",
      status_name: "Escalated",
      assignee: ASSISTANT_MASTER.id,
      assignee_detail: {
        id: ASSISTANT_MASTER.id,
        display_name: ASSISTANT_MASTER.display_name,
      },
    });
    const user = userEvent.setup();
    const { onUpdated, onActivityChanged } = renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    const reason = screen.getByRole("textbox", { name: "Reason" });
    await user.type(reason, "SLA risk");
    await user.click(screen.getByRole("button", { name: "Confirm Escalate" }));
    expect(
      await screen.findByText("Select an escalation supervisor."),
    ).toBeVisible();
    expect(reason).toHaveValue("SLA risk");

    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    const option = await screen.findByRole("option", {
      name: /Lindiwe Dlamini/,
    });
    expect(option).toHaveTextContent("Assistant Master");
    expect(within(option).getByText(/Office Leadership/)).toBeVisible();
    expect(within(option).getByText("Approves workflow progress.")).toBeVisible();
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Escalate to supervisor" }),
      ).toHaveTextContent(ASSISTANT_MASTER.display_name),
    );
    await user.click(screen.getByRole("button", { name: "Confirm Escalate" }));

    await waitFor(() =>
      expect(harness.transition).toHaveBeenCalledWith(TICKET.number, {
        to_status: "escalated",
        updated_at: TICKET.updated_at,
        reason: "SLA risk",
        supervisor_id: ASSISTANT_MASTER.id,
      }),
    );
    await waitFor(() => expect(onUpdated).toHaveBeenCalledTimes(1));
    expect(onActivityChanged).toHaveBeenCalledTimes(1);
  });

  it("clears reason, supervisor, and search after a successful escalation refresh", async () => {
    harness.escalationSupervisors.mockResolvedValue({
      results: [ASSISTANT_MASTER],
    });
    const refreshed = {
      ...ESCALATABLE_TICKET,
      updated_at: "2026-07-27T09:16:00Z",
      status_code: "escalated",
      status_name: "Escalated",
    };
    harness.transition.mockResolvedValue(refreshed);
    const user = userEvent.setup();
    const { onUpdated, rerender } = renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await user.type(screen.getByRole("textbox", { name: "Reason" }), "SLA risk");
    await selectSupervisor(user);
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    await user.type(
      await screen.findByRole("combobox", {
        name: "Search Escalate to supervisor",
      }),
      "lindiwe",
    );
    await waitFor(() =>
      expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
        TICKET.number,
        "lindiwe",
      ),
    );
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm Escalate" }));
    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(refreshed));

    rerender(
      <TransitionActions
        ticket={refreshed}
        onUpdated={onUpdated}
        onActivityChanged={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await waitFor(() =>
      expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
        refreshed.number,
        "",
      ),
    );
    expect(screen.getByRole("textbox", { name: "Reason" })).toHaveValue("");
    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toHaveTextContent("Select eligible team member");
  });

  it("shows supervisor lookup loading and failure state without querying other actions", async () => {
    const lookup = deferred<{ results: TicketAssignee[] }>();
    harness.escalationSupervisors.mockReturnValue(lookup.promise);
    const user = userEvent.setup();
    renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toHaveAttribute("aria-busy", "true");
    lookup.reject(
      new ApiError(503, {
        code: "service_unavailable",
        detail: "Supervisor directory is unavailable.",
        fields: {},
        correlation_id: "corr-directory-1",
      }),
    );

    expect(
      await screen.findByText("Supervisor directory is unavailable."),
    ).toBeVisible();
  });

  it("clears the selected supervisor when the escalation dialog is cancelled", async () => {
    harness.escalationSupervisors.mockResolvedValue({
      results: [ASSISTANT_MASTER],
    });
    const user = userEvent.setup();
    renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await selectSupervisor(user);
    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toHaveTextContent(ASSISTANT_MASTER.display_name);

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Escalate" }));
    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toHaveTextContent("Select eligible team member");
  });

  it("clears the selected supervisor when a different action is selected", async () => {
    harness.escalationSupervisors.mockImplementation((_number, search) =>
      Promise.resolve({
        results: search ? [DEPUTY_MASTER] : [ASSISTANT_MASTER],
      }),
    );
    const user = userEvent.setup();
    renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await selectSupervisor(user);
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    await user.type(
      await screen.findByRole("combobox", {
        name: "Search Escalate to supervisor",
      }),
      "executive",
    );
    await waitFor(() =>
      expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
        TICKET.number,
        "executive",
      ),
    );
    expect(
      await screen.findByRole("option", { name: /Musa Mabuza/ }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Start work", hidden: true }),
    );
    expect(
      screen.queryByRole("combobox", { name: "Escalate to supervisor" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Escalate", hidden: true }),
    );
    await waitFor(() =>
      expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
        TICKET.number,
        "",
      ),
    );
    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toHaveTextContent("Select eligible team member");
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    expect(await screen.findByRole("option", { name: /Lindiwe Dlamini/ })).toBeVisible();
    expect(
      screen.queryByRole("option", { name: /Musa Mabuza/ }),
    ).not.toBeInTheDocument();
  });

  it("preserves values through a stale escalation then clears them after Reload", async () => {
    harness.escalationSupervisors.mockResolvedValue({
      results: [ASSISTANT_MASTER],
    });
    harness.transition.mockRejectedValue(
      new ApiError(409, {
        code: "stale_ticket",
        detail: "The ticket changed.",
        fields: { updated_at: ["2026-07-27T09:17:00Z"] },
        correlation_id: "corr-escalation-stale",
      }),
    );
    harness.get.mockResolvedValue({
      ...ESCALATABLE_TICKET,
      updated_at: "2026-07-27T09:17:00Z",
    });
    const user = userEvent.setup();
    const { onUpdated, onActivityChanged } = renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await user.type(screen.getByRole("textbox", { name: "Reason" }), "SLA risk");
    await selectSupervisor(user);
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    await user.type(
      await screen.findByRole("combobox", {
        name: "Search Escalate to supervisor",
      }),
      "assistant",
    );
    await waitFor(() =>
      expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
        TICKET.number,
        "assistant",
      ),
    );
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm Escalate" }));

    expect(
      await screen.findByText("This ticket changed since you opened it"),
    ).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Reason" })).toHaveValue("SLA risk");
    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toHaveTextContent(ASSISTANT_MASTER.display_name);

    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(harness.get).toHaveBeenCalledWith(TICKET.number));
    expect(onUpdated).toHaveBeenCalledTimes(1);
    expect(onActivityChanged).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await waitFor(() =>
      expect(harness.escalationSupervisors).toHaveBeenLastCalledWith(
        TICKET.number,
        "",
      ),
    );
    expect(screen.getByRole("textbox", { name: "Reason" })).toHaveValue("");
    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toHaveTextContent("Select eligible team member");
  });

  it("disables supervisor selection while escalation submission is pending", async () => {
    harness.escalationSupervisors.mockResolvedValue({
      results: [ASSISTANT_MASTER],
    });
    const pending = deferred<TicketDetail>();
    harness.transition.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await user.type(
      screen.getByRole("textbox", { name: "Reason" }),
      "SLA risk",
    );
    await selectSupervisor(user);
    await user.click(screen.getByRole("button", { name: "Confirm Escalate" }));

    await waitFor(() => expect(harness.transition).toHaveBeenCalledTimes(1));
    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    pending.resolve(ESCALATABLE_TICKET);
  });

  it("preserves an escalation selection for server field and stale errors", async () => {
    harness.escalationSupervisors.mockResolvedValue({
      results: [ASSISTANT_MASTER],
    });
    harness.transition.mockRejectedValue(
      new ApiError(400, {
        code: "invalid_transition",
        detail: "Supervisor no longer has this authority.",
        fields: {
          supervisor_id: ["Select an eligible escalation supervisor."],
        },
        correlation_id: "corr-supervisor-1",
      }),
    );
    const user = userEvent.setup();
    renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await user.type(
      screen.getByRole("textbox", { name: "Reason" }),
      "SLA risk",
    );
    await selectSupervisor(user);
    await user.click(screen.getByRole("button", { name: "Confirm Escalate" }));

    expect(
      await screen.findByText("Select an eligible escalation supervisor."),
    ).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Reason" })).toHaveValue(
      "SLA risk",
    );
    expect(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    ).toHaveTextContent(ASSISTANT_MASTER.display_name);
  });

  it("prioritizes a server supervisor error over a failed candidate refresh", async () => {
    harness.escalationSupervisors.mockImplementation((_number, search) =>
      search
        ? Promise.reject(
            new ApiError(503, {
              code: "service_unavailable",
              detail: "Supervisor directory is unavailable.",
              fields: {},
              correlation_id: "corr-directory-2",
            }),
          )
        : Promise.resolve({ results: [ASSISTANT_MASTER] }),
    );
    harness.transition.mockRejectedValue(
      new ApiError(400, {
        code: "invalid_transition",
        detail: "Supervisor is no longer eligible.",
        fields: { supervisor_id: ["Choose another eligible supervisor."] },
        correlation_id: "corr-supervisor-2",
      }),
    );
    const user = userEvent.setup();
    renderActions(ESCALATABLE_TICKET);

    await user.click(screen.getByRole("button", { name: "Escalate" }));
    await user.type(screen.getByRole("textbox", { name: "Reason" }), "SLA risk");
    await selectSupervisor(user);
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    await user.type(
      await screen.findByRole("combobox", {
        name: "Search Escalate to supervisor",
      }),
      "different",
    );
    await screen.findByText("Supervisor directory is unavailable.");
    await user.click(
      screen.getByRole("combobox", { name: "Escalate to supervisor" }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm Escalate" }));

    expect(
      await screen.findByText("Choose another eligible supervisor."),
    ).toBeVisible();
    expect(
      screen.queryByText("Supervisor directory is unavailable."),
    ).not.toBeInTheDocument();
  });
  it("renders only the transition labels supplied by the ticket", () => {
    renderActions();

    expect(screen.getByRole("button", { name: "Start work" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Wait on requester" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Resolve" })).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Close ticket" }),
    ).not.toBeInTheDocument();
  });

  it("renders conditional required fields and submits the observed timestamp", async () => {
    const refreshed = {
      ...TICKET,
      status_code: "resolved",
      status_name: "Resolved",
    };
    harness.transition.mockResolvedValue(refreshed);
    const user = userEvent.setup();
    renderActions();

    const fields = await openResolve(user);
    expect(fields.code).toBeRequired();
    expect(fields.summary).toBeRequired();
    expect(
      screen.queryByRole("textbox", { name: "Reason" }),
    ).not.toBeInTheDocument();

    await user.type(fields.code, "completed");
    await user.type(fields.summary, "Verified and completed");
    await user.click(screen.getByRole("button", { name: "Confirm Resolve" }));

    await waitFor(() =>
      expect(harness.transition).toHaveBeenCalledWith(TICKET.number, {
        to_status: "resolved",
        updated_at: TICKET.updated_at,
        resolution_code: "completed",
        resolution_summary: "Verified and completed",
      }),
    );

    await user.click(screen.getByRole("button", { name: "Wait on requester" }));
    expect(screen.getByRole("textbox", { name: "Reason" })).toBeRequired();
    expect(
      screen.queryByRole("textbox", { name: "Resolution code" }),
    ).not.toBeInTheDocument();
  });

  it("keeps every action and form control disabled while submission is pending", async () => {
    const pending = deferred<TicketDetail>();
    harness.transition.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    renderActions();

    const fields = await openResolve(user);
    await user.type(fields.code, "completed");
    await user.type(fields.summary, "Verified");
    const submitButton = screen.getByRole("button", {
      name: "Confirm Resolve",
    });
    const form = submitButton.closest("form");
    expect(form).not.toBeNull();
    act(() => {
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
      form?.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    await waitFor(() => expect(harness.transition).toHaveBeenCalledTimes(1));
    expect(fields.code).toBeDisabled();
    expect(fields.summary).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Confirm Resolve" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByText("Start work").closest("button")).toBeDisabled();

    pending.resolve(TICKET);
  });

  it("keeps typed values and renders authoritative server field errors", async () => {
    harness.transition.mockRejectedValue(
      new ApiError(400, {
        code: "invalid_transition",
        detail: "The resolution needs attention.",
        fields: {
          resolution_code: ["Choose a valid resolution code."],
          resolution_summary: ["Add more detail."],
        },
        correlation_id: "corr-field-1",
      }),
    );
    const user = userEvent.setup();
    renderActions();

    const fields = await openResolve(user);
    await user.type(fields.code, "my-code");
    await user.type(fields.summary, "My typed summary");
    await user.click(screen.getByRole("button", { name: "Confirm Resolve" }));

    expect(
      await screen.findByText("Choose a valid resolution code."),
    ).toBeVisible();
    expect(screen.getByText("Add more detail.")).toBeVisible();
    expect(fields.code).toHaveValue("my-code");
    expect(fields.summary).toHaveValue("My typed summary");
  });

  it("passes the refreshed ticket to onUpdated and closes after success", async () => {
    const refreshed = {
      ...TICKET,
      status_code: "in_progress",
      status_name: "In Progress",
      updated_at: "2026-07-27T09:16:00Z",
    };
    harness.transition.mockResolvedValue(refreshed);
    const user = userEvent.setup();
    const { onUpdated } = renderActions();

    await user.click(screen.getByRole("button", { name: "Start work" }));
    await user.click(
      screen.getByRole("button", { name: "Confirm Start work" }),
    );

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(refreshed));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers an explicit reload after a stale-ticket conflict", async () => {
    const refreshed = {
      ...TICKET,
      updated_at: "2026-07-27T09:17:00Z",
    };
    harness.transition.mockRejectedValue(
      new ApiError(409, {
        code: "stale_ticket",
        detail: "The ticket changed.",
        fields: { updated_at: [refreshed.updated_at] },
        correlation_id: "corr-stale-1",
      }),
    );
    harness.get.mockResolvedValue(refreshed);
    const user = userEvent.setup();
    const { onUpdated, onActivityChanged } = renderActions();

    await user.click(screen.getByRole("button", { name: "Start work" }));
    await user.click(
      screen.getByRole("button", { name: "Confirm Start work" }),
    );

    expect(
      await screen.findByText("This ticket changed since you opened it"),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Reload" }));

    await waitFor(() =>
      expect(harness.get).toHaveBeenCalledWith(TICKET.number),
    );
    expect(onUpdated).toHaveBeenCalledWith(refreshed);
    expect(onActivityChanged).toHaveBeenCalledTimes(1);
  });

  it("shows the correlation ID for an unexpected server error", async () => {
    harness.transition.mockRejectedValue(
      new ApiError(500, {
        code: "server_error",
        detail: "Something went wrong.",
        fields: {},
        correlation_id: "corr-unexpected-42",
      }),
    );
    const user = userEvent.setup();
    renderActions();

    await user.click(screen.getByRole("button", { name: "Start work" }));
    await user.click(
      screen.getByRole("button", { name: "Confirm Start work" }),
    );

    expect(await screen.findByText(/Something went wrong\./)).toBeVisible();
    expect(screen.getByText(/corr-unexpected-42/)).toBeVisible();
  });
});
