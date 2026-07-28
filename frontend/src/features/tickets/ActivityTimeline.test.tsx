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
    occurred_at: "2026-07-27T08:00:00.500Z",
    actor: { subject: "agent-2", display_name: "Supervisor Two" },
    visibility: "internal",
    payload: { body: "Internal investigation detail" },
  },
  {
    id: "transition:1",
    type: "status_transition",
    occurred_at: "2026-07-27T08:02:00Z",
    actor: { subject: "agent-1", display_name: "Agent One" },
    visibility: "internal",
    payload: { from: "triage", to: "in_progress", reason: "Started" },
  },
  {
    id: "audit:1",
    type: "work_state",
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

beforeEach(() => {
  harness.activity.mockReset();
});

describe("typed ticket activity", () => {
  it("renders every supported activity type oldest first without raw payloads", async () => {
    harness.activity.mockResolvedValue({ results: [...ITEMS].reverse() });

    renderWithProviders(<ActivityTimeline ticketNumber="MHC-2026-000001" />);

    const timeline = await screen.findByRole("list", {
      name: "Ticket activity",
    });
    const entries = within(timeline).getAllByRole("listitem");
    expect(entries).toHaveLength(6);
    expect(entries.map((entry) => entry.textContent)).toEqual([
      expect.stringContaining("Requester-visible update"),
      expect.stringContaining("Internal investigation detail"),
      expect.stringContaining("Triage to In progress"),
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
