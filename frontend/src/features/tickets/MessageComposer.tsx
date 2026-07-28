import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { apiProblem, type ApiProblem, ticketsApi } from "@/lib/api";

interface MessageComposerProps {
  ticketNumber: string;
  onCreated: () => void | Promise<void>;
}

type ComposerMode = "reply" | "note";

function MutationError({
  title,
  problem,
}: {
  title: string;
  problem: ApiProblem | null;
}) {
  return (
    <Alert variant="destructive">
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>{problem?.detail ?? "Please try again."}</p>
        {problem ? <p>Reference: {problem.correlation_id}</p> : null}
      </AlertDescription>
    </Alert>
  );
}

export function MessageComposer({
  ticketNumber,
  onCreated,
}: MessageComposerProps) {
  const [mode, setMode] = useState<ComposerMode>("reply");
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const replyLocked = useRef(false);
  const noteLocked = useRef(false);

  const replyMutation = useMutation({
    mutationFn: async (body: string) => {
      const created = await ticketsApi.addMessage(ticketNumber, body);
      await onCreated();
      return created;
    },
    onSuccess: (_created, submittedBody) => {
      setReply((current) => (current === submittedBody ? "" : current));
    },
    onSettled: () => {
      replyLocked.current = false;
    },
  });

  const noteMutation = useMutation({
    mutationFn: async (body: string) => {
      const created = await ticketsApi.addNote(ticketNumber, body);
      await onCreated();
      return created;
    },
    onSuccess: (_created, submittedBody) => {
      setNote((current) => (current === submittedBody ? "" : current));
    },
    onSettled: () => {
      noteLocked.current = false;
    },
  });

  function submitReply() {
    const body = reply;
    if (!body.trim() || replyLocked.current) return;
    replyLocked.current = true;
    replyMutation.mutate(body);
  }

  function submitNote() {
    const body = note;
    if (!body.trim() || noteLocked.current) return;
    noteLocked.current = true;
    noteMutation.mutate(body);
  }

  const replyProblem = apiProblem(replyMutation.error);
  const noteProblem = apiProblem(noteMutation.error);

  return (
    <section
      aria-labelledby="message-composer-heading"
      className="border-t pt-5"
    >
      <h2 id="message-composer-heading" className="text-base font-semibold">
        Add to activity
      </h2>
      <Tabs
        className="mt-3"
        value={mode}
        onValueChange={(value) => {
          if (value === "reply" || value === "note") setMode(value);
        }}
      >
        <TabsList aria-label="Message type" variant="line">
          <TabsTrigger value="reply">Reply</TabsTrigger>
          <TabsTrigger value="note">Internal note</TabsTrigger>
        </TabsList>

        <TabsContent value="reply">
          <form
            className="space-y-3 pt-3"
            onSubmit={(event) => {
              event.preventDefault();
              submitReply();
            }}
          >
            <Field data-invalid={Boolean(replyProblem?.fields.body_text)}>
              <FieldLabel htmlFor="ticket-reply">Reply message</FieldLabel>
              <Textarea
                id="ticket-reply"
                value={reply}
                disabled={replyMutation.isPending}
                aria-invalid={Boolean(replyProblem?.fields.body_text)}
                onChange={(event) => setReply(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                This message is visible to the requester.
              </p>
              <FieldError
                errors={replyProblem?.fields.body_text?.map((message) => ({
                  message,
                }))}
              />
            </Field>

            {replyMutation.isError ? (
              <MutationError
                title="Could not send reply"
                problem={replyProblem}
              />
            ) : null}

            <div className="flex justify-end">
              <Button
                type="submit"
                disabled={!reply.trim() || replyMutation.isPending}
              >
                {replyMutation.isPending ? (
                  <Spinner aria-hidden data-icon="inline-start" />
                ) : null}
                {replyMutation.isPending ? "Sending…" : "Send reply"}
              </Button>
            </div>
          </form>
        </TabsContent>

        <TabsContent value="note">
          <form
            className="space-y-3 border-l-2 border-l-amber-500 pt-3 pl-4"
            onSubmit={(event) => {
              event.preventDefault();
              submitNote();
            }}
          >
            <Field data-invalid={Boolean(noteProblem?.fields.body)}>
              <FieldLabel htmlFor="ticket-internal-note">
                Internal note
              </FieldLabel>
              <Textarea
                id="ticket-internal-note"
                value={note}
                disabled={noteMutation.isPending}
                aria-invalid={Boolean(noteProblem?.fields.body)}
                onChange={(event) => setNote(event.target.value)}
              />
              <p className="text-xs font-medium text-amber-800 dark:text-amber-300">
                Internal notes are not visible to the requester.
              </p>
              <FieldError
                errors={noteProblem?.fields.body?.map((message) => ({
                  message,
                }))}
              />
            </Field>

            {noteMutation.isError ? (
              <MutationError
                title="Could not save internal note"
                problem={noteProblem}
              />
            ) : null}

            <div className="flex justify-end">
              <Button
                type="submit"
                disabled={!note.trim() || noteMutation.isPending}
              >
                {noteMutation.isPending ? (
                  <Spinner aria-hidden data-icon="inline-start" />
                ) : null}
                {noteMutation.isPending ? "Saving…" : "Add internal note"}
              </Button>
            </div>
          </form>
        </TabsContent>
      </Tabs>
    </section>
  );
}
