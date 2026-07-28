import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type TicketDetail } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { OperationsPanel } from "./OperationsPanel";

const harness = vi.hoisted(() => ({
  assignees: vi.fn(),
  updateWorkState: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      assignees: harness.assignees,
      updateWorkState: harness.updateWorkState,
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
  waiting_reason: "requester",
  created_at: "2026-07-27T08:00:00Z",
  updated_at: "2026-07-27T09:15:00Z",
  age_hours: 1.25,
  sla_health: "on_track",
  available_transition_codes: [],
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
  blocked_reason: "Awaiting signed form",
  next_action: "Review file",
  next_action_at: "2026-07-28T08:00:00Z",
  available_transitions: [],
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
  relationships: [],
  attachments: [],
  messages: [],
  notes: [],
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

function renderPanel(
  ticket: TicketDetail = TICKET,
  onUpdated = vi.fn(),
  onReload = vi.fn(),
) {
  renderWithProviders(
    <OperationsPanel
      ticket={ticket}
      onUpdated={onUpdated}
      onReload={onReload}
    />,
  );
  return { onUpdated, onReload };
}

beforeEach(() => {
  harness.assignees.mockReset();
  harness.updateWorkState.mockReset();
  harness.assignees.mockResolvedValue({ results: [] });
});

describe("server-driven ticket operations", () => {
  it("self-assigns an unassigned agent with the server-provided assignee id", async () => {
    const unassigned = {
      ...TICKET,
      assignee: null,
      assignee_detail: null,
      capabilities: {
        ...TICKET.capabilities,
        can_self_assign: true,
        self_assignee_id: "user-record-42",
      },
    };
    harness.updateWorkState.mockResolvedValue({
      ...unassigned,
      assignee: "user-record-42",
    });
    const user = userEvent.setup();
    renderPanel(unassigned);

    expect(screen.getByRole("button", { name: "Self-assign" })).toBeVisible();
    expect(
      screen.queryByRole("combobox", { name: "Assignee" }),
    ).not.toBeInTheDocument();
    expect(harness.assignees).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Self-assign" }));

    await waitFor(() =>
      expect(harness.updateWorkState).toHaveBeenCalledWith(TICKET.number, {
        assignee: "user-record-42",
        updated_at: TICKET.updated_at,
      }),
    );
  });

  it("loads reassignment choices and confidentiality controls only from capabilities", async () => {
    const supervisor = {
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_reassign: true,
        can_change_confidentiality: true,
      },
    };
    harness.assignees.mockResolvedValue({
      results: [
        { id: "agent-1", username: "case.agent", display_name: "Case Agent" },
        { id: "agent-2", username: "second.agent", display_name: "Second Agent" },
      ],
    });
    renderPanel(supervisor);

    expect(
      await screen.findByRole("option", { name: "Second Agent" }),
    ).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Assignee" })).toBeEnabled();
    expect(
      screen.getByRole("combobox", { name: "Confidentiality" }),
    ).toBeEnabled();
    expect(harness.assignees).toHaveBeenCalledWith(TICKET.number);
  });

  it("fails reassignment safely while preserving other work after an assignee lookup error", async () => {
    const supervisor = {
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_reassign: true,
        can_change_confidentiality: true,
      },
    };
    harness.assignees.mockRejectedValue(
      new ApiError(503, {
        code: "assignees_unavailable",
        detail: "Eligible assignees are temporarily unavailable.",
        fields: {},
        correlation_id: "corr-assignees-503",
      }),
    );
    harness.updateWorkState.mockResolvedValue({
      ...supervisor,
      team: "Escalations",
    });
    const user = userEvent.setup();
    renderPanel(supervisor);

    expect(
      await screen.findByText(/Eligible assignees are temporarily unavailable\./),
    ).toBeVisible();
    expect(screen.getByText(/corr-assignees-503/)).toBeVisible();

    const assignee = screen.getByRole("combobox", { name: "Assignee" });
    expect(assignee).toBeDisabled();
    expect(assignee).toHaveValue("agent-1");
    expect(
      screen.getByRole("option", { name: "Case Agent" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Team" })).toBeEnabled();
    expect(
      screen.getByRole("combobox", { name: "Confidentiality" }),
    ).toBeEnabled();

    await user.clear(screen.getByRole("textbox", { name: "Team" }));
    await user.type(screen.getByRole("textbox", { name: "Team" }), "Escalations");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(harness.updateWorkState).toHaveBeenCalledWith(TICKET.number, {
        team: "Escalations",
        updated_at: TICKET.updated_at,
      }),
    );
  });

  it("does not infer elevated controls when capability flags deny them", () => {
    renderPanel(TICKET);

    expect(
      screen.queryByRole("combobox", { name: "Assignee" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Confidentiality" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Normal")).toBeVisible();
  });

  it("renders the complete work state as read-only for an auditor", () => {
    const auditor = {
      ...TICKET,
      capabilities: {
        can_update_work_state: false,
        can_self_assign: false,
        self_assignee_id: null,
        can_reassign: false,
        can_change_confidentiality: false,
        can_add_message: false,
        can_add_note: false,
        can_upload_attachment: false,
      },
    };
    renderPanel(auditor);

    expect(screen.getByText("Estates")).toBeVisible();
    expect(screen.getByText("Requester")).toBeVisible();
    expect(screen.getByText("Awaiting signed form")).toBeVisible();
    expect(screen.getByText("Review file")).toBeVisible();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });

  it("patches only dirty work-state fields plus the observed timestamp", async () => {
    const refreshed = {
      ...TICKET,
      team: "Escalations",
      waiting_reason: "third_party",
      blocked_reason: "Awaiting registrar",
      next_action: "Call registrar (confirmed)",
      next_action_at: "2026-07-30T10:45:00.000Z",
      updated_at: "2026-07-27T09:20:00Z",
    };
    harness.updateWorkState.mockResolvedValue(refreshed);
    const user = userEvent.setup();
    const { onUpdated } = renderPanel();

    await user.clear(screen.getByRole("textbox", { name: "Team" }));
    await user.type(screen.getByRole("textbox", { name: "Team" }), "Escalations");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Waiting reason" }),
      "third_party",
    );
    await user.clear(screen.getByRole("textbox", { name: "Blocked reason" }));
    await user.type(
      screen.getByRole("textbox", { name: "Blocked reason" }),
      "Awaiting registrar",
    );
    await user.clear(screen.getByRole("textbox", { name: "Next action" }));
    await user.type(
      screen.getByRole("textbox", { name: "Next action" }),
      "Call the registrar",
    );
    fireEvent.change(screen.getByLabelText("Next action time"), {
      target: { value: "2026-07-30T12:45" },
    });
    await user.click(screen.getByRole("button", { name: "Save" }));

    const expectedNextActionAt = new Date("2026-07-30T12:45").toISOString();
    await waitFor(() =>
      expect(harness.updateWorkState).toHaveBeenCalledWith(TICKET.number, {
        team: "Escalations",
        waiting_reason: "third_party",
        blocked_reason: "Awaiting registrar",
        next_action: "Call the registrar",
        next_action_at: expectedNextActionAt,
        updated_at: TICKET.updated_at,
      }),
    );
    expect(onUpdated).toHaveBeenCalledWith(refreshed);
    expect(screen.getByRole("textbox", { name: "Next action" })).toHaveValue(
      "Call registrar (confirmed)",
    );
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("keeps the form visible and disables every control while saving", async () => {
    const pending = deferred<TicketDetail>();
    harness.updateWorkState.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    renderPanel();

    await user.clear(screen.getByRole("textbox", { name: "Team" }));
    await user.type(screen.getByRole("textbox", { name: "Team" }), "Escalations");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(harness.updateWorkState).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("heading", { name: "Operations" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Team" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Waiting reason" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();

    pending.resolve(TICKET);
  });

  it("preserves typed values and shows field and correlation details after a 400", async () => {
    harness.updateWorkState.mockRejectedValue(
      new ApiError(400, {
        code: "invalid_work_state",
        detail: "Review the highlighted values.",
        fields: { next_action: ["Next action is too long."] },
        correlation_id: "corr-work-400",
      }),
    );
    const user = userEvent.setup();
    renderPanel();

    const nextAction = screen.getByRole("textbox", { name: "Next action" });
    await user.clear(nextAction);
    await user.type(nextAction, "A deliberately invalid action");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Next action is too long.")).toBeVisible();
    expect(screen.getByText(/corr-work-400/)).toBeVisible();
    expect(nextAction).toHaveValue("A deliberately invalid action");
  });

  it("reloads a stale ticket only after the operator chooses Reload", async () => {
    harness.updateWorkState.mockRejectedValue(
      new ApiError(409, {
        code: "stale_ticket",
        detail: "The ticket changed.",
        fields: { updated_at: ["Use the current version."] },
        correlation_id: "corr-stale-work",
      }),
    );
    const user = userEvent.setup();
    const { onReload } = renderPanel();

    await user.clear(screen.getByRole("textbox", { name: "Team" }));
    await user.type(screen.getByRole("textbox", { name: "Team" }), "Escalations");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("This ticket changed since you opened it"),
    ).toBeVisible();
    expect(onReload).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(onReload).toHaveBeenCalledTimes(1);
  });
});
