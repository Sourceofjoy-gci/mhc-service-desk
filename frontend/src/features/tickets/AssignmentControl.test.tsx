import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, useLayoutEffect } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
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
  const view = renderWithProviders(
    <AssignmentControl
      ticket={ticket}
      onUpdated={onUpdated}
      onReload={onReload}
      onActivityChanged={onActivityChanged}
    />,
  );
  return {
    queryClient: view.queryClient,
    onUpdated,
    onReload,
    onActivityChanged,
    rerenderTicket: (nextTicket: TicketDetail) =>
      view.rerender(
        <AssignmentControl
          ticket={nextTicket}
          onUpdated={onUpdated}
          onReload={onReload}
          onActivityChanged={onActivityChanged}
        />,
      ),
  };
}

function ResolveOnLayout({ resolve }: { resolve: () => void }) {
  useLayoutEffect(resolve, [resolve]);
  return null;
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

  it("blocks every directory assignment path when the initial candidate lookup fails", async () => {
    harness.assignees.mockRejectedValue(
      new ApiError(503, {
        code: "candidate_directory_unavailable",
        detail: "The eligible staff directory is temporarily unavailable.",
        fields: {},
        correlation_id: "corr-candidates-initial",
      }),
    );
    renderControl(ticketWithCapabilities({ can_assign: true }));

    expect(
      await screen.findByText(
        "The eligible staff directory is temporarily unavailable. Reference: corr-candidates-initial",
      ),
    ).toBeVisible();
    const trigger = screen.getByRole("combobox", {
      name: "Eligible team member",
    });
    expect(trigger).toBeDisabled();
    fireEvent.click(trigger);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(harness.assign).not.toHaveBeenCalled();
  });

  it("blocks a stale proposal after a background lookup error and recovers only after a successful lookup", async () => {
    const backgroundLookup = deferred<{ results: TicketAssignee[] }>();
    const lookupFailure = new ApiError(503, {
      code: "candidate_directory_unavailable",
      detail: "The eligible staff directory is temporarily unavailable.",
      fields: {},
      correlation_id: "corr-candidates-background",
    });
    const user = userEvent.setup();
    const { queryClient } = renderControl(
      ticketWithCapabilities({ can_assign: true }),
    );

    await chooseCandidate(user, ACCOUNTANT.display_name);
    const reason = screen.getByRole("textbox", { name: "Reason for transfer" });
    await user.type(reason, "Finance review required");
    harness.assignees.mockReturnValueOnce(backgroundLookup.promise);
    let backgroundRefetch!: Promise<void>;
    act(() => {
      backgroundRefetch = queryClient.refetchQueries({
        queryKey: ["ticket", BASE_TICKET.number, "assignees"],
        type: "active",
      });
    });

    await waitFor(() => expect(harness.assignees).toHaveBeenCalledTimes(2));
    const confirm = screen.getByRole("button", { name: "Transfer" });
    expect(confirm).toBeDisabled();

    await act(async () => {
      backgroundLookup.reject(lookupFailure);
      await backgroundRefetch;
    });

    const dialog = screen.getByRole("dialog");
    const lookupAlert = await within(dialog).findByRole("alert");
    expect(
      within(lookupAlert).getByText("Eligible team member lookup unavailable"),
    ).toBeVisible();
    expect(
      within(lookupAlert).getByText(
        "The eligible staff directory is temporarily unavailable. Reference: corr-candidates-background",
      ),
    ).toBeVisible();
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(harness.assign).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent(
      `New assignee: ${ACCOUNTANT.display_name}`,
    );

    harness.assignees.mockResolvedValueOnce({
      results: [CURRENT_ASSIGNEE, ACCOUNTANT, RECORDS_CLERK],
    });
    await act(async () => {
      await queryClient.refetchQueries({
        queryKey: ["ticket", BASE_TICKET.number, "assignees"],
        type: "active",
      });
    });

    await waitFor(() => expect(confirm).toBeEnabled());
    expect(
      within(dialog).queryByText(/corr-candidates-background/),
    ).not.toBeInTheDocument();
  });

  it("blocks an open unassignment confirmation after the candidate lookup fails", async () => {
    const user = userEvent.setup();
    const { queryClient } = renderControl(
      ticketWithCapabilities({ can_assign: true }),
    );

    await chooseCandidate(user, "Unassigned");
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Return to queue",
    );
    harness.assignees.mockRejectedValueOnce(
      new ApiError(503, {
        code: "candidate_directory_unavailable",
        detail: "The eligible staff directory is temporarily unavailable.",
        fields: {},
        correlation_id: "corr-candidates-unassign",
      }),
    );
    await act(async () => {
      await queryClient.refetchQueries({
        queryKey: ["ticket", BASE_TICKET.number, "assignees"],
        type: "active",
      });
    });

    const dialog = screen.getByRole("dialog");
    expect(
      await within(dialog).findByText(
        "The eligible staff directory is temporarily unavailable. Reference: corr-candidates-unassign",
      ),
    ).toBeVisible();
    const confirm = screen.getByRole("button", { name: "Unassign" });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(harness.assign).not.toHaveBeenCalled();
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
    expect(dialog).toHaveTextContent(
      `Ticket: ${BASE_TICKET.number} — ${BASE_TICKET.title}`,
    );
    expect(dialog).toHaveTextContent(
      `Previous assignee: ${CURRENT_ASSIGNEE.display_name}`,
    );
    expect(dialog).toHaveTextContent(
      `New assignee: ${ACCOUNTANT.display_name}`,
    );
    expect(dialog).toHaveTextContent(
      "Designation / team: Accountant · Finance",
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
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "New assignee: Unassigned",
    );
    expect(screen.getByRole("dialog")).not.toHaveTextContent(
      "Designation / team:",
    );
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

  it("clears only a stale conflict when the same ticket refreshes and retries with its new timestamp", async () => {
    const refreshedTimestamp = "2026-07-30T10:45:00Z";
    const refreshedTicket = {
      ...ticketWithCapabilities({ can_assign: true }),
      updated_at: refreshedTimestamp,
    };
    harness.assign
      .mockRejectedValueOnce(
        new ApiError(409, {
          code: "stale_ticket",
          detail: "The ticket changed.",
          fields: {
            expected_updated_at: ["Use the current ticket version."],
          },
          correlation_id: "corr-assignment-stale-refresh",
        }),
      )
      .mockResolvedValueOnce(responseWith(refreshedTicket));
    const user = userEvent.setup();
    const { rerenderTicket } = renderControl(
      ticketWithCapabilities({ can_assign: true }),
    );

    await chooseCandidate(user, ACCOUNTANT.display_name);
    const reason = screen.getByRole("textbox", {
      name: "Reason for transfer",
    });
    await user.type(reason, "Finance review required");
    await user.click(screen.getByRole("button", { name: "Transfer" }));
    expect(
      await screen.findByText("This ticket changed since you opened it"),
    ).toBeVisible();

    rerenderTicket(refreshedTicket);

    await waitFor(() =>
      expect(
        screen.queryByText("This ticket changed since you opened it"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent(
      `New assignee: ${ACCOUNTANT.display_name}`,
    );
    expect(reason).toHaveValue("Finance review required");
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() => expect(harness.assign).toHaveBeenCalledTimes(2));
    expect(harness.assign).toHaveBeenLastCalledWith(BASE_TICKET.number, {
      assignee_id: ACCOUNTANT.id,
      expected_updated_at: refreshedTimestamp,
      reason: "Finance review required",
    });
  });

  it("drops every transient interaction when the component changes tickets", async () => {
    harness.assign.mockResolvedValue(
      responseWith({
        ...BASE_TICKET,
        assignee: ACCOUNTANT.id,
        assignee_detail: {
          id: ACCOUNTANT.id,
          display_name: ACCOUNTANT.display_name,
        },
      }),
    );
    const firstTicket = ticketWithCapabilities({ can_assign: true });
    const secondTicket = {
      ...ticketWithCapabilities({ can_assign: true }),
      id: "ticket-2",
      number: "MHC-2026-000002",
      title: "Second estate matter",
      assignee: ACCOUNTANT.id,
      assignee_detail: {
        id: ACCOUNTANT.id,
        display_name: ACCOUNTANT.display_name,
      },
      updated_at: "2026-07-30T11:00:00Z",
    };
    const user = userEvent.setup();
    const { rerenderTicket } = renderControl(firstTicket);

    await chooseCandidate(user, ACCOUNTANT.display_name);
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "First ticket finance review",
    );
    await user.click(screen.getByRole("button", { name: "Transfer" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      BASE_TICKET.number,
    );

    await openCandidateList(user);
    await user.type(
      screen.getByRole("combobox", {
        name: "Search Eligible team member",
      }),
      "records",
    );
    fireEvent.click(
      await screen.findByRole("option", { name: /Siphiwe Ndlovu/ }),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent(BASE_TICKET.number);

    rerenderTicket(secondTicket);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("Current owner").nextSibling).toHaveTextContent(
      ACCOUNTANT.display_name,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: "Eligible team member" }),
      ).toHaveTextContent(ACCOUNTANT.display_name),
    );
    const { search } = await openCandidateList(user);
    expect(search).toHaveValue("");
    await waitFor(() =>
      expect(harness.assignees).toHaveBeenCalledWith(secondTicket.number, ""),
    );
    expect(harness.assign).toHaveBeenCalledTimes(1);
  });

  it("does not surface a late assignment result from the previous ticket scope", async () => {
    const pending = deferred<AssignmentResponse>();
    harness.assign.mockReturnValue(pending.promise);
    const firstTicket = unassignedTicket({ can_assign: true });
    const secondTicket = {
      ...BASE_TICKET,
      id: "ticket-2",
      number: "MHC-2026-000002",
      title: "Second estate matter",
    };
    const user = userEvent.setup();
    const { onUpdated, onActivityChanged, rerenderTicket } =
      renderControl(firstTicket);

    await chooseCandidate(user, ACCOUNTANT.display_name);
    await user.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(harness.assign).toHaveBeenCalledTimes(1));

    rerenderTicket(secondTicket);
    await act(async () => {
      pending.resolve(
        responseWith({
          ...firstTicket,
          assignee: ACCOUNTANT.id,
          assignee_detail: {
            id: ACCOUNTANT.id,
            display_name: ACCOUNTANT.display_name,
          },
        }),
      );
      await pending.promise;
    });

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(harness.toastSuccess).not.toHaveBeenCalled();
    expect(onUpdated).not.toHaveBeenCalled();
    expect(onActivityChanged).not.toHaveBeenCalled();
    expect(screen.getByText(CURRENT_ASSIGNEE.display_name)).toBeVisible();
  });

  it("does not apply an older assignment response after the same ticket version refreshes", async () => {
    const pending = deferred<AssignmentResponse>();
    harness.assign.mockReturnValue(pending.promise);
    const originalTicket = unassignedTicket({ can_assign: true });
    const refreshedTicket = {
      ...originalTicket,
      title: "Server-refreshed estate matter",
      updated_at: "2026-07-30T10:45:00Z",
    };
    const staleResponseTicket = {
      ...originalTicket,
      assignee: ACCOUNTANT.id,
      assignee_detail: {
        id: ACCOUNTANT.id,
        display_name: ACCOUNTANT.display_name,
      },
      updated_at: "2026-07-30T10:30:00Z",
    };
    const user = userEvent.setup();
    const { onUpdated, onActivityChanged, rerenderTicket } =
      renderControl(originalTicket);

    await chooseCandidate(user, ACCOUNTANT.display_name);
    await user.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(harness.assign).toHaveBeenCalledTimes(1));
    rerenderTicket(refreshedTicket);

    await act(async () => {
      pending.resolve(responseWith(staleResponseTicket));
      await pending.promise;
    });

    expect(onUpdated).not.toHaveBeenCalled();
    expect(onActivityChanged).not.toHaveBeenCalled();
    expect(harness.toastSuccess).not.toHaveBeenCalled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("closes the old ticket scope during the new ticket commit before passive cleanup", async () => {
    const pending = deferred<AssignmentResponse>();
    harness.assign.mockReturnValue(pending.promise);
    const ticketA = unassignedTicket({ can_assign: true });
    const ticketB = {
      ...ticketWithCapabilities({ can_assign: true }),
      id: "ticket-2",
      number: "MHC-2026-000002",
      title: "Second estate matter",
      updated_at: "2026-07-30T11:00:00Z",
    };
    const lateTicketA = {
      ...ticketA,
      assignee: ACCOUNTANT.id,
      assignee_detail: {
        id: ACCOUNTANT.id,
        display_name: ACCOUNTANT.display_name,
      },
      updated_at: "2026-07-30T10:30:00Z",
    };
    const onUpdated = vi.fn();
    const onReload = vi.fn();
    const onActivityChanged = vi.fn();
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const actEnvironment = globalThis as typeof globalThis & {
      IS_REACT_ACT_ENVIRONMENT?: boolean;
    };
    const previousActEnvironment = actEnvironment.IS_REACT_ACT_ENVIRONMENT;
    const renderTicket = (ticket: TicketDetail, resolve?: () => void) => (
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter
            initialEntries={["/"]}
          >
            <AssignmentControl
              ticket={ticket}
              onUpdated={onUpdated}
              onReload={onReload}
              onActivityChanged={onActivityChanged}
            />
            {resolve ? <ResolveOnLayout resolve={resolve} /> : null}
          </MemoryRouter>
        </QueryClientProvider>
      </StrictMode>
    );

    try {
      await act(async () => root.render(renderTicket(ticketA)));
      await waitFor(() =>
        expect(
          within(container).getByRole("combobox", {
            name: "Eligible team member",
          }),
        ).toBeEnabled(),
      );
      fireEvent.click(
        within(container).getByRole("combobox", {
          name: "Eligible team member",
        }),
      );
      fireEvent.click(
        await within(container).findByRole("option", {
          name: /Thandi Mokoena/,
        }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Assign" }));
      await waitFor(() => expect(harness.assign).toHaveBeenCalledTimes(1));
      const mutationA = queryClient.getMutationCache().getAll()[0];
      const deliverLateSuccess = mutationA.options.onSuccess as unknown as (
        response: AssignmentResponse,
        variables: unknown,
      ) => Promise<void>;
      const variables = mutationA.state.variables;
      expect(deliverLateSuccess).toBeTypeOf("function");

      actEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
      flushSync(() => {
        root.render(
          renderTicket(ticketB, () => {
            void deliverLateSuccess(responseWith(lateTicketA), variables);
          }),
        );
      });
      actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;

      expect(onUpdated).not.toHaveBeenCalled();
      expect(onActivityChanged).not.toHaveBeenCalled();
      expect(harness.toastSuccess).not.toHaveBeenCalled();
      expect(within(container).queryByRole("status")).not.toBeInTheDocument();
    } finally {
      actEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment;
      flushSync(() => root.unmount());
      pending.resolve(responseWith(lateTicketA));
      container.remove();
    }
  });

  it("closes and discards a directory proposal when can_assign is revoked", async () => {
    const user = userEvent.setup();
    const { rerenderTicket } = renderControl(
      ticketWithCapabilities({ can_assign: true }),
    );

    await chooseCandidate(user, ACCOUNTANT.display_name);
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Finance review required",
    );

    rerenderTicket(ticketWithCapabilities({ can_assign: false }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(harness.assign).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Transfer" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(CURRENT_ASSIGNEE.display_name)).toBeVisible();
  });

  it("preserves a self proposal only while the same self detail remains authorized", async () => {
    const selfTicket = unassignedTicket({
      can_assign: false,
      can_self_assign: true,
      self_assignee_id: RECORDS_CLERK.id,
      self_assignee_detail: RECORDS_CLERK,
    });
    harness.assign.mockResolvedValue(
      responseWith({
        ...selfTicket,
        assignee: RECORDS_CLERK.id,
        assignee_detail: {
          id: RECORDS_CLERK.id,
          display_name: RECORDS_CLERK.display_name,
        },
      }),
    );
    const user = userEvent.setup();
    const { rerenderTicket } = renderControl(selfTicket);

    await user.click(screen.getByRole("button", { name: "Self-assign" }));
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Pick up own queue work",
    );
    rerenderTicket({ ...selfTicket, title: "Server-refreshed title" });

    expect(screen.getByRole("dialog")).toHaveTextContent(
      `New assignee: ${RECORDS_CLERK.display_name}`,
    );
    await user.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(harness.assign).toHaveBeenCalledTimes(1));
    expect(harness.assign).toHaveBeenCalledWith(BASE_TICKET.number, {
      assignee_id: RECORDS_CLERK.id,
      expected_updated_at: BASE_TICKET.updated_at,
      reason: "Pick up own queue work",
    });
  });

  it("blocks an ineligible self-assignment until Reload yields a new authoritative ticket state", async () => {
    const selfTicket = unassignedTicket({
      can_assign: false,
      can_self_assign: true,
      self_assignee_id: RECORDS_CLERK.id,
      self_assignee_detail: RECORDS_CLERK,
    });
    const refreshedTicket = {
      ...selfTicket,
      updated_at: "2026-07-30T10:45:00Z",
    };
    const assignedTicket = {
      ...refreshedTicket,
      assignee: RECORDS_CLERK.id,
      assignee_detail: {
        id: RECORDS_CLERK.id,
        display_name: RECORDS_CLERK.display_name,
      },
    };
    harness.assign
      .mockRejectedValueOnce(
        new ApiError(400, {
          code: "invalid_assignment",
          detail: "Your staff eligibility changed before assignment.",
          fields: {
            assignee_id: ["Reload this ticket before trying again."],
          },
          correlation_id: "corr-self-ineligible",
        }),
      )
      .mockResolvedValueOnce(
        responseWith(assignedTicket, {
          ...RECEIPT,
          previous_assignee: null,
          new_assignee: RECORDS_CLERK,
        }),
      );
    const user = userEvent.setup();
    const { onReload, rerenderTicket } = renderControl(selfTicket);

    await user.click(screen.getByRole("button", { name: "Self-assign" }));
    const reason = screen.getByRole("textbox", { name: "Reason for transfer" });
    await user.type(reason, "Pick up own queue work");
    await user.click(screen.getByRole("button", { name: "Assign" }));

    expect(
      await screen.findByText("Selected staff member is no longer eligible"),
    ).toBeVisible();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(
      `New assignee: ${RECORDS_CLERK.display_name}`,
    );
    expect(dialog).toHaveTextContent(
      "Designation / team: Records Clerk · Records",
    );
    expect(reason).toHaveValue("Pick up own queue work");
    expect(
      screen.queryByRole("button", { name: "Assign" }),
    ).not.toBeInTheDocument();
    const reload = screen.getByRole("button", { name: "Reload" });
    fireEvent.submit(dialog.querySelector("form") as HTMLFormElement);
    expect(harness.assign).toHaveBeenCalledTimes(1);

    await user.click(reload);
    expect(onReload).toHaveBeenCalledTimes(1);
    rerenderTicket(selfTicket);
    expect(screen.getByRole("button", { name: "Reload" })).toBeVisible();
    fireEvent.submit(dialog.querySelector("form") as HTMLFormElement);
    expect(harness.assign).toHaveBeenCalledTimes(1);

    rerenderTicket(refreshedTicket);
    const retry = await screen.findByRole("button", { name: "Assign" });
    expect(retry).toBeEnabled();
    await user.click(retry);

    await waitFor(() => expect(harness.assign).toHaveBeenCalledTimes(2));
    expect(harness.assign).toHaveBeenLastCalledWith(BASE_TICKET.number, {
      assignee_id: RECORDS_CLERK.id,
      expected_updated_at: refreshedTicket.updated_at,
      reason: "Pick up own queue work",
    });
  });

  it("discards a self proposal when self_assignee_detail changes identity", async () => {
    const selfTicket = unassignedTicket({
      can_assign: false,
      can_self_assign: true,
      self_assignee_id: RECORDS_CLERK.id,
      self_assignee_detail: RECORDS_CLERK,
    });
    const user = userEvent.setup();
    const { rerenderTicket } = renderControl(selfTicket);

    await user.click(screen.getByRole("button", { name: "Self-assign" }));
    rerenderTicket(
      ticketWithCapabilities(
        {
          can_assign: false,
          can_self_assign: true,
          self_assignee_id: ACCOUNTANT.id,
          self_assignee_detail: ACCOUNTANT,
        },
        selfTicket,
      ),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(harness.assign).not.toHaveBeenCalled();
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
    expect(reason).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(reason).toHaveFocus());
    expect(
      screen
        .getByText("Provide a more specific transfer reason.")
        .closest('[role="alert"]'),
    ).toBeVisible();
  });

  it("keeps an ineligible target proposal but gates resubmission until candidates refresh", async () => {
    const refreshedCandidates = deferred<{ results: TicketAssignee[] }>();
    harness.assignees
      .mockResolvedValueOnce({
        results: [CURRENT_ASSIGNEE, ACCOUNTANT, RECORDS_CLERK],
      })
      .mockReturnValueOnce(refreshedCandidates.promise);
    harness.assign.mockRejectedValue(
      new ApiError(400, {
        code: "invalid_assignment",
        detail: "The selected staff member cannot action this ticket now.",
        fields: {
          assignee_id: ["Select a currently eligible team member."],
        },
        correlation_id: "corr-assignee-ineligible",
      }),
    );
    const user = userEvent.setup();
    renderControl(ticketWithCapabilities({ can_assign: true }));

    await chooseCandidate(user, ACCOUNTANT.display_name);
    const reason = screen.getByRole("textbox", { name: "Reason for transfer" });
    await user.type(reason, "Finance review required");
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    expect(
      await screen.findByText("Selected staff member is no longer eligible"),
    ).toBeVisible();
    expect(
      screen.getByText(
        "The selected staff member cannot action this ticket now.",
      ),
    ).toBeVisible();
    expect(
      screen.getByText("Select a currently eligible team member."),
    ).toBeVisible();
    expect(screen.getByRole("dialog")).toHaveTextContent(
      `New assignee: ${ACCOUNTANT.display_name}`,
    );
    expect(reason).toHaveValue("Finance review required");
    const confirm = screen.getByRole("button", { name: "Transfer" });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(harness.assign).toHaveBeenCalledTimes(1);
    expect(harness.assignees).toHaveBeenCalledTimes(2);

    refreshedCandidates.resolve({
      results: [CURRENT_ASSIGNEE, ACCOUNTANT, RECORDS_CLERK],
    });
    await waitFor(() => expect(confirm).toBeEnabled());
  });

  it("treats ineligible_assignee as a target eligibility change", async () => {
    harness.assign.mockRejectedValue(
      new ApiError(400, {
        code: "ineligible_assignee",
        detail: "The proposed owner is outside the ticket scope.",
        fields: { assignee_id: ["Choose another eligible owner."] },
        correlation_id: "corr-ineligible-code",
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
      await screen.findByText("Selected staff member is no longer eligible"),
    ).toBeVisible();
    expect(screen.getByText("Choose another eligible owner.")).toBeVisible();
  });

  it("offers Reload for an assignment-time missing ticket without losing proposal context", async () => {
    harness.assign.mockRejectedValue(
      new ApiError(404, {
        code: "ticket_not_found",
        detail: "This ticket no longer exists or is no longer accessible.",
        fields: {},
        correlation_id: "corr-assignment-404",
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
      await screen.findByText("Ticket is no longer available"),
    ).toBeVisible();
    expect(
      screen.getByText(
        "This ticket no longer exists or is no longer accessible.",
      ),
    ).toBeVisible();
    expect(screen.getByRole("dialog")).toHaveTextContent(
      `New assignee: ${ACCOUNTANT.display_name}`,
    );
    expect(reason).toHaveValue("Finance review required");
    expect(onReload).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Reload" }));
    expect(onReload).toHaveBeenCalledTimes(1);
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

  it("renders a safe receipt fallback when the server timestamp is malformed", async () => {
    const malformedReceipt: AssignmentReceipt = {
      ...RECEIPT,
      occurred_at: "not-a-date",
    };
    const refreshed = {
      ...BASE_TICKET,
      assignee: ACCOUNTANT.id,
      assignee_detail: {
        id: ACCOUNTANT.id,
        display_name: ACCOUNTANT.display_name,
      },
      updated_at: "2026-07-30T10:30:00Z",
    };
    harness.assign.mockResolvedValue(responseWith(refreshed, malformedReceipt));
    const user = userEvent.setup();
    const { onUpdated } = renderControl(
      ticketWithCapabilities({ can_assign: true }),
    );

    await chooseCandidate(user, ACCOUNTANT.display_name);
    await user.type(
      screen.getByRole("textbox", { name: "Reason for transfer" }),
      "Finance review required",
    );
    await user.click(screen.getByRole("button", { name: "Transfer" }));

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(refreshed));
    const receipt = screen.getByRole("status");
    expect(receipt).toHaveTextContent("on date/time unavailable");
    expect(receipt).not.toHaveTextContent("Invalid Date");
    expect(harness.toastSuccess).toHaveBeenCalledWith(receipt.textContent);
  });
});
