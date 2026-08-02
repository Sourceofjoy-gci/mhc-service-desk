import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TicketDetail } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { SlaClocks } from "./SlaClocks";

type Clocks = TicketDetail["sla_clocks"];

describe("server-provided SLA clocks", () => {
  it("renders labels, semantic states, due timestamps, and server durations", () => {
    const clocks: Clocks = {
      first_response: {
        state: "running",
        due_at: "2026-07-28T10:30:00Z",
        remaining_seconds: 5400,
        overdue_seconds: 0,
      },
      resolution: {
        state: "breached",
        due_at: "2026-07-27T08:00:00Z",
        remaining_seconds: 0,
        overdue_seconds: 9000,
      },
    };
    renderWithProviders(<SlaClocks clocks={clocks} />);

    const firstResponse = screen.getByRole("listitem", {
      name: "First response SLA: running",
    });
    expect(within(firstResponse).getByText("First response")).toBeVisible();
    expect(within(firstResponse).getByText("Running")).toBeVisible();
    expect(
      within(firstResponse).getByText("1 hour 30 minutes remaining"),
    ).toBeVisible();
    expect(within(firstResponse).getByText(/^Due /)).toHaveAttribute(
      "datetime",
      "2026-07-28T10:30:00Z",
    );

    const resolution = screen.getByRole("listitem", {
      name: "Resolution SLA: breached",
    });
    expect(within(resolution).getByText("Breached")).toBeVisible();
    expect(
      within(resolution).getByText("2 hours 30 minutes overdue"),
    ).toBeVisible();
    expect(resolution).toHaveClass("text-destructive");
  });

  it("uses a warning state for paused clocks without inventing a due time", () => {
    const clocks: Clocks = {
      first_response: {
        state: "met",
        due_at: null,
        remaining_seconds: 0,
        overdue_seconds: 0,
      },
      resolution: {
        state: "paused",
        due_at: null,
        remaining_seconds: 1800,
        overdue_seconds: 0,
      },
    };
    renderWithProviders(<SlaClocks clocks={clocks} />);

    const paused = screen.getByRole("listitem", {
      name: "Resolution SLA: paused",
    });
    expect(within(paused).getByText("Paused")).toBeVisible();
    expect(within(paused).getByText("30 minutes remaining")).toBeVisible();
    expect(paused).toHaveClass("text-warning-foreground");
    expect(within(paused).queryByText(/^Due /)).not.toBeInTheDocument();
  });
});
