import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type ActivityItem } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { ActivityTimeline } from "./ActivityTimeline";

const harness = vi.hoisted(() => ({
  activity: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      activity: harness.activity,
    },
  };
});

const ITEMS: ActivityItem[] = [
  {
    id: "message:1",
    type: "message",
    category: "public_reply",
    occurred_at: "2026-07-27T08:00:00Z",
    actor: { subject: "agent-1", display_name: "Agent One" },
    visibility: "requester",
    payload: {
      direction: "outbound",
      author_label: "Agent One",
      body_text: "Requester-visible update",
      body_html_sanitized: "",
      delivery_status: "sent",
    },
  },
  {
    id: "note:1",
    type: "internal_note",
    category: "internal_note",
    occurred_at: "2026-07-27T08:00:00.500Z",
    actor: { subject: "agent-2", display_name: "Supervisor Two" },
    visibility: "internal",
    payload: { body: "Internal investigation detail" },
  },
  {
    id: "transition:1",
    type: "status_transition",
    category: "workflow",
    occurred_at: "2026-07-27T08:02:00Z",
    actor: { subject: "agent-1", display_name: "Agent One" },
    visibility: "internal",
    payload: { from: "triage", to: "in_progress", reason: "Started" },
  },
  {
    id: "audit:1",
    type: "work_state",
    category: "workflow",
    occurred_at: "2026-07-27T08:03:00Z",
    actor: { subject: "agent-1", display_name: "Agent One" },
    visibility: "internal",
    payload: {
      before: { team: "Intake", next_action: "Review" },
      after: { team: "Estates", next_action: "Call requester" },
    },
  },
  {
    id: "attachment:1",
    type: "attachment",
    category: "attachment",
    occurred_at: "2026-07-27T08:04:00Z",
    actor: { subject: "agent-1", display_name: "Agent One" },
    visibility: "internal",
    payload: {
      id: "attachment-1",
      filename: "evidence.pdf",
      size_bytes: 2048,
      content_type: "application/pdf",
      uploaded_by: "agent-1",
      uploaded_at: "2026-07-27T08:04:00Z",
      scan_status: "clean",
      download_available: true,
    },
  },
  {
    id: "relationship:1",
    type: "relationship",
    category: "relationship",
    occurred_at: "2026-07-27T08:05:00Z",
    actor: null,
    visibility: "internal",
    payload: {
      kind: "related",
      ticket_number: "MHC-2026-000099",
      direction: "outgoing",
    },
  },
];

const COMPLETE_CUSTODY_ITEMS: ActivityItem[] = [
  {
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
  },
  ITEMS[0],
  ITEMS[1],
  {
    id: "custody:assigned",
    type: "custody_event",
    category: "custody",
    occurred_at: "2026-07-27T08:03:00Z",
    actor: { subject: "master-1", display_name: "Master Dlamini" },
    visibility: "internal",
    payload: {
      action: "assigned",
      previous_owner: null,
      new_owner: {
        id: "staff-1",
        display_name: "Lindiwe Khumalo",
        designations: ["Estate Examiner"],
        team_labels: ["Estate Administration"],
      },
      previous_queue: null,
      new_queue: null,
      previous_status: null,
      new_status: null,
      actor_kind: "user",
      source_process: "ticket.assignment",
      reason: "Allocate for examination",
    },
  },
  {
    id: "custody:queue",
    type: "custody_event",
    category: "custody",
    occurred_at: "2026-07-27T08:04:00Z",
    actor: { subject: "master-1", display_name: "Master Dlamini" },
    visibility: "internal",
    payload: {
      action: "queue_changed",
      previous_owner: null,
      new_owner: null,
      previous_queue: { id: "queue-intake", label: "Intake" },
      new_queue: { id: "queue-estates", label: "Estates examination" },
      previous_status: null,
      new_status: null,
      actor_kind: "user",
      source_process: "ticket.routing",
      reason: "Route to the examining queue",
    },
  },
  {
    id: "custody:reassigned",
    type: "custody_event",
    category: "custody",
    occurred_at: "2026-07-27T08:05:00Z",
    actor: { subject: "deputy-master-1", display_name: "Deputy Master Naidoo" },
    visibility: "internal",
    payload: {
      action: "reassigned",
      previous_owner: {
        id: "staff-1",
        display_name: "Lindiwe Khumalo",
        designations: ["Estate Examiner"],
        team_labels: ["Estate Administration"],
      },
      new_owner: {
        id: "staff-2",
        display_name: "Thandi Mokoena",
        designations: ["Senior Accountant"],
        team_labels: ["Finance"],
      },
      previous_queue: null,
      new_queue: null,
      previous_status: null,
      new_status: null,
      actor_kind: "user",
      source_process: "ticket.assignment",
      reason: "Financial review required",
    },
  },
  {
    id: "custody:escalated",
    type: "custody_event",
    category: "custody",
    occurred_at: "2026-07-27T08:06:00Z",
    actor: { subject: "sla-monitor", display_name: "SLA monitor" },
    visibility: "internal",
    payload: {
      action: "escalated",
      previous_owner: null,
      new_owner: null,
      previous_queue: null,
      new_queue: null,
      previous_status: null,
      new_status: null,
      actor_kind: "system",
      source_process: "sla.monitor",
      reason: "Resolution SLA at risk",
    },
  },
  {
    id: "custody:status",
    type: "status_transition",
    category: "workflow",
    occurred_at: "2026-07-27T08:07:00Z",
    actor: { subject: "staff-2", display_name: "Thandi Mokoena" },
    visibility: "internal",
    payload: {
      action: "status_changed",
      from: "triage",
      to: "in_progress",
      reason: "Examination started",
    },
  },
  {
    id: "custody:unassigned",
    type: "custody_event",
    category: "custody",
    occurred_at: "2026-07-27T08:08:00Z",
    actor: { subject: "deputy-master-1", display_name: "Deputy Master Naidoo" },
    visibility: "internal",
    payload: {
      action: "unassigned",
      previous_owner: {
        id: "staff-2",
        display_name: "Thandi Mokoena",
        designations: ["Senior Accountant"],
        team_labels: ["Finance"],
      },
      new_owner: null,
      previous_queue: null,
      new_queue: null,
      previous_status: null,
      new_status: null,
      actor_kind: "user",
      source_process: "ticket.assignment",
      reason: "Return to the team queue",
    },
  },
  {
    id: "custody:reopened",
    type: "status_transition",
    category: "workflow",
    occurred_at: "2026-07-27T08:09:00Z",
    actor: { subject: "records-clerk-1", display_name: "Records Clerk Maseko" },
    visibility: "internal",
    payload: {
      action: "reopened",
      from: "resolved",
      to: "reopened",
      reason: "New records received",
    },
  },
  {
    id: "custody:closed",
    type: "status_transition",
    category: "workflow",
    occurred_at: "2026-07-27T08:10:00Z",
    actor: { subject: "master-1", display_name: "Master Dlamini" },
    visibility: "internal",
    payload: {
      action: "closed",
      from: "resolved",
      to: "closed",
      reason: "Matter completed",
    },
  },
];

beforeEach(() => {
  harness.activity.mockReset();
});

describe("typed ticket activity", () => {
  it("renders the complete creation-to-closure custody history in API order", async () => {
    harness.activity.mockResolvedValue({ results: COMPLETE_CUSTODY_ITEMS });

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    const timeline = await screen.findByRole("list", {
      name: "Ticket activity",
    });
    const entries = within(timeline).getAllByRole("listitem");
    expect(entries).toHaveLength(11);
    expect(entries.map((entry) => entry.textContent)).toEqual([
      expect.stringContaining("Ticket created"),
      expect.stringContaining("Requester-visible update"),
      expect.stringContaining("Internal investigation detail"),
      expect.stringContaining("Assigned"),
      expect.stringContaining("Queue changed"),
      expect.stringContaining("Reassigned"),
      expect.stringContaining("Escalated"),
      expect.stringContaining("Status changed"),
      expect.stringContaining("Unassigned"),
      expect.stringContaining("Ticket reopened"),
      expect.stringContaining("Ticket closed"),
    ]);

    expect(screen.getByText("Visible to requester")).toBeVisible();
    expect(screen.getByText("Internal only")).toBeVisible();
    expect(screen.getAllByText("Workflow")).toHaveLength(3);
    expect(screen.getAllByText("Chain of custody")).toHaveLength(6);

    expect(
      screen.getByText(
        "Owner: Unassigned → Lindiwe Khumalo (Estate Examiner · Estate Administration)",
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Owner: Lindiwe Khumalo (Estate Examiner · Estate Administration) → Thandi Mokoena (Senior Accountant · Finance)",
      ),
    ).toBeVisible();
    expect(
      screen.getByText(
        "Owner: Thandi Mokoena (Senior Accountant · Finance) → Unassigned",
      ),
    ).toBeVisible();
    expect(
      screen.getByText("Queue: Intake → Estates examination"),
    ).toBeVisible();
    expect(screen.getByText("Status: Triage → In progress")).toBeVisible();
    expect(screen.getByText("Status: Resolved → Reopened")).toBeVisible();
    expect(screen.getByText("Status: Resolved → Closed")).toBeVisible();

    expect(screen.getByText("System process: ticket.intake")).toBeVisible();
    expect(screen.getByText("System process: sla.monitor")).toBeVisible();
    for (const reason of [
      "Online submission received",
      "Allocate for examination",
      "Route to the examining queue",
      "Financial review required",
      "Resolution SLA at risk",
      "Examination started",
      "Return to the team queue",
      "New records received",
      "Matter completed",
    ]) {
      expect(screen.getByText(reason)).toBeVisible();
    }
    const timestamps = within(timeline).getAllByRole("time");
    expect(timestamps).toHaveLength(11);
    for (const timestamp of timestamps) {
      expect(timestamp).not.toBeEmptyDOMElement();
    }
    for (const [articleName, actorName] of [
      ["Custody event: Ticket created", "Ticket intake"],
      ["Custody event: Assigned", "Master Dlamini"],
      ["Custody event: Queue changed", "Master Dlamini"],
      ["Custody event: Reassigned", "Deputy Master Naidoo"],
      ["Custody event: Escalated", "SLA monitor"],
      ["Custody event: Unassigned", "Deputy Master Naidoo"],
      ["Workflow event: Status changed", "Thandi Mokoena"],
    ]) {
      expect(
        within(screen.getByRole("article", { name: articleName })).getByText(
          actorName,
        ),
      ).toBeVisible();
    }
    expect(
      screen.getByRole("article", {
        name: "Workflow event: Ticket reopened",
      }),
    ).toHaveTextContent("Records Clerk Maseko");
    expect(
      screen.getByRole("article", {
        name: "Workflow event: Ticket closed",
      }),
    ).toHaveTextContent("Master Dlamini");

    // The backend presents custody-backed status facts as workflow entries;
    // they must not be duplicated as generic custody cards.
    expect(screen.getAllByText("Ticket reopened")).toHaveLength(1);
    expect(screen.getAllByText("Ticket closed")).toHaveLength(1);
  });

  it("renders every supported activity type oldest first without raw payloads", async () => {
    harness.activity.mockResolvedValue({ results: ITEMS });

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    const timeline = await screen.findByRole("list", {
      name: "Ticket activity",
    });
    const entries = within(timeline).getAllByRole("listitem");
    expect(entries).toHaveLength(6);
    expect(entries.map((entry) => entry.textContent)).toEqual([
      expect.stringContaining("Requester-visible update"),
      expect.stringContaining("Internal investigation detail"),
      expect.stringContaining("Status: Triage → In progress"),
      expect.stringContaining("Team changed from Intake to Estates"),
      expect.stringContaining("evidence.pdf"),
      expect.stringContaining("MHC-2026-000099"),
    ]);

    expect(
      screen.getByRole("article", { name: "Requester-visible message" }),
    ).toHaveAttribute("data-visibility", "requester");
    expect(
      screen.getByRole("article", { name: "Internal note" }),
    ).toHaveAttribute("data-visibility", "internal");
    expect(screen.getByText("Visible to requester")).toBeVisible();
    expect(screen.getByText("Internal only")).toBeVisible();
    expect(screen.getAllByText("Workflow")).toHaveLength(2);
    expect(screen.getByText("Attachment")).toBeVisible();
    expect(screen.getByText("Relationship")).toBeVisible();

    expect(screen.getByText("Started")).toBeVisible();
    expect(
      screen.getByText("Next action changed from Review to Call requester"),
    ).toBeVisible();
    expect(screen.getByText("Scan: Clean")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "MHC-2026-000099" }),
    ).toHaveAttribute("href", "/tickets/MHC-2026-000099");

    expect(screen.getAllByText("Agent One").length).toBeGreaterThan(0);
    expect(entries[0].querySelector("time")).toHaveAttribute(
      "datetime",
      "2026-07-27T08:00:00Z",
    );
    expect(timeline).not.toHaveTextContent("body_text");
    expect(timeline).not.toHaveTextContent('"before"');
  });

  it("preserves backend chronology below JavaScript millisecond precision", async () => {
    const earlier: ActivityItem = {
      id: "message:z-earlier",
      type: "message",
      category: "public_reply",
      occurred_at: "2026-07-27T08:00:00.000001Z",
      actor: { subject: "agent-1", display_name: "Agent One" },
      visibility: "requester",
      payload: {
        body_text: "Earlier backend item",
        direction: "outbound",
        delivery_status: "sent",
      },
    };
    const later: ActivityItem = {
      id: "message:a-later",
      type: "message",
      category: "public_reply",
      occurred_at: "2026-07-27T08:00:00.000999Z",
      actor: { subject: "agent-2", display_name: "Supervisor Two" },
      visibility: "requester",
      payload: {
        body_text: "Later backend item",
        direction: "outbound",
        delivery_status: "sent",
      },
    };
    harness.activity.mockResolvedValue({ results: [earlier, later] });

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    const entries = within(
      await screen.findByRole("list", { name: "Ticket activity" }),
    ).getAllByRole("listitem");
    expect(entries.map((entry) => entry.textContent)).toEqual([
      expect.stringContaining("Earlier backend item"),
      expect.stringContaining("Later backend item"),
    ]);
  });

  it("accepts a custody event while preserving its server action", async () => {
    const custody: ActivityItem = {
      id: "custody:1",
      type: "custody_event",
      category: "custody",
      occurred_at: "2026-07-27T08:06:00Z",
      actor: { subject: "supervisor-1", display_name: "Supervisor One" },
      visibility: "internal",
      payload: { action: "reassigned" },
    };
    harness.activity.mockResolvedValue({ results: [custody] });

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    expect(await screen.findByText("Reassigned")).toBeVisible();
  });

  it("safely parses malformed custody records and string arrays", async () => {
    const custody: ActivityItem = {
      id: "custody:malformed",
      type: "custody_event",
      category: "custody",
      occurred_at: "2026-07-27T08:06:00Z",
      actor: null,
      visibility: "internal",
      payload: {
        action: ["reassigned"],
        previous_owner: "not-an-owner",
        new_owner: {
          id: "staff-safe",
          display_name: "Safe Owner",
          designations: ["Accountant", 42, ""],
          team_labels: [null, "Finance"],
        },
        previous_queue: [],
        new_queue: { id: "queue-finance", label: "Finance review" },
        actor_kind: "robot",
        source_process: { unsafe: true },
        reason: ["not text"],
      },
    };
    harness.activity.mockResolvedValue({ results: [custody] });

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    expect(await screen.findByText("Recorded")).toBeVisible();
    expect(
      screen.getByText("Owner: Unassigned → Safe Owner (Accountant · Finance)"),
    ).toBeVisible();
    expect(screen.getByText("Chain of custody")).toBeVisible();
    expect(screen.getByText("Queue: Not set → Finance review")).toBeVisible();
    expect(screen.queryByText(/unsafe/i)).not.toBeInTheDocument();
    expect(screen.queryByText("not text")).not.toBeInTheDocument();
  });

  it("shows a distinct loading state", () => {
    harness.activity.mockReturnValue(new Promise(() => undefined));

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    expect(
      screen.getByRole("status", { name: "Loading activity" }),
    ).toBeVisible();
  });

  it("shows a distinct empty state", async () => {
    harness.activity.mockResolvedValue({ results: [] });

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    expect(await screen.findByText("No activity yet")).toBeVisible();
    expect(
      screen.getByText("Messages and ticket changes will appear here."),
    ).toBeVisible();
  });

  it("explains a permission denial separately from an unexpected failure", async () => {
    harness.activity.mockRejectedValue(
      new ApiError(403, {
        code: "forbidden",
        detail: "Activity is outside your scope.",
        fields: {},
        correlation_id: "corr-activity-403",
      }),
    );

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    expect(await screen.findByText("Activity unavailable")).toBeVisible();
    expect(screen.getByText("Activity is outside your scope.")).toBeVisible();
    expect(screen.getByText(/corr-activity-403/)).toBeVisible();
    expect(
      screen.queryByText("Could not load activity"),
    ).not.toBeInTheDocument();
  });

  it("shows canonical context for an unexpected failure", async () => {
    harness.activity.mockRejectedValue(
      new ApiError(503, {
        code: "activity_unavailable",
        detail: "The activity service is temporarily unavailable.",
        fields: {},
        correlation_id: "corr-activity-503",
      }),
    );

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    expect(await screen.findByText("Could not load activity")).toBeVisible();
    expect(
      screen.getByText("The activity service is temporarily unavailable."),
    ).toBeVisible();
    expect(screen.getByText(/corr-activity-503/)).toBeVisible();
  });
});
