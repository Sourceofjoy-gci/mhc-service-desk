import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ticketsApi, DEV_AUTH_TOKEN } from "../../lib/api";

interface UploadResult {
  id: string;
  filename: string;
  size_bytes: number;
  scan_status: "pending" | "clean" | "infected" | "error";
  scan_signature: string;
}

interface UploadResponse {
  results: UploadResult[];
}

async function uploadFiles(number: string, files: File[]): Promise<UploadResponse> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const r = await fetch(`/api/v1/tickets/${number}/attachments/`, {
    method: "POST",
    body: form,
    headers: DEV_AUTH_TOKEN ? { Authorization: DEV_AUTH_TOKEN } : {},
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`upload failed: ${r.status} ${body.slice(0, 200)}`);
  }
  return r.json();
}

export default function AttachmentUploader({ ticketNumber }: { ticketNumber: string }) {
  const [files, setFiles] = useState<File[]>([]);
  const upload = useMutation({
    mutationFn: (fs: File[]) => uploadFiles(ticketNumber, fs),
    onSuccess: () => setFiles([]),
  });

  return (
    <div className="rounded-md border border-ink-100 bg-white p-4">
      <h2 className="text-sm font-semibold text-ink-700">Attachments</h2>
      <p className="mt-1 text-xs text-ink-500">
        Files are scanned by ClamAV before they can be downloaded (FR-093, FR-094).
      </p>
      <div className="mt-3 space-y-2">
        <input
          type="file"
          multiple
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
          className="block w-full text-sm"
        />
        {files.length > 0 && (
          <ul className="space-y-1 text-xs text-ink-500">
            {files.map((f) => (
              <li key={f.name}>
                {f.name} — {Math.round(f.size / 1024)} KB
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-center gap-2">
          <button
            onClick={() => upload.mutate(files)}
            disabled={files.length === 0 || upload.isPending}
            className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {upload.isPending ? "Uploading…" : "Upload"}
          </button>
          {upload.isError && (
            <span className="text-sm text-red-700">{(upload.error as Error).message}</span>
          )}
        </div>
        {upload.data && (
          <ul className="mt-2 space-y-1 text-sm">
            {upload.data.results.map((r) => (
              <li
                key={r.id}
                className={
                  r.scan_status === "infected"
                    ? "rounded-md bg-red-50 p-2 text-red-800"
                    : r.scan_status === "clean"
                    ? "rounded-md bg-green-50 p-2 text-green-800"
                    : "rounded-md bg-amber-50 p-2 text-amber-800"
                }
              >
                <span className="font-medium">{r.filename}</span> — scan: {r.scan_status}
                {r.scan_signature ? ` (${r.scan_signature})` : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
