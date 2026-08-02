import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import PublicFormPage from "./PublicFormPage";

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

describe("public intake form structure", () => {
  it("keeps entered fields visible and explains missing required values", async () => {
    const user = userEvent.setup();
    renderWithProviders(<PublicFormPage />, { route: "/public" });

    await user.click(screen.getByRole("button", { name: "Submit request" }));

    expect(screen.getByText("Enter a short title.")).toBeVisible();
    expect(screen.getByText("Describe the request.")).toBeVisible();
    expect(screen.getByText("Enter your name.")).toBeVisible();
    expect(screen.getByText("Consent is required.")).toBeVisible();
    expect(screen.getByRole("textbox", { name: /title/i })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(harness.publicIntake).not.toHaveBeenCalled();
  });

  it("uses inline validation, rejects whitespace, and preserves entered values", async () => {
    const user = userEvent.setup();
    harness.publicIntake.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<PublicFormPage />, { route: "/public" });

    const title = screen.getByRole("textbox", { name: /title/i });
    const description = screen.getByRole("textbox", {
      name: /describe your request/i,
    });
    const requesterName = screen.getByRole("textbox", { name: /your name/i });
    const email = screen.getByRole("textbox", { name: /email/i });
    const consent = screen.getByRole("checkbox", { name: /i consent/i });
    const submitButton = screen.getByRole("button", {
      name: "Submit request",
    });

    expect(submitButton.closest("form")).toHaveAttribute("novalidate");

    await user.type(title, "   ");
    await user.type(description, "   ");
    await user.type(requesterName, "   ");
    await user.type(email, "not-an-email");
    await user.click(consent);
    await user.click(submitButton);

    expect(screen.getByText("Enter a short title.")).toBeVisible();
    expect(screen.getByText("Describe the request.")).toBeVisible();
    expect(screen.getByText("Enter your name.")).toBeVisible();
    expect(screen.getByText("Enter a valid email address.")).toBeVisible();
    expect(email).toHaveAttribute("aria-describedby", "public-email-error");
    expect(screen.getByText("Enter a valid email address.")).toHaveAttribute(
      "id",
      "public-email-error",
    );
    expect(title).toHaveFocus();
    expect(title).toHaveValue("   ");
    expect(harness.publicIntake).not.toHaveBeenCalled();
  });

  it("locks a valid submission synchronously and keeps its button name stable", async () => {
    const user = userEvent.setup();
    harness.publicIntake.mockImplementation(() => new Promise(() => {}));
    renderWithProviders(<PublicFormPage />, { route: "/public" });

    await user.type(screen.getByRole("textbox", { name: /title/i }), "Hours");
    await user.type(
      screen.getByRole("textbox", { name: /describe your request/i }),
      "Confirm office hours",
    );
    await user.type(
      screen.getByRole("textbox", { name: /your name/i }),
      "Lindiwe Dlamini",
    );
    await user.click(screen.getByRole("checkbox", { name: /i consent/i }));
    const submitButton = screen.getByRole("button", {
      name: "Submit request",
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
      screen.getByRole("button", { name: "Submit request" }),
    ).toBeDisabled();
  });
});
