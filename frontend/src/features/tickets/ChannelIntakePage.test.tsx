import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import ChannelIntakePage from "./ChannelIntakePage";

const harness = vi.hoisted(() => ({
  publicIntake: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      publicIntake: harness.publicIntake,
    },
  };
});

beforeEach(() => {
  harness.publicIntake.mockReset();
});

describe("staff-assisted intake form", () => {
  it("offers every supported Master's Office location and submits its code", async () => {
    const user = userEvent.setup();
    harness.publicIntake.mockResolvedValue({
      ticket_number: "O00123",
      domain: "operational",
      title: "Hours",
      priority: "P3",
      message: "Your request has been received.",
    });
    renderWithProviders(
      <ChannelIntakePage
        channel="call"
        title="Call-centre capture"
        description="Capture a call-centre enquiry on behalf of a requester."
      />,
      { route: "/intake/call" },
    );

    await user.click(screen.getByLabelText("Office"));

    expect(
      screen.getAllByRole("option").map((option) => option.textContent),
    ).toEqual([
      "Mbabane (Main)",
      "Manzini",
      "Lobamba",
      "Hlathikhulu",
      "Nhlangano",
      "Siteki",
      "Siphofaneni",
      "Simunye",
      "Pigg's Peak",
    ]);

    await user.click(screen.getByRole("option", { name: "Pigg's Peak" }));
    await user.type(screen.getByRole("textbox", { name: /title/i }), "Hours");
    await user.type(
      screen.getByRole("textbox", { name: /description/i }),
      "Confirm office hours",
    );
    await user.type(
      screen.getByRole("textbox", { name: /requester name/i }),
      "Lindiwe Dlamini",
    );
    await user.click(screen.getByRole("button", { name: "Capture ticket" }));

    await waitFor(() =>
      expect(harness.publicIntake).toHaveBeenCalledWith(
        expect.objectContaining({ office_code: "MHC-PIG" }),
      ),
    );
  });

  it("shows, copies, and links the immutable reference after capture", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    harness.publicIntake.mockResolvedValue({
      ticket_number: "O00123",
      domain: "operational",
      title: "Hours",
      priority: "P3",
      message: "Your request has been received.",
    });
    renderWithProviders(
      <ChannelIntakePage
        channel="call"
        title="Call-centre capture"
        description="Capture a call-centre enquiry on behalf of a requester."
      />,
      { route: "/intake/call" },
    );

    await user.type(screen.getByRole("textbox", { name: /title/i }), "Hours");
    await user.type(
      screen.getByRole("textbox", { name: /description/i }),
      "Confirm office hours",
    );
    await user.type(
      screen.getByRole("textbox", { name: /requester name/i }),
      "Lindiwe Dlamini",
    );
    await user.click(screen.getByRole("button", { name: "Capture ticket" }));

    expect(await screen.findByText("Reference number")).toBeVisible();
    expect(screen.getByText("O00123")).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Track this ticket" }),
    ).toHaveAttribute(
      "href",
      "/ticket-tracking?reference=O00123",
    );
    await user.click(screen.getByRole("button", { name: "Copy reference" }));
    expect(writeText).toHaveBeenCalledWith("O00123");
  });

  it("groups the workflow and explains every required validation error", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <ChannelIntakePage
        channel="call"
        title="Call-centre capture"
        description="Capture a call-centre enquiry on behalf of a requester."
      />,
      { route: "/intake/call" },
    );

    expect(
      screen.getByRole("group", { name: "Service details" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Request details" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Requester details" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Capture ticket" }));

    expect(screen.getByText("Enter a short title.")).toBeVisible();
    expect(screen.getByText("Describe what the requester needs.")).toBeVisible();
    expect(screen.getByText("Enter the requester name.")).toBeVisible();
    expect(screen.getByRole("textbox", { name: /title/i })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(harness.publicIntake).not.toHaveBeenCalled();
  });

  it("uses inline validation, rejects whitespace, and focuses the first invalid field", async () => {
    const user = userEvent.setup();
    harness.publicIntake.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(
      <ChannelIntakePage
        channel="call"
        title="Call-centre capture"
        description="Capture a call-centre enquiry on behalf of a requester."
      />,
      { route: "/intake/call" },
    );

    const title = screen.getByRole("textbox", { name: /title/i });
    const description = screen.getByRole("textbox", { name: /description/i });
    const requesterName = screen.getByRole("textbox", {
      name: /requester name/i,
    });
    const email = screen.getByRole("textbox", { name: /email/i });
    const submitButton = screen.getByRole("button", {
      name: "Capture ticket",
    });

    expect(submitButton.closest("form")).toHaveAttribute("novalidate");

    await user.type(title, "   ");
    await user.type(description, "   ");
    await user.type(requesterName, "   ");
    await user.type(email, "not-an-email");
    await user.click(submitButton);

    expect(screen.getByText("Enter a short title.")).toBeVisible();
    expect(screen.getByText("Describe what the requester needs.")).toBeVisible();
    expect(screen.getByText("Enter the requester name.")).toBeVisible();
    expect(screen.getByText("Enter a valid email address.")).toBeVisible();
    expect(email).toHaveAttribute(
      "aria-describedby",
      "intake-requester-email-error",
    );
    expect(screen.getByText("Enter a valid email address.")).toHaveAttribute(
      "id",
      "intake-requester-email-error",
    );
    expect(title).toHaveFocus();
    expect(title).toHaveValue("   ");
    expect(harness.publicIntake).not.toHaveBeenCalled();
  });

  it("locks a valid capture synchronously and keeps its button name stable", async () => {
    const user = userEvent.setup();
    harness.publicIntake.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(
      <ChannelIntakePage
        channel="call"
        title="Call-centre capture"
        description="Capture a call-centre enquiry on behalf of a requester."
      />,
      { route: "/intake/call" },
    );

    await user.type(screen.getByRole("textbox", { name: /title/i }), "Hours");
    await user.type(
      screen.getByRole("textbox", { name: /description/i }),
      "Confirm office hours",
    );
    await user.type(
      screen.getByRole("textbox", { name: /requester name/i }),
      "Lindiwe Dlamini",
    );
    const submitButton = screen.getByRole("button", {
      name: "Capture ticket",
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

    await waitFor(() => expect(harness.publicIntake).toHaveBeenCalledTimes(1));
    expect(
      screen.getByRole("button", { name: "Capture ticket" }),
    ).toBeDisabled();
  });
});
