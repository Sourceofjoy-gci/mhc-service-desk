import { useMutation } from "@tanstack/react-query";
import { AlertCircle, Upload } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";
import { DEV_AUTH_TOKEN } from "../../lib/api";

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

async function uploadFiles(
  number: string,
  files: File[],
): Promise<UploadResponse> {
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

export default function AttachmentUploader({
  ticketNumber,
}: {
  ticketNumber: string;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const upload = useMutation({
    mutationFn: (fs: File[]) => uploadFiles(ticketNumber, fs),
    onSuccess: () => {
      setFiles([]);
      toast.success("Attachments uploaded");
    },
  });

  return (
    <Card className="rounded-lg!">
      <CardHeader>
        <CardTitle>
          <h2>Attachments</h2>
        </CardTitle>
        <CardDescription>
          Files are scanned by ClamAV before they can be downloaded (FR-093,
          FR-094).
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <FieldGroup className="gap-3">
          <Field>
            <FieldLabel htmlFor="ticket-attachments">Choose files</FieldLabel>
            <Input
              id="ticket-attachments"
              type="file"
              multiple
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
          </Field>
        </FieldGroup>

        {files.length > 0 && (
          <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
            {files.map((f) => (
              <li key={f.name}>
                {f.name} — {Math.round(f.size / 1024)} KB
              </li>
            ))}
          </ul>
        )}

        <Button
          className="self-start"
          onClick={() => upload.mutate(files)}
          disabled={files.length === 0 || upload.isPending}
        >
          {upload.isPending ? (
            <Spinner data-icon="inline-start" />
          ) : (
            <Upload data-icon="inline-start" />
          )}
          {upload.isPending ? "Uploading…" : "Upload"}
        </Button>

        {upload.isError && (
          <Alert variant="destructive">
            <AlertCircle data-icon="inline-start" aria-hidden />
            <AlertTitle>Upload failed</AlertTitle>
            <AlertDescription>
              {(upload.error as Error).message}
            </AlertDescription>
          </Alert>
        )}

        {upload.data && (
          <ul className="flex flex-col" aria-label="Attachment scan results">
            {upload.data.results.map((r, index) => (
              <li key={r.id} className="flex flex-col gap-2">
                {index > 0 ? <Separator className="mb-3" /> : null}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{r.filename}</span>
                  <Badge
                    variant={
                      r.scan_status === "infected" || r.scan_status === "error"
                        ? "destructive"
                        : r.scan_status === "clean"
                          ? "secondary"
                          : "outline"
                    }
                  >
                    {r.scan_status}
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {Math.round(r.size_bytes / 1024)} KB
                  {r.scan_signature ? ` · ${r.scan_signature}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
