import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  type AttachmentMetadata,
  type AttachmentUploadResponse,
} from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import AttachmentUploader, {
  attachmentDownloadNavigation,
} from "./AttachmentUploader";

const harness = vi.hoisted(() => ({
  list: vi.fn(),
  upload: vi.fn(),
  download: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    attachmentsApi: {
      list: harness.list,
      upload: harness.upload,
      download: harness.download,
    },
  };
});

const TICKET_NUMBER = "MHC-2026-000009";

const ATTACHMENTS: AttachmentMetadata[] = [
  {
    id: "attachment-clean",
    filename: "evidence.pdf",
    size_bytes: 2048,
    content_type: "application/pdf",
    uploaded_by: "A. Clerk",
    uploaded_at: "2026-07-27T08:15:00Z",
    scan_status: "clean",
    download_available: true,
  },
  {
    id: "attachment-infected",
    filename: "unsafe.exe",
    size_bytes: 1024,
    content_type: "application/x-msdownload",
    uploaded_by: "Security Desk",
    uploaded_at: "2026-07-27T08:16:00Z",
    scan_status: "infected",
    download_available: false,
  },
  {
    id: "attachment-error",
    filename: "unreadable.zip",
    size_bytes: 512,
    content_type: "application/zip",
    uploaded_by: "A. Clerk",
    uploaded_at: "2026-07-27T08:17:00Z",
    scan_status: "error",
    download_available: false,
  },
  {
    id: "attachment-pending",
    filename: "new-proof.txt",
    size_bytes: 5,
    content_type: "text/plain",
    uploaded_by: "A. Clerk",
    uploaded_at: "2026-07-27T08:18:00Z",
    scan_status: "pending",
    download_available: false,
  },
];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  harness.list.mockReset();
  harness.upload.mockReset();
  harness.download.mockReset();
  harness.list.mockResolvedValue({ results: [] });
});

describe("AttachmentUploader", () => {
  it("loads canonical file metadata independently of uploads and labels scan safety", async () => {
    harness.list.mockResolvedValue({ results: ATTACHMENTS });

    renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);

    const list = await screen.findByRole("list", {
      name: "Ticket attachments",
    });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(4);

    const clean = within(rows[0]);
    expect(clean.getByText("evidence.pdf")).toBeVisible();
    expect(clean.getByText("2 KB")).toBeVisible();
    expect(clean.getByText("application/pdf")).toBeVisible();
    expect(clean.getByText("A. Clerk")).toBeVisible();
    expect(clean.getByText("27 Jul 2026, 10:15")).toBeVisible();
    expect(clean.getByText("Ready")).toBeVisible();
    expect(clean.getByRole("time")).toHaveAttribute(
      "datetime",
      "2026-07-27T08:15:00Z",
    );

    expect(within(rows[1]).getByText("Quarantined")).toBeVisible();
    expect(within(rows[2]).getByText("Scan failed")).toBeVisible();
    expect(within(rows[3]).getByText("Scanning")).toBeVisible();
    expect(screen.getAllByRole("button", { name: /^Download / })).toHaveLength(
      1,
    );
    expect(
      screen.getByRole("button", { name: "Download evidence.pdf" }),
    ).toBeEnabled();
    expect(harness.list).toHaveBeenCalledWith(TICKET_NUMBER);
    expect(screen.queryByText(/dev token/i)).not.toBeInTheDocument();
  });

  it("exposes an accessible loading state", () => {
    harness.list.mockReturnValue(new Promise(() => undefined));

    renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);

    expect(
      screen.getByRole("status", { name: "Loading attachments" }),
    ).toBeVisible();
  });

  it("renders a permission state for denied metadata without token guidance", async () => {
    harness.list.mockRejectedValue(
      new ApiError(403, {
        code: "permission_denied",
        detail: "You cannot view attachments for this ticket.",
        fields: {},
        correlation_id: "corr-files-403",
      }),
    );

    renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Attachments unavailable")).toBeVisible();
    expect(alert).toHaveTextContent(
      "You cannot view attachments for this ticket.",
    );
    expect(alert).toHaveTextContent("corr-files-403");
    expect(alert).not.toHaveTextContent(/token/i);
  });

  it("keeps selected files and restores upload controls after a failure", async () => {
    harness.upload.mockRejectedValue(
      new ApiError(503, {
        code: "scan_unavailable",
        detail: "The file scanner is temporarily unavailable.",
        fields: {},
        correlation_id: "corr-upload-503",
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);
    const input = screen.getByLabelText("Choose files") as HTMLInputElement;
    const file = new File(["proof"], "proof.txt", { type: "text/plain" });

    await user.upload(input, file);
    await user.click(screen.getByRole("button", { name: "Upload" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Upload failed");
    expect(alert).toHaveTextContent(
      "The file scanner is temporarily unavailable.",
    );
    expect(alert).toHaveTextContent("corr-upload-503");
    expect(
      screen.getByRole("list", { name: "Selected files" }),
    ).toHaveTextContent("proof.txt");
    expect(input.files).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
  });

  it("clears selection only after success and reloads attachments and activity", async () => {
    const uploaded = ATTACHMENTS[3];
    harness.list
      .mockResolvedValueOnce({ results: [] })
      .mockResolvedValueOnce({ results: [uploaded] });
    harness.upload.mockResolvedValue({
      results: [{ ...uploaded, scan_signature: "" }],
    } satisfies AttachmentUploadResponse);
    const user = userEvent.setup();
    const { queryClient } = renderWithProviders(
      <AttachmentUploader ticketNumber={TICKET_NUMBER} />,
    );
    queryClient.setQueryData(["ticket-activity", TICKET_NUMBER], {
      results: [{ id: "existing-activity" }],
    });
    const input = screen.getByLabelText("Choose files") as HTMLInputElement;
    const file = new File(["proof"], "new-proof.txt", {
      type: "text/plain",
    });

    await screen.findByText("No attachments yet");
    await user.upload(input, file);
    await user.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText("new-proof.txt")).toBeVisible();
    expect(harness.upload).toHaveBeenCalledWith(TICKET_NUMBER, [file]);
    expect(harness.list).toHaveBeenCalledTimes(2);
    expect(
      queryClient.getQueryState(["ticket-activity", TICKET_NUMBER])
        ?.isInvalidated,
    ).toBe(true);
    expect(
      (screen.getByLabelText("Choose files") as HTMLInputElement).files,
    ).toHaveLength(0);
    expect(
      screen.queryByRole("list", { name: "Selected files" }),
    ).not.toBeInTheDocument();
  });

  it("blocks duplicate upload submissions before React rerenders", async () => {
    const pending = deferred<AttachmentUploadResponse>();
    harness.upload.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);
    const file = new File(["proof"], "proof.txt", { type: "text/plain" });

    await user.upload(screen.getByLabelText("Choose files"), file);
    const uploadButton = screen.getByRole("button", { name: "Upload" });
    fireEvent.click(uploadButton);
    fireEvent.click(uploadButton);

    await waitFor(() => expect(harness.upload).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByRole("button", { name: "Uploading…" }),
    ).toBeDisabled();

    pending.resolve({ results: [] });
  });

  it("requests a signed URL only on an allowed click and blocks duplicate downloads", async () => {
    harness.list.mockResolvedValue({ results: [ATTACHMENTS[0]] });
    const pending = deferred<{
      url: string;
      filename: string;
      expires_in: number;
    }>();
    harness.download.mockReturnValue(pending.promise);
    renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);
    const button = await screen.findByRole("button", {
      name: "Download evidence.pdf",
    });

    expect(harness.download).not.toHaveBeenCalled();
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(harness.download).toHaveBeenCalledTimes(1));
    expect(harness.download).toHaveBeenCalledWith("attachment-clean");
    expect(
      await screen.findByRole("button", { name: "Preparing evidence.pdf…" }),
    ).toBeDisabled();

    const assign = vi
      .spyOn(attachmentDownloadNavigation, "assign")
      .mockImplementation(() => undefined);
    try {
      pending.resolve({
        url: "https://files.example.test/signed/evidence.pdf",
        filename: "evidence.pdf",
        expires_in: 60,
      });
      await waitFor(() =>
        expect(assign).toHaveBeenCalledWith(
          "https://files.example.test/signed/evidence.pdf",
        ),
      );
    } finally {
      assign.mockRestore();
    }
  });

  it("explains a denied download as a permission failure", async () => {
    harness.list.mockResolvedValue({ results: [ATTACHMENTS[0]] });
    harness.download.mockRejectedValue(
      new ApiError(403, {
        code: "permission_denied",
        detail: "You cannot download this attachment.",
        fields: {},
        correlation_id: "corr-download-403",
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);

    await user.click(
      await screen.findByRole("button", { name: "Download evidence.pdf" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Download unavailable");
    expect(alert).toHaveTextContent("You cannot download this attachment.");
    expect(alert).toHaveTextContent("corr-download-403");
    expect(alert).not.toHaveTextContent(/token/i);
  });
});
