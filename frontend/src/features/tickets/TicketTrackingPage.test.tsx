import { beforeEach, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import {
  ApiError,
  type TicketTrackingResult,
} from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import TicketTrackingPage from "./TicketTrackingPage";

const harness = vi.hoisted(() => ({ track: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: { ...original.ticketsApi, track: harness.track },
  };
});

const TRACKING_RESULT: TicketTrackingResult = {
  reference: "O00123",
  title: "Estate status enquiry",
  tracking_status: "In Progress",
  status_updated_at: "2026-08-02T10:15:00Z",
  created_at: "2026-08-02T09:00:00Z",
  updated_at: "2026-08-02T10:15:00Z",
  office: "Mbabane (Main)",
  service: "Estate registration or reference",
  progress: [
    { status: "Submitted", occurred_at: "2026-08-02T09:00:00Z" },
    { status: "In Progress", occurred_at: "2026-08-02T10:15:00Z" },
  ],
};

function LocationProbe() {
  return <output data-testid="ticket-location">{useLocation().pathname}</output>;
}

function renderTracking(route: string) {
  return renderWithProviders(
    <Routes>
      <Route path="/ticket-tracking" element={<TicketTrackingPage />} />
      <Route path="/tickets/:number" element={<LocationProbe />} />
    </Routes>,
    { route },
  );
}

beforeEach(() => {
  harness.track.mockReset();
});

it("tracks a normalised reference once and renders safe progress", async () => {
  harness.track.mockResolvedValue(TRACKING_RESULT);
  const user = userEvent.setup();
  renderTracking("/ticket-tracking");

  await user.type(
    screen.getByLabelText("Reference number"),
    " o00123 ",
  );
  await user.click(screen.getByRole("button", { name: "Track ticket" }));

  await screen.findByRole("heading", { name: "Estate status enquiry" });
  expect(harness.track).toHaveBeenCalledOnce();
  expect(harness.track).toHaveBeenCalledWith("O00123");
  expect(screen.getAllByText("In Progress")[0]).toBeVisible();
  expect(
    screen.getByRole("list", { name: "Ticket progress" }),
  ).toHaveTextContent("Submitted");
  expect(screen.queryByText(/internal note/i)).not.toBeInTheDocument();
});

it("rejects an invalid local reference without calling the API and focuses input", async () => {
  const user = userEvent.setup();
  renderTracking("/ticket-tracking");
  const input = screen.getByLabelText("Reference number");

  await user.type(input, "not-a-reference");
  await user.click(screen.getByRole("button", { name: "Track ticket" }));

  expect(harness.track).not.toHaveBeenCalled();
  expect(input).toHaveFocus();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Enter a valid ticket reference",
  );
});

it("blocks duplicate submissions while a lookup is pending", async () => {
  harness.track.mockImplementation(() => new Promise(() => undefined));
  const user = userEvent.setup();
  renderTracking("/ticket-tracking");
  await user.type(
    screen.getByLabelText("Reference number"),
    "O00123",
  );
  const submit = screen.getByRole("button", { name: "Track ticket" });

  await user.click(submit);
  submit.removeAttribute("disabled");
  await user.click(submit);

  expect(harness.track).toHaveBeenCalledOnce();
});

it("loads one valid reference supplied in the query string", async () => {
  harness.track.mockResolvedValue(TRACKING_RESULT);

  renderTracking("/ticket-tracking?reference=o00123");

  await screen.findByRole("heading", { name: "Estate status enquiry" });
  expect(harness.track).toHaveBeenCalledOnce();
  expect(harness.track).toHaveBeenCalledWith("O00123");
});

it("hides a loaded ticket when the reference input no longer matches it", async () => {
  harness.track.mockResolvedValue(TRACKING_RESULT);
  const user = userEvent.setup();
  renderTracking("/ticket-tracking?reference=O00123");

  await screen.findByRole("heading", { name: "Estate status enquiry" });
  const input = screen.getByLabelText("Reference number");
  await user.clear(input);
  await user.type(input, "not-a-reference");

  expect(
    screen.queryByRole("heading", { name: "Estate status enquiry" }),
  ).not.toBeInTheDocument();
});

it("conceals whether a missing ticket is outside the staff member's access", async () => {
  harness.track.mockRejectedValue(
    new ApiError(404, {
      code: "not_found",
      detail: "Ticket not found.",
      fields: {},
      correlation_id: "hidden-ticket",
    }),
  );

  renderTracking("/ticket-tracking?reference=O00123");

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "could not be found or is outside your access",
  );
});

it("shows the correlation reference for an unexpected structured error", async () => {
  harness.track.mockRejectedValue(
    new ApiError(500, {
      code: "server_error",
      detail: "Unexpected failure.",
      fields: {},
      correlation_id: "track-correlation-123",
    }),
  );

  renderTracking("/ticket-tracking?reference=O00123");

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "track-correlation-123",
  );
});

it("encodes the returned reference in the full-ticket link", async () => {
  harness.track.mockResolvedValue({
    ...TRACKING_RESULT,
    reference: "O00123/EXTRA",
  });

  renderTracking("/ticket-tracking?reference=O00123");

  const link = await screen.findByRole("link", { name: "Open full ticket" });
  expect(link).toHaveAttribute(
    "href",
    "/tickets/O00123%2FEXTRA",
  );
  await waitFor(() => expect(harness.track).toHaveBeenCalledOnce());
});
