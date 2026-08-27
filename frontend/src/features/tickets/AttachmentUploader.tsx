import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Download,
  FileText,
  Paperclip,
  Upload,
} from "lucide-react";
import { useRef, useState } from "react";
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
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import {
  ApiError,
  apiProblem,
  attachmentsApi,
  type AttachmentMetadata,
} from "@/lib/api";

export const attachmentDownloadNavigation = {
  assign(url: string) {
    window.location.assign(url);
  },
};

const attachmentDate = new Intl.DateTimeFormat("en-ZA", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Africa/Johannesburg",
});

const scanState: Record<
  AttachmentMetadata["scan_status"],
  { label: string; variant: "secondary" | "outline" | "destructive" }
> = {
  clean: { label: "Ready", variant: "secondary" },
  pending: { label: "Scanning", variant: "outline" },
  infected: { label: "Quarantined", variant: "destructive" },
  error: { label: "Scan failed", variant: "destructive" },
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kilobytes = bytes / 1024;
  if (kilobytes < 1024) {
    return `${Number.isInteger(kilobytes) ? kilobytes : kilobytes.toFixed(1)} KB`;
  }
  const megabytes = kilobytes / 1024;
  return `${Number.isInteger(megabytes) ? megabytes : megabytes.toFixed(1)} MB`;
}

function FailureAlert({
  error,
  deniedTitle,
  errorTitle,
  deniedFallback,
  errorFallback,
}: {
  error: unknown;
  deniedTitle: string;
  errorTitle: string;
  deniedFallback: string;
  errorFallback: string;
}) {
  const problem = apiProblem(error);
  const denied = error instanceof ApiError && error.status === 403;

  return (
    <Alert variant="destructive">
      <AlertCircle data-icon="inline-start" aria-hidden />
      <AlertTitle>{denied ? deniedTitle : errorTitle}</AlertTitle>
      <AlertDescription>
        <p>{problem?.detail ?? (denied ? deniedFallback : errorFallback)}</p>
        {problem ? <p>Reference: {problem.correlation_id}</p> : null}
      </AlertDescription>
    </Alert>
  );
}

function AttachmentRow({ attachment }: { attachment: AttachmentMetadata }) {
  const downloadLock = useRef(false);
  const download = useMutation({
    mutationKey: ["attachment-download", attachment.id],
    mutationFn: () => attachmentsApi.download(attachment.id),
    onSuccess: ({ url }) => attachmentDownloadNavigation.assign(url),
    onSettled: () => {
      downloadLock.current = false;
    },
  });
  const state = scanState[attachment.scan_status];
  const canDownload =
    attachment.download_available && attachment.scan_status === "clean";

  function requestDownload() {
    if (downloadLock.current || !canDownload) return;
    downloadLock.current = true;
    download.mutate();
  }

  return (
    <li className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <FileText
            className="mt-0.5 size-4 shrink-0 text-muted-foreground"
            aria-hidden
          />
          <div className="min-w-0">
            <p className="truncate font-medium">{attachment.filename}</p>
            <p className="flex flex-wrap gap-x-1 text-xs text-muted-foreground">
              <span>{formatSize(attachment.size_bytes)}</span>
              <span aria-hidden>·</span>
              <span>{attachment.content_type}</span>
            </p>
          </div>
        </div>
        <Badge variant={state.variant}>{state.label}</Badge>
      </div>

      <dl className="grid gap-1 pl-6.5 text-xs text-muted-foreground sm:grid-cols-2">
        <div className="flex gap-1">
          <dt>Uploaded by</dt>
          <dd className="font-medium text-foreground">
            {attachment.uploaded_by || "System"}
          </dd>
        </div>
        <div className="flex gap-1 sm:justify-end">
          <dt className="sr-only">Uploaded at</dt>
          <dd>
            <time dateTime={attachment.uploaded_at}>
              {attachmentDate.format(new Date(attachment.uploaded_at))}
            </time>
          </dd>
        </div>
      </dl>

      {canDownload ? (
        <Button
          variant="outline"
          size="sm"
          className="ml-6.5 self-start"
          aria-label={`Download ${attachment.filename}`}
          disabled={download.isPending}
          onClick={requestDownload}
        >
          {download.isPending ? (
            <Spinner data-icon="inline-start" aria-hidden />
          ) : (
            <Download data-icon="inline-start" aria-hidden />
          )}
          Download
        </Button>
      ) : null}

      {download.isError ? (
        <FailureAlert
          error={download.error}
          deniedTitle="Download unavailable"
          errorTitle="Download failed"
          deniedFallback="You do not have permission to download this attachment."
          errorFallback="The download could not be prepared. Please try again."
        />
      ) : null}
    </li>
  );
}

export default function AttachmentUploader({
  ticketNumber,
  canUpload = true,
  embedded = false,
  compact = false,
}: {
  ticketNumber: string;
  canUpload?: boolean;
  embedded?: boolean;
  compact?: boolean;
}) {
  const queryClient = useQueryClient();
  const uploadLock = useRef(false);
  const [files, setFiles] = useState<File[]>([]);
  const [inputKey, setInputKey] = useState(0);

  const attachments = useQuery({
    queryKey: ["ticket-attachments", ticketNumber],
    queryFn: () => attachmentsApi.list(ticketNumber),
  });

  const upload = useMutation({
    mutationFn: (selectedFiles: readonly File[]) =>
      attachmentsApi.upload(ticketNumber, selectedFiles),
    onSuccess: async () => {
      setFiles([]);
      setInputKey((key) => key + 1);
      toast.success("Attachments uploaded");
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["ticket-attachments", ticketNumber],
        }),
        queryClient.invalidateQueries({
          queryKey: ["ticket-activity", ticketNumber],
        }),
      ]);
    },
    onSettled: () => {
      uploadLock.current = false;
    },
  });

  function submitFiles() {
    if (uploadLock.current || files.length === 0) return;
    uploadLock.current = true;
    upload.mutate(files);
  }

  const attachmentResults = attachments.data?.results ?? [];
  const existingAttachments = (
    <section aria-label="Existing attachments">
      {attachments.isLoading ? (
        <div className="flex min-h-20 items-center justify-center">
          <Spinner className="size-5" aria-label="Loading attachments" />
        </div>
      ) : attachments.isError ? (
        <FailureAlert
          error={attachments.error}
          deniedTitle="Attachments unavailable"
          errorTitle="Could not load attachments"
          deniedFallback="You do not have permission to view attachments for this ticket."
          errorFallback="The attachment list could not be loaded. Please try again."
        />
      ) : attachmentResults.length === 0 ? (
        embedded ? (
          <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
            No attachments yet.
          </p>
        ) : (
          <Empty className="min-h-24 border">
            <EmptyHeader>
              <EmptyTitle>No attachments yet</EmptyTitle>
              <EmptyDescription>
                Uploaded files and their scan results will appear here.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )
      ) : (
        <ul className="divide-y divide-border" aria-label="Ticket attachments">
          {attachmentResults.map((attachment) => (
            <AttachmentRow key={attachment.id} attachment={attachment} />
          ))}
        </ul>
      )}
    </section>
  );

  const uploadForm = canUpload ? (
    <form
      className={embedded ? "" : "border-t pt-4"}
      onSubmit={(event) => {
        event.preventDefault();
        submitFiles();
      }}
    >
      <FieldGroup className="gap-3">
        <Field>
          <FieldLabel htmlFor="ticket-attachments">Choose files</FieldLabel>
          <Input
            key={inputKey}
            id="ticket-attachments"
            type="file"
            multiple
            disabled={upload.isPending}
            onChange={(event) => {
              setFiles(Array.from(event.target.files ?? []));
              upload.reset();
            }}
          />
          <FieldDescription>
            Choose one or more files. Downloads remain unavailable until
            scanning is complete.
          </FieldDescription>
        </Field>
      </FieldGroup>

      {files.length > 0 ? (
        <ul
          className="mt-3 flex flex-col gap-1 text-xs text-muted-foreground"
          aria-label="Selected files"
        >
          {files.map((file) => (
            <li key={`${file.name}:${file.size}:${file.lastModified}`}>
              {file.name} · {formatSize(file.size)}
            </li>
          ))}
        </ul>
      ) : null}

      <Button
        type="submit"
        className="mt-3"
        disabled={files.length === 0 || upload.isPending}
      >
        {upload.isPending ? (
          <Spinner data-icon="inline-start" aria-hidden />
        ) : (
          <Upload data-icon="inline-start" aria-hidden />
        )}
        Upload
      </Button>
    </form>
  ) : null;

  const uploadError =
    canUpload && upload.isError ? (
      <FailureAlert
        error={upload.error}
        deniedTitle="Upload unavailable"
        errorTitle="Upload failed"
        deniedFallback="You do not have permission to upload attachments to this ticket."
        errorFallback="The files could not be uploaded. Please try again."
      />
    ) : null;

  if (embedded) {
    return (
      <section
        aria-labelledby="attachments-heading"
        className={compact ? "flex flex-col gap-3" : "flex flex-col gap-4"}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              {compact ? (
                <Paperclip
                  className="size-4 text-muted-foreground"
                  aria-hidden
                />
              ) : null}
              <h2 id="attachments-heading" className="text-base font-semibold">
                Attachments
              </h2>
              {compact && !attachments.isLoading && !attachments.isError ? (
                <span className="text-sm text-muted-foreground">
                  ({attachmentResults.length})
                </span>
              ) : null}
            </div>
            {!compact ? (
              <p className="text-sm text-muted-foreground">
                Files become available after security scanning.
              </p>
            ) : null}
          </div>
          {!compact && !attachments.isLoading && !attachments.isError ? (
            <Badge
              variant="outline"
              aria-label={`${attachmentResults.length} attachments`}
            >
              {attachmentResults.length}
            </Badge>
          ) : null}
        </div>
        {existingAttachments}
        {uploadForm ? (
          <details className="rounded-lg border border-border/80 bg-background/30">
            <summary className="flex min-h-9 cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
              <Upload className="size-4 text-muted-foreground" aria-hidden />
              Add files
            </summary>
            <div className="border-t border-border/80 p-3">{uploadForm}</div>
          </details>
        ) : null}
        {uploadError}
      </section>
    );
  }

  return (
    <Card className="rounded-lg!">
      <CardHeader>
        <CardTitle>
          <h2 id="attachments-heading">Attachments</h2>
        </CardTitle>
        <CardDescription>
          Files remain unavailable until their security scan is complete.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {existingAttachments}
        {uploadForm}
        {uploadError}
      </CardContent>
    </Card>
  );
}
