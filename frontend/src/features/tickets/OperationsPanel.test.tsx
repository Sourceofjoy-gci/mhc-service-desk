import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  type AssignmentResponse,
  type TicketAssignee,
  type TicketDetail,
} from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { OperationsPanel } from "./OperationsPanel";

const harness = vi.hoisted(() => ({
  assignees: vi.fn(),
  assign: vi.fn(),
  updateWorkState: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      assignees: harness.assignees,
      assign: harness.assign,
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
  relationships: [],
  attachments: [],
  messages: [],
  notes: [],
};

const SECOND_AGENT: TicketAssignee = {
  id: "agent-2",
  username: "second.agent",
  display_name: "Second Agent",
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
        id: SECOND_AGENT.id,
        display_name: SECOND_AGENT.display_name,
        designations: SECOND_AGENT.designations,
        team_labels: SECOND_AGENT.team_labels,
      },
      occurred_at: "2026-07-27T09:20:00Z",
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

function StatefulPanel({
  initialTicket,
  onUpdated,
}: {
  initialTicket: TicketDetail;
  onUpdated: (ticket: TicketDetail) => void;
}) {
  const [ticket, setTicket] = useState(initialTicket);
  return (
    <OperationsPanel
      ticket={ticket}
      onUpdated={(updated) => {
        setTicket(updated);
        onUpdated(updated);
      }}
      onReload={vi.fn()}
    />
  );
}

function renderStatefulPanel(ticket: TicketDetail, onUpdated = vi.fn()) {
  renderWithProviders(
    <StatefulPanel initialTicket={ticket} onUpdated={onUpdated} />,
  );
  return { onUpdated };
}

beforeEach(() => {
  harness.assignees.mockReset();
  harness.assign.mockReset();
  harness.updateWorkState.mockReset();
  harness.assignees.mockResolvedValue({ results: [] });
});

describe("server-driven ticket operations", () => {
  it("renders assignment above non-ownership operations without a legacy candidate request", () => {
    const legacyReassignCapability = {
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_reassign: true,
      },
    };
    renderPanel(legacyReassignCapability);

    const assignment = screen.getByRole("heading", { name: "Assignment" });
    const operations = screen.getByRole("heading", { name: "Operations" });
    expect(assignment).toBeVisible();
    expect(screen.getByText("Current owner").parentElement).toHaveTextContent(
      "Case Agent",
    );
    expect(
      assignment.compareDocumentPosition(operations) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      screen.getByText("Work state and the next planned action."),
    ).toBeVisible();
    expect(
      screen.queryByRole("combobox", { name: "Assignee" }),
    ).not.toBeInTheDocument();
    expect(harness.assignees).not.toHaveBeenCalled();
  });

  it("delegates ownership changes to the dedicated assignment endpoint", async () => {
    const supervisor = {
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_assign: true,
        can_reassign: true,
      },
    };
    harness.assignees.mockResolvedValue({
      results: [SECOND_AGENT],
    });
    harness.assign.mockResolvedValue(
      assignmentResponse({
        ...supervisor,
        assignee: SECOND_AGENT.id,
        assignee_detail: {
          id: SECOND_AGENT.id,
          display_name: SECOND_AGENT.display_name,
        },
        updated_at: "2026-07-27T09:20:00Z",
      }),
    );
    const user = userEvent.setup();
    renderPanel(supervisor);

    await user.click(
      screen.getByRole("combobox", { name: "Eligible team member" }),
    );
    fireEvent.click(
      await screen.findByRole("option", { name: /Second Agent/ }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Move to finance review",
    );
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() =>
      expect(harness.assign).toHaveBeenCalledWith(TICKET.number, {
        assignee_id: SECOND_AGENT.id,
        expected_updated_at: TICKET.updated_at,
        reason: "Move to finance review",
      }),
    );
    expect(harness.updateWorkState).not.toHaveBeenCalled();
  });

  it("preserves pending work state and validation after an assignment-only refresh", async () => {
    const editableSupervisor = {
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_assign: true,
        can_reassign: true,
        can_change_confidentiality: true,
      },
    };
    const assignmentOnlyRefresh = {
      ...editableSupervisor,
      assignee: SECOND_AGENT.id,
      assignee_detail: {
        id: SECOND_AGENT.id,
        display_name: SECOND_AGENT.display_name,
      },
      updated_at: "2026-07-27T09:20:00Z",
    };
    harness.assignees.mockResolvedValue({ results: [SECOND_AGENT] });
    harness.updateWorkState.mockRejectedValue(
      new ApiError(400, {
        code: "invalid_work_state",
        detail: "Review the highlighted values.",
        fields: { next_action: ["Next action needs more detail."] },
        correlation_id: "corr-pending-work-400",
      }),
    );
    harness.assign.mockResolvedValue(assignmentResponse(assignmentOnlyRefresh));
    const onUpdated = vi.fn();
    const user = userEvent.setup();
    renderStatefulPanel(editableSupervisor, onUpdated);

    const team = screen.getByRole("textbox", { name: "Team" });
    const nextAction = screen.getByRole("textbox", { name: "Next action" });
    const confidentiality = screen.getByRole("combobox", {
      name: "Confidentiality",
    });
    await user.clear(team);
    await user.type(team, "Pending finance review");
    await user.clear(nextAction);
    await user.type(nextAction, "Call the accountant with the signed file");
    await user.selectOptions(confidentiality, "sensitive");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Next action needs more detail."),
    ).toBeVisible();
    await user.click(
      screen.getByRole("combobox", { name: "Eligible team member" }),
    );
    fireEvent.click(
      await screen.findByRole("option", { name: /Second Agent/ }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Move to finance review",
    );
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() =>
      expect(screen.getByText("Current owner").parentElement).toHaveTextContent(
        SECOND_AGENT.display_name,
      ),
    );
    expect(team).toHaveValue("Pending finance review");
    expect(nextAction).toHaveValue("Call the accountant with the signed file");
    expect(confidentiality).toHaveValue("sensitive");
    expect(screen.getByText("Next action needs more detail.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(onUpdated).toHaveBeenCalledWith(assignmentOnlyRefresh);
  });

  it("rebases untouched fields from a same-ticket authoritative refresh", async () => {
    const editableTicket = {
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_change_confidentiality: true,
      },
    };
    const refreshed = {
      ...editableTicket,
      waiting_reason: "internal",
      blocked_reason: "Server-side records check",
      updated_at: "2026-07-27T09:20:00Z",
    };
    const onUpdated = vi.fn();
    const onReload = vi.fn();
    const user = userEvent.setup();
    const result = renderWithProviders(
      <OperationsPanel
        ticket={editableTicket}
        onUpdated={onUpdated}
        onReload={onReload}
      />,
    );

    await user.clear(screen.getByRole("textbox", { name: "Team" }));
    await user.type(
      screen.getByRole("textbox", { name: "Team" }),
      "Pending finance review",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Confidentiality" }),
      "sensitive",
    );

    result.rerender(
      <OperationsPanel
        ticket={refreshed}
        onUpdated={onUpdated}
        onReload={onReload}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Waiting reason" }),
      ).toHaveValue("internal"),
    );
    expect(screen.getByRole("textbox", { name: "Blocked reason" })).toHaveValue(
      "Server-side records check",
    );
    expect(screen.getByRole("textbox", { name: "Team" })).toHaveValue(
      "Pending finance review",
    );
    expect(
      screen.getByRole("combobox", { name: "Confidentiality" }),
    ).toHaveValue("sensitive");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("resets pending values and validation when the ticket identity changes", async () => {
    const editableTicket = {
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_change_confidentiality: true,
      },
    };
    const nextTicket = {
      ...editableTicket,
      id: "ticket-2",
      number: "MHC-2026-000002",
      team: "Records",
      next_action: "Index the new file",
      confidentiality: "restricted",
      updated_at: "2026-07-27T11:00:00Z",
    };
    harness.updateWorkState.mockRejectedValue(
      new ApiError(400, {
        code: "invalid_work_state",
        detail: "Review the highlighted values.",
        fields: { next_action: ["Next action needs more detail."] },
        correlation_id: "corr-old-ticket-400",
      }),
    );
    const onUpdated = vi.fn();
    const onReload = vi.fn();
    const user = userEvent.setup();
    const result = renderWithProviders(
      <OperationsPanel
        ticket={editableTicket}
        onUpdated={onUpdated}
        onReload={onReload}
      />,
    );

    await user.clear(screen.getByRole("textbox", { name: "Team" }));
    await user.type(
      screen.getByRole("textbox", { name: "Team" }),
      "Pending old-ticket edit",
    );
    await user.clear(screen.getByRole("textbox", { name: "Next action" }));
    await user.type(
      screen.getByRole("textbox", { name: "Next action" }),
      "Invalid old-ticket action",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Confidentiality" }),
      "sensitive",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Next action needs more detail."),
    ).toBeVisible();

    result.rerender(
      <OperationsPanel
        ticket={nextTicket}
        onUpdated={onUpdated}
        onReload={onReload}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Team" })).toHaveValue(
        nextTicket.team,
      ),
    );
    expect(screen.getByRole("textbox", { name: "Next action" })).toHaveValue(
      nextTicket.next_action,
    );
    expect(
      screen.getByRole("combobox", { name: "Confidentiality" }),
    ).toHaveValue(nextTicket.confidentiality);
    expect(
      screen.queryByText("Next action needs more detail."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
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
        self_assignee_detail: null,
        can_assign: false,
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
    expect(
      screen.queryByRole("button", { name: "Save" }),
    ).not.toBeInTheDocument();
  });

  it("patches only dirty work-state fields plus the observed timestamp", async () => {
    const editableTicket = {
      ...TICKET,
      capabilities: {
        ...TICKET.capabilities,
        can_change_confidentiality: true,
      },
    };
    const refreshed = {
      ...editableTicket,
      team: "Escalations",
      waiting_reason: "third_party",
      blocked_reason: "Awaiting registrar",
      next_action: "Call registrar (confirmed)",
      next_action_at: "2026-07-30T10:45:00.000Z",
      confidentiality: "sensitive",
      updated_at: "2026-07-27T09:20:00Z",
    };
    harness.updateWorkState.mockResolvedValue(refreshed);
    const user = userEvent.setup();
    const { onUpdated } = renderPanel(editableTicket);

    await user.clear(screen.getByRole("textbox", { name: "Team" }));
    await user.type(
      screen.getByRole("textbox", { name: "Team" }),
      "Escalations",
    );
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
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Confidentiality" }),
      "sensitive",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    const expectedNextActionAt = new Date("2026-07-30T12:45").toISOString();
    await waitFor(() =>
      expect(harness.updateWorkState).toHaveBeenCalledWith(TICKET.number, {
        team: "Escalations",
        waiting_reason: "third_party",
        blocked_reason: "Awaiting registrar",
        next_action: "Call the registrar",
        next_action_at: expectedNextActionAt,
        confidentiality: "sensitive",
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
    await user.type(
      screen.getByRole("textbox", { name: "Team" }),
      "Escalations",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(harness.updateWorkState).toHaveBeenCalledTimes(1),
    );
    expect(screen.getByRole("heading", { name: "Operations" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Team" })).toBeDisabled();
    expect(
      screen.getByRole("combobox", { name: "Waiting reason" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();

    pending.resolve(TICKET);
  });

  it("preserves typed values and shows field and correlation details after a 400", async () => {
    const authoritative = {
      ...TICKET,
      next_action: "Review accepted action",
      updated_at: "2026-07-27T09:21:00Z",
    };
    harness.updateWorkState
      .mockRejectedValueOnce(
        new ApiError(400, {
          code: "invalid_work_state",
          detail: "Review the highlighted values.",
          fields: { next_action: ["Next action is too long."] },
          correlation_id: "corr-work-400",
        }),
      )
      .mockResolvedValueOnce(authoritative);
    const user = userEvent.setup();
    const { onUpdated } = renderPanel();

    const nextAction = screen.getByRole("textbox", { name: "Next action" });
    await user.clear(nextAction);
    await user.type(nextAction, "A deliberately invalid action");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Next action is too long.")).toBeVisible();
    expect(screen.getByText(/corr-work-400/)).toBeVisible();
    expect(nextAction).toHaveValue("A deliberately invalid action");

    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(harness.updateWorkState).toHaveBeenCalledTimes(2),
    );
    expect(nextAction).toHaveValue(authoritative.next_action);
    expect(
      screen.queryByText("Next action is too long."),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(onUpdated).toHaveBeenCalledWith(authoritative);
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
    await user.type(
      screen.getByRole("textbox", { name: "Team" }),
      "Escalations",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("This ticket changed since you opened it"),
    ).toBeVisible();
    expect(onReload).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(onReload).toHaveBeenCalledTimes(1);
  });
});
