import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type TicketDetail } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { TransitionActions } from "./TransitionActions";

const harness = vi.hoisted(() => ({
  transition: vi.fn(),
  get: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      transition: harness.transition,
      get: harness.get,
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
  available_transition_codes: [
    "in_progress",
    "waiting_requester",
    "resolved",
  ],
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
  onUpdated = vi.fn(),
  onActivityChanged = vi.fn(),
) {
  renderWithProviders(
    <TransitionActions
      ticket={TICKET}
      onUpdated={onUpdated}
      onActivityChanged={onActivityChanged}
    />,
  );
  return { onUpdated, onActivityChanged };
}

async function openResolve(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Resolve" }));
  return {
    code: screen.getByRole("textbox", { name: "Resolution code" }),
    summary: screen.getByRole("textbox", { name: "Resolution summary" }),
  };
}

beforeEach(() => {
  harness.transition.mockReset();
  harness.get.mockReset();
});

describe("server-driven transition actions", () => {
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
    const refreshed = { ...TICKET, status_code: "resolved", status_name: "Resolved" };
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
    await user.click(screen.getByRole("button", { name: "Confirm Resolve" }));

    await waitFor(() => expect(harness.transition).toHaveBeenCalledTimes(1));
    expect(fields.code).toBeDisabled();
    expect(fields.summary).toBeDisabled();
    expect(screen.getByRole("button", { name: "Updating…" })).toBeDisabled();
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

    await waitFor(() => expect(harness.get).toHaveBeenCalledWith(TICKET.number));
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
