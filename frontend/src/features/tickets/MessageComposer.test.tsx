import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import { MessageComposer } from "./MessageComposer";

const harness = vi.hoisted(() => ({
  addMessage: vi.fn(),
  addNote: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      addMessage: harness.addMessage,
      addNote: harness.addNote,
    },
  };
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  harness.addMessage.mockReset();
  harness.addNote.mockReset();
});

describe("reply and internal-note composition", () => {
  it("keeps distinct drafts and prevents either empty body from submitting", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <MessageComposer ticketNumber="MHC-2026-000001" onCreated={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "Send reply" })).toBeDisabled();
    expect(
      screen.getByRole("textbox", { name: "Reply message" }),
    ).toHaveAccessibleDescription("This message is visible to the requester.");
    await user.type(
      screen.getByRole("textbox", { name: "Reply message" }),
      "Requester update",
    );

    await user.click(screen.getByRole("tab", { name: "Internal note" }));
    expect(
      screen.getByText("Internal notes are not visible to the requester."),
    ).toBeVisible();
    expect(
      screen.getByRole("textbox", { name: "Internal note" }),
    ).toHaveAccessibleDescription(
      "Internal notes are not visible to the requester.",
    );
    expect(
      screen.getByRole("button", { name: "Add internal note" }),
    ).toBeDisabled();
    await user.type(
      screen.getByRole("textbox", { name: "Internal note" }),
      "Investigation draft",
    );

    await user.click(screen.getByRole("tab", { name: "Reply" }));
    expect(screen.getByRole("textbox", { name: "Reply message" })).toHaveValue(
      "Requester update",
    );
    await user.click(screen.getByRole("tab", { name: "Internal note" }));
    expect(screen.getByRole("textbox", { name: "Internal note" })).toHaveValue(
      "Investigation draft",
    );
    expect(harness.addMessage).not.toHaveBeenCalled();
    expect(harness.addNote).not.toHaveBeenCalled();
  });

  it("blocks duplicate replies and does not update the timeline optimistically", async () => {
    const pending = deferred<{ id: string }>();
    harness.addMessage.mockReturnValue(pending.promise);
    const onCreated = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <MessageComposer ticketNumber="MHC-2026-000001" onCreated={onCreated} />,
    );

    await user.type(
      screen.getByRole("textbox", { name: "Reply message" }),
      "A single reply",
    );
    const submit = screen.getByRole("button", { name: "Send reply" });
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(harness.addMessage).toHaveBeenCalledTimes(1));
    expect(harness.addMessage).toHaveBeenCalledWith(
      "MHC-2026-000001",
      "A single reply",
    );
    expect(onCreated).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send reply" })).toBeDisabled();
    expect(
      screen.getByRole("textbox", { name: "Reply message" }),
    ).toBeDisabled();

    pending.resolve({ id: "message-1" });
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
  });

  it("awaits timeline refresh before clearing only the submitted reply", async () => {
    harness.addMessage.mockResolvedValue({ id: "message-1" });
    const refreshed = deferred<void>();
    const onCreated = vi.fn(() => refreshed.promise);
    const user = userEvent.setup();
    renderWithProviders(
      <MessageComposer ticketNumber="MHC-2026-000001" onCreated={onCreated} />,
    );

    await user.type(
      screen.getByRole("textbox", { name: "Reply message" }),
      "Ready for requester",
    );
    await user.click(screen.getByRole("tab", { name: "Internal note" }));
    await user.type(
      screen.getByRole("textbox", { name: "Internal note" }),
      "Keep this internal draft",
    );
    await user.click(screen.getByRole("tab", { name: "Reply" }));
    await user.click(screen.getByRole("button", { name: "Send reply" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("textbox", { name: "Reply message" })).toHaveValue(
      "Ready for requester",
    );
    expect(screen.getByRole("button", { name: "Send reply" })).toBeDisabled();

    refreshed.resolve();
    await waitFor(() =>
      expect(
        screen.getByRole("textbox", { name: "Reply message" }),
      ).toHaveValue(""),
    );
    await user.click(screen.getByRole("tab", { name: "Internal note" }));
    expect(screen.getByRole("textbox", { name: "Internal note" })).toHaveValue(
      "Keep this internal draft",
    );
  });

  it("clears a successful reply whose body includes surrounding whitespace", async () => {
    harness.addMessage.mockResolvedValue({ id: "message-1" });
    const user = userEvent.setup();
    renderWithProviders(
      <MessageComposer ticketNumber="MHC-2026-000001" onCreated={vi.fn()} />,
    );

    const reply = screen.getByRole("textbox", { name: "Reply message" });
    await user.type(reply, "  Reply with intentional spacing  ");
    await user.click(screen.getByRole("button", { name: "Send reply" }));

    await waitFor(() => expect(reply).toHaveValue(""));
  });

  it("preserves an internal note and shows canonical error context", async () => {
    harness.addNote.mockRejectedValue(
      new ApiError(400, {
        code: "invalid_note",
        detail: "The internal note could not be saved.",
        fields: { body: ["The note contains unsupported content."] },
        correlation_id: "corr-note-400",
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(
      <MessageComposer ticketNumber="MHC-2026-000001" onCreated={vi.fn()} />,
    );

    await user.click(screen.getByRole("tab", { name: "Internal note" }));
    const note = screen.getByRole("textbox", { name: "Internal note" });
    await user.type(note, "Sensitive investigation detail");
    await user.click(screen.getByRole("button", { name: "Add internal note" }));

    expect(
      await screen.findByText("Could not save internal note"),
    ).toBeVisible();
    expect(
      screen.getByText("The internal note could not be saved."),
    ).toBeVisible();
    expect(
      screen.getByText("The note contains unsupported content."),
    ).toBeVisible();
    expect(screen.getByText("Reference: corr-note-400")).toBeVisible();
    expect(note).toHaveValue("Sensitive investigation detail");
    expect(harness.addNote).toHaveBeenCalledWith(
      "MHC-2026-000001",
      "Sensitive investigation detail",
    );
    expect(harness.addMessage).not.toHaveBeenCalled();
  });
});
