import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configureApiAuth } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import AttachmentUploader from "./AttachmentUploader";

describe("AttachmentUploader", () => {
  let disposeAuth: () => void;

  beforeEach(() => {
    disposeAuth = configureApiAuth({
      getAccessToken: vi.fn().mockResolvedValue("production-token"),
      refresh: vi.fn().mockResolvedValue(true),
      login: vi.fn().mockResolvedValue(undefined),
    });
  });

  afterEach(() => {
    disposeAuth();
  });

  it("submits selected files through the authenticated attachment helper", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          results: [
            {
              id: "attachment-1",
              filename: "proof.txt",
              size_bytes: 5,
              scan_status: "pending",
              scan_signature: "",
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    renderWithProviders(<AttachmentUploader ticketNumber="MHC-9" />);
    const file = new File(["proof"], "proof.txt", { type: "text/plain" });

    await user.upload(screen.getByLabelText("Choose files"), file);
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(
      await screen.findByRole("list", { name: "Attachment scan results" }),
    ).toHaveTextContent("proof.txt");
    expect(fetchMock).toHaveBeenCalledOnce();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer production-token");
    expect(headers.has("Content-Type")).toBe(false);
    expect(init.body).toBeInstanceOf(FormData);
  });
});
