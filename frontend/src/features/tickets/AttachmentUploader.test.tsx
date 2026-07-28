import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  type AttachmentDownload,
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

const SECOND_CLEAN_ATTACHMENT: AttachmentMetadata = {
  id: "attachment-clean-2",
  filename: "transcript.docx",
  size_bytes: 4096,
  content_type:
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  uploaded_by: "B. Registrar",
  uploaded_at: "2026-07-27T08:19:00Z",
  scan_status: "clean",
  download_available: true,
};

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
    harness.upload
      .mockRejectedValueOnce(
        new ApiError(503, {
          code: "scan_unavailable",
          detail: "The file scanner is temporarily unavailable.",
          fields: {},
          correlation_id: "corr-upload-503",
        }),
      )
      .mockResolvedValueOnce({ results: [] });
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

    await user.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(harness.upload).toHaveBeenCalledTimes(2));
    expect(harness.upload).toHaveBeenNthCalledWith(2, TICKET_NUMBER, [file]);
    await waitFor(() =>
      expect(
        screen.queryByRole("list", { name: "Selected files" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("releases the upload lock after success for a new explicit upload", async () => {
    harness.upload.mockResolvedValue({ results: [] });
    const user = userEvent.setup();
    renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);
    const first = new File(["first"], "first.txt", { type: "text/plain" });
    const second = new File(["second"], "second.txt", {
      type: "text/plain",
    });

    await screen.findByText("No attachments yet");
    await user.upload(screen.getByLabelText("Choose files"), first);
    await user.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(harness.upload).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByLabelText("Choose files")).toBeEnabled(),
    );
    await user.upload(screen.getByLabelText("Choose files"), second);
    await user.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(harness.upload).toHaveBeenCalledTimes(2));
    expect(harness.upload).toHaveBeenNthCalledWith(2, TICKET_NUMBER, [second]);
  });

  it("fails closed when unsafe scan metadata claims a download is available", async () => {
    harness.list.mockResolvedValue({
      results: ATTACHMENTS.slice(1).map((attachment) => ({
        ...attachment,
        download_available: true,
      })),
    });

    renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);

    const list = await screen.findByRole("list", {
      name: "Ticket attachments",
    });
    expect(within(list).getByText("Quarantined")).toBeVisible();
    expect(within(list).getByText("Scan failed")).toBeVisible();
    expect(within(list).getByText("Scanning")).toBeVisible();
    expect(
      within(list).queryAllByRole("button", { name: /^Download / }),
    ).toHaveLength(0);
    expect(harness.download).not.toHaveBeenCalled();
  });

  it("prepares different clean attachments concurrently", async () => {
    harness.list.mockResolvedValue({
      results: [ATTACHMENTS[0], SECOND_CLEAN_ATTACHMENT],
    });
    const first = deferred<AttachmentDownload>();
    const second = deferred<AttachmentDownload>();
    harness.download.mockImplementation((id: string) =>
      id === ATTACHMENTS[0].id ? first.promise : second.promise,
    );
    const assign = vi
      .spyOn(attachmentDownloadNavigation, "assign")
      .mockImplementation(() => undefined);
    try {
      renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);
      const evidence = await screen.findByRole("button", {
        name: "Download evidence.pdf",
      });
      const transcript = screen.getByRole("button", {
        name: "Download transcript.docx",
      });

      fireEvent.click(evidence);
      fireEvent.click(transcript);

      await waitFor(() => expect(harness.download).toHaveBeenCalledTimes(2));
      expect(harness.download).toHaveBeenCalledWith("attachment-clean");
      expect(harness.download).toHaveBeenCalledWith("attachment-clean-2");
      expect(
        await screen.findByRole("button", {
          name: "Preparing evidence.pdf…",
        }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Preparing transcript.docx…" }),
      ).toBeDisabled();

      first.resolve({
        url: "https://files.example.test/signed/evidence.pdf",
        filename: "evidence.pdf",
        expires_in: 60,
      });
      second.resolve({
        url: "https://files.example.test/signed/transcript.docx",
        filename: "transcript.docx",
        expires_in: 60,
      });
      await waitFor(() => expect(assign).toHaveBeenCalledTimes(2));
    } finally {
      assign.mockRestore();
    }
  });

  it("releases a download lock after success so the same file can be retried", async () => {
    harness.list.mockResolvedValue({ results: [ATTACHMENTS[0]] });
    harness.download
      .mockResolvedValueOnce({
        url: "https://files.example.test/signed/evidence-1.pdf",
        filename: "evidence.pdf",
        expires_in: 60,
      })
      .mockResolvedValueOnce({
        url: "https://files.example.test/signed/evidence-2.pdf",
        filename: "evidence.pdf",
        expires_in: 60,
      });
    const assign = vi
      .spyOn(attachmentDownloadNavigation, "assign")
      .mockImplementation(() => undefined);
    const user = userEvent.setup();
    try {
      renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);

      await user.click(
        await screen.findByRole("button", { name: "Download evidence.pdf" }),
      );
      await waitFor(() => expect(assign).toHaveBeenCalledTimes(1));
      await user.click(
        await screen.findByRole("button", { name: "Download evidence.pdf" }),
      );

      await waitFor(() => expect(harness.download).toHaveBeenCalledTimes(2));
      await waitFor(() =>
        expect(assign).toHaveBeenNthCalledWith(
          2,
          "https://files.example.test/signed/evidence-2.pdf",
        ),
      );
    } finally {
      assign.mockRestore();
    }
  });

  it("releases a download lock after failure so the same file can be retried", async () => {
    harness.list.mockResolvedValue({ results: [ATTACHMENTS[0]] });
    harness.download
      .mockRejectedValueOnce(
        new ApiError(503, {
          code: "download_unavailable",
          detail: "The signed URL service is unavailable.",
          fields: {},
          correlation_id: "corr-download-503",
        }),
      )
      .mockResolvedValueOnce({
        url: "https://files.example.test/signed/evidence-retry.pdf",
        filename: "evidence.pdf",
        expires_in: 60,
      });
    const assign = vi
      .spyOn(attachmentDownloadNavigation, "assign")
      .mockImplementation(() => undefined);
    const user = userEvent.setup();
    try {
      renderWithProviders(<AttachmentUploader ticketNumber={TICKET_NUMBER} />);

      await user.click(
        await screen.findByRole("button", { name: "Download evidence.pdf" }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The signed URL service is unavailable.",
      );
      await user.click(
        screen.getByRole("button", { name: "Download evidence.pdf" }),
      );

      await waitFor(() => expect(harness.download).toHaveBeenCalledTimes(2));
      await waitFor(() =>
        expect(assign).toHaveBeenCalledWith(
          "https://files.example.test/signed/evidence-retry.pdf",
        ),
      );
    } finally {
      assign.mockRestore();
    }
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
