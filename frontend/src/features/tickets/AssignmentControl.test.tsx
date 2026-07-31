import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type AssignmentReceipt,
  type AssignmentResponse,
  type TicketAssignee,
  type TicketDetail,
} from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { AssignmentControl } from "./AssignmentControl";

const harness = vi.hoisted(() => ({
  assignees: vi.fn(),
  assign: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      assignees: harness.assignees,
      assign: harness.assign,
    },
  };
});

vi.mock("sonner", () => ({
  toast: {
    success: harness.toastSuccess,
  },
}));

const CURRENT_ASSIGNEE: TicketAssignee = {
  id: "00000000-0000-0000-0000-000000000011",
  username: "case.agent",
  display_name: "Case Agent",
  designations: ["Estate Examiner"],
  team_labels: ["Estate Administration"],
};

const ACCOUNTANT: TicketAssignee = {
  id: "00000000-0000-0000-0000-000000000012",
  username: "thandi.mokoena",
  display_name: "Thandi Mokoena",
  designations: ["Accountant"],
  team_labels: ["Finance"],
};

const RECORDS_CLERK: TicketAssignee = {
  id: "00000000-0000-0000-0000-000000000013",
  username: "siphiwe.ndlovu",
  display_name: "Siphiwe Ndlovu",
  designations: ["Records Clerk"],
  team_labels: ["Records"],
};

const BASE_TICKET: TicketDetail = {
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
  assignee: CURRENT_ASSIGNEE.id,
  waiting_reason: "",
  created_at: "2026-07-30T08:00:00Z",
  updated_at: "2026-07-30T10:00:00Z",
  age_hours: 2,
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
  acknowledged_at: null,
  first_responded_at: null,
  resolved_at: null,
  closed_at: null,
  reopened_at: null,
  assignee_detail: {
    id: CURRENT_ASSIGNEE.id,
    display_name: CURRENT_ASSIGNEE.display_name,
  },
  team: "Estate Administration",
  blocked_reason: "",
  next_action: "",
  next_action_at: null,
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
      due_at: "2026-07-30T12:00:00Z",
      remaining_seconds: 7200,
      overdue_seconds: 0,
    },
    resolution: {
      state: "running",
      due_at: "2026-07-31T10:00:00Z",
      remaining_seconds: 86400,
      overdue_seconds: 0,
    },
  },
  relationships: [],
  attachments: [],
  messages: [],
  notes: [],
};

const RECEIPT: AssignmentReceipt = {
  ticket_number: BASE_TICKET.number,
  action: "reassigned",
  previous_assignee: {
    id: CURRENT_ASSIGNEE.id,
    display_name: "Previous owner from receipt",
    designations: ["Estate Examiner"],
    team_labels: ["Estate Administration"],
  },
  new_assignee: {
    id: ACCOUNTANT.id,
    display_name: "New owner from receipt",
    designations: ["Accountant"],
    team_labels: ["Finance"],
  },
  occurred_at: "2026-07-30T10:30:00Z",
  performed_by: {
    kind: "user",
    subject: "operator-1",
    display_name: "Deputy Master Dlamini",
  },
};

function ticketWithCapabilities(
  capabilities: Partial<TicketDetail["capabilities"]>,
  ticket: TicketDetail = BASE_TICKET,
): TicketDetail {
  return {
    ...ticket,
    capabilities: { ...ticket.capabilities, ...capabilities },
  };
}

function unassignedTicket(
  capabilities: Partial<TicketDetail["capabilities"]> = {},
): TicketDetail {
  return ticketWithCapabilities(capabilities, {
    ...BASE_TICKET,
    assignee: null,
    assignee_detail: null,
    status_code: "new",
    status_name: "New",
  });
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

function responseWith(
  ticket: TicketDetail,
  receipt: AssignmentReceipt = RECEIPT,
): AssignmentResponse {
  return { ticket, receipt };
}

function renderControl(
  ticket: TicketDetail = BASE_TICKET,
  options: {
    onUpdated?: (ticket: TicketDetail) => void;
    onReload?: () => void;
    onActivityChanged?: () => void | Promise<void>;
  } = {},
) {
  const onUpdated = options.onUpdated ?? vi.fn();
  const onReload = options.onReload ?? vi.fn();
  const onActivityChanged = options.onActivityChanged ?? vi.fn();
  renderWithProviders(
    <AssignmentControl
      ticket={ticket}
      onUpdated={onUpdated}
      onReload={onReload}
      onActivityChanged={onActivityChanged}
    />,
  );
  return { onUpdated, onReload, onActivityChanged };
}

async function openCandidateList(user: ReturnType<typeof userEvent.setup>) {
  const trigger = screen.getByRole("combobox", {
    name: "Eligible team member",
  });
  await user.click(trigger);
  return {
    trigger,
    search: await screen.findByRole("combobox", {
      name: "Search Eligible team member",
    }),
  };
}

async function chooseCandidate(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
) {
  await openCandidateList(user);
  fireEvent.click(
    await screen.findByRole("option", {
      name: new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
    }),
  );
}

beforeEach(() => {
  harness.assignees.mockReset();
  harness.assign.mockReset();
  harness.toastSuccess.mockReset();
  harness.assignees.mockResolvedValue({
    results: [CURRENT_ASSIGNEE, ACCOUNTANT, RECORDS_CLERK],
  });
});

describe("internal ticket assignment", () => {
  it("keeps ownership read-only and does not request candidates without a server capability", () => {
    renderControl();

    expect(screen.getByRole("heading", { name: "Assignment" })).toBeVisible();
    expect(screen.getByText("Current owner")).toBeVisible();
    expect(screen.getByText(CURRENT_ASSIGNEE.display_name)).toBeVisible();
    expect(
      screen.queryByRole("combobox", { name: "Eligible team member" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Self-assign" }),
    ).not.toBeInTheDocument();
    expect(harness.assignees).not.toHaveBeenCalled();
  });

  it("loads only server-authoritative candidates and shows designation and team context", async () => {
    renderControl(ticketWithCapabilities({ can_assign: true }));

    await waitFor(() =>
      expect(harness.assignees).toHaveBeenCalledWith(BASE_TICKET.number, ""),
    );
    const user = userEvent.setup();
    await openCandidateList(user);

    const option = screen
      .getByText(ACCOUNTANT.display_name)
      .closest("[role=option]");
    expect(option).not.toBeNull();
    expect(
      within(option as HTMLElement).getByText("Accountant · Finance"),
    ).toBeVisible();
  });

  it("debounces candidate searches and stale responses cannot replace the latest results", async () => {
    const finance = deferred<{ results: TicketAssignee[] }>();
    const records = deferred<{ results: TicketAssignee[] }>();
    harness.assignees.mockImplementation((_number: string, search: string) => {
      if (search === "finance") return finance.promise;
      if (search === "records") return records.promise;
      return Promise.resolve({ results: [] });
    });
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }));

    const { search } = await openCandidateList(user);
    await user.type(search, "finance");
    await waitFor(
      () =>
        expect(harness.assignees).toHaveBeenCalledWith(
          BASE_TICKET.number,
          "finance",
        ),
      { timeout: 1000 },
    );
    await user.clear(search);
    await user.type(search, "records");
    await waitFor(
      () =>
        expect(harness.assignees).toHaveBeenCalledWith(
          BASE_TICKET.number,
          "records",
        ),
      { timeout: 1000 },
    );

    records.resolve({ results: [RECORDS_CLERK] });
    expect(await screen.findByText(RECORDS_CLERK.display_name)).toBeVisible();

    finance.resolve({ results: [ACCOUNTANT] });
    await waitFor(() =>
      expect(screen.getByText(RECORDS_CLERK.display_name)).toBeVisible(),
    );
    expect(screen.queryByText(ACCOUNTANT.display_name)).not.toBeInTheDocument();
  });

  it("confirms a proposed transfer with ticket and immutable owner snapshots", async () => {
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }));

    await chooseCandidate(user, ACCOUNTANT.display_name);

    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByRole("heading", {
        name: "Confirm ticket assignment",
      }),
    ).toBeVisible();
    expect(dialog).toHaveTextContent(`Ticket: ${BASE_TICKET.number}`);
    expect(dialog).toHaveTextContent(
      `Previous assignee: ${CURRENT_ASSIGNEE.display_name}`,
    );
    expect(dialog).toHaveTextContent(
      `New assignee: ${ACCOUNTANT.display_name}`,
    );
  });

  it("requires a trimmed reason before transfer confirmation is enabled", async () => {
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }));

    await chooseCandidate(user, ACCOUNTANT.display_name);
    const confirm = screen.getByRole("button", { name: "Transfer" });
    expect(confirm).toBeDisabled();
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "   ",
    );
    expect(confirm).toBeDisabled();
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Move to finance review",
    );
    expect(confirm).toBeEnabled();
  });

  it("requires a reason before unassignment confirmation is enabled", async () => {
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }));

    await chooseCandidate(user, "Unassigned");
    const confirm = screen.getByRole("button", { name: "Unassign" });
    expect(confirm).toBeDisabled();
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Return to queue",
    );
    expect(confirm).toBeEnabled();
  });

  it("allows an initial assignment to be confirmed without a reason", async () => {
    const user = userEvent.setup();
    renderControl(unassignedTicket({ can_assign: true }));

    await chooseCandidate(user, ACCOUNTANT.display_name);

    expect(screen.getByRole("button", { name: "Assign" })).toBeEnabled();
    expect(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
    ).not.toBeRequired();
  });

  it("cancels without a request and returns focus to the assignment trigger", async () => {
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }));

    await chooseCandidate(user, ACCOUNTANT.display_name);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(harness.assign).not.toHaveBeenCalled();
    const trigger = screen.getByRole("combobox", {
      name: "Eligible team member",
    });
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(trigger).toHaveTextContent(CURRENT_ASSIGNEE.display_name);
  });

  it("submits exactly once when Confirm receives two clicks", async () => {
    const pending = deferred<AssignmentResponse>();
    harness.assign.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    renderControl(unassignedTicket({ can_assign: true }));

    await chooseCandidate(user, ACCOUNTANT.display_name);
    const confirm = screen.getByRole("button", { name: "Assign" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    await waitFor(() => expect(harness.assign).toHaveBeenCalledTimes(1));
    expect(harness.assign).toHaveBeenCalledWith(BASE_TICKET.number, {
      assignee_id: ACCOUNTANT.id,
      expected_updated_at: BASE_TICKET.updated_at,
      reason: "",
    });
    pending.resolve(
      responseWith({
        ...unassignedTicket({ can_assign: true }),
        assignee: ACCOUNTANT.id,
        assignee_detail: {
          id: ACCOUNTANT.id,
          display_name: ACCOUNTANT.display_name,
        },
      }),
    );
  });

  it("uses only self_assignee_detail for self-assignment and still confirms", async () => {
    const selfTicket = unassignedTicket({
      can_assign: false,
      can_self_assign: true,
      self_assignee_id: RECORDS_CLERK.id,
      self_assignee_detail: RECORDS_CLERK,
    });
    const user = userEvent.setup();
    renderControl(selfTicket);

    expect(harness.assignees).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Self-assign" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Previous assignee: Unassigned");
    expect(dialog).toHaveTextContent(
      `New assignee: ${RECORDS_CLERK.display_name}`,
    );
    expect(harness.assignees).not.toHaveBeenCalled();
  });

  it("keeps the proposed candidate and reason after a stale-ticket conflict", async () => {
    harness.assign.mockRejectedValue(
      new ApiError(409, {
        code: "stale_ticket",
        detail: "The ticket changed.",
        fields: { expected_updated_at: ["Use the current ticket version."] },
        correlation_id: "corr-assignment-stale",
      }),
    );
    const user = userEvent.setup();
    const { onReload } = renderControl(
      ticketWithCapabilities({ can_assign: true }),
    );

    await chooseCandidate(user, ACCOUNTANT.display_name);
    const reason = screen.getByRole("textbox", { name: "Reason for transfer" });
    await user.type(reason, "Finance review required");
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    expect(
      await screen.findByText("This ticket changed since you opened it"),
    ).toBeVisible();
    expect(screen.getByRole("dialog")).toHaveTextContent(
      `New assignee: ${ACCOUNTANT.display_name}`,
    );
    expect(reason).toHaveValue("Finance review required");
    expect(onReload).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(onReload).toHaveBeenCalledTimes(1);
  });

  it("keeps the dialog open and renders structured validation errors", async () => {
    harness.assign.mockRejectedValue(
      new ApiError(400, {
        code: "invalid_assignment",
        detail: "Review the highlighted assignment values.",
        fields: { reason: ["Provide a more specific transfer reason."] },
        correlation_id: "corr-assignment-400",
      }),
    );
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }));

    await chooseCandidate(user, ACCOUNTANT.display_name);
    const reason = screen.getByRole("textbox", { name: "Reason for transfer" });
    await user.type(reason, "Too vague");
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    expect(
      await screen.findByText("Provide a more specific transfer reason."),
    ).toBeVisible();
    expect(
      screen.getByText("Review the highlighted assignment values."),
    ).toBeVisible();
    expect(screen.getByText(/corr-assignment-400/)).toBeVisible();
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(reason).toHaveValue("Too vague");
  });

  it("discards the proposal after a permission or eligibility change", async () => {
    harness.assign.mockRejectedValue(
      new ApiError(403, {
        code: "assignment_forbidden",
        detail: "The selected staff member is no longer eligible.",
        fields: {},
        correlation_id: "corr-assignment-403",
      }),
    );
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }));

    await chooseCandidate(user, ACCOUNTANT.display_name);
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Finance review required",
    );
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    expect(
      await screen.findByText("Assignment permission changed"),
    ).toBeVisible();
    expect(
      screen.getByText("The selected staff member is no longer eligible."),
    ).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Eligible team member" }),
    ).toHaveTextContent(CURRENT_ASSIGNEE.display_name);
  });

  it("locks every assignment interaction while the authoritative request is pending", async () => {
    const pending = deferred<AssignmentResponse>();
    harness.assign.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }));

    await chooseCandidate(user, ACCOUNTANT.display_name);
    const reason = screen.getByRole("textbox", { name: "Reason for transfer" });
    await user.type(reason, "Finance review required");
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    expect(
      screen.getByRole("button", { name: "Transferring…" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(reason).toBeDisabled();
    pending.resolve(
      responseWith({
        ...BASE_TICKET,
        assignee: ACCOUNTANT.id,
        assignee_detail: {
          id: ACCOUNTANT.id,
          display_name: ACCOUNTANT.display_name,
        },
      }),
    );
  });

  it("updates first, renders and toasts the immutable receipt, then awaits activity", async () => {
    const activity = deferred<void>();
    const callOrder: string[] = [];
    const onUpdated = vi.fn(() => {
      callOrder.push("updated");
    });
    const onActivityChanged = vi.fn(() => {
      callOrder.push("activity");
      return activity.promise;
    });
    const refreshed = {
      ...BASE_TICKET,
      assignee: ACCOUNTANT.id,
      assignee_detail: {
        id: ACCOUNTANT.id,
        display_name: "Conflicting name from mutable ticket",
      },
      updated_at: "2026-07-30T10:30:00Z",
    };
    harness.assign.mockResolvedValue(responseWith(refreshed));
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }), {
      onUpdated,
      onActivityChanged,
    });

    await chooseCandidate(user, ACCOUNTANT.display_name);
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Finance review required",
    );
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(refreshed));
    expect(harness.assign).toHaveBeenCalledWith(BASE_TICKET.number, {
      assignee_id: ACCOUNTANT.id,
      expected_updated_at: BASE_TICKET.updated_at,
      reason: "Finance review required",
    });
    expect(callOrder).toEqual(["updated", "activity"]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const receipt = screen.getByRole("status");
    expect(receipt).toHaveTextContent(
      `${RECEIPT.ticket_number} reassigned: Previous owner from receipt → New owner from receipt`,
    );
    expect(receipt).toHaveTextContent("by Deputy Master Dlamini.");
    expect(receipt).not.toHaveTextContent(
      "Conflicting name from mutable ticket",
    );
    expect(harness.toastSuccess).toHaveBeenCalledWith(receipt.textContent);

    activity.resolve();
    await waitFor(() => expect(onActivityChanged).toHaveBeenCalledTimes(1));
  });
});
