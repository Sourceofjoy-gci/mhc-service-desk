import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Send, StickyNote } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ChannelBadge,
  PriorityBadge,
  StatusBadge,
} from "@/components/domain-badges";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { ticketsApi, type TicketDetail } from "../../lib/api";
import AttachmentUploader from "./AttachmentUploader";

export default function TicketDetailPage() {
  const { number } = useParams<{ number: string }>();
  const qc = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ["ticket", number],
    queryFn: () => ticketsApi.get(number!),
    enabled: !!number,
  });

  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");

  const addMessage = useMutation({
    mutationFn: (body_text: string) =>
      ticketsApi.addMessage(number!, body_text),
    onSuccess: () => {
      setReply("");
      qc.invalidateQueries({ queryKey: ["ticket", number] });
    },
  });

  const addNote = useMutation({
    mutationFn: (body: string) => ticketsApi.addNote(number!, body),
    onSuccess: () => {
      setNote("");
      qc.invalidateQueries({ queryKey: ["ticket", number] });
    },
  });

  if (isLoading) {
    return (
      <section
        className="flex flex-col gap-6"
        aria-busy="true"
        aria-label="Loading ticket"
      >
        <Skeleton className="h-7 w-32" />
        <div className="flex flex-col gap-3">
          <Skeleton className="h-4 w-28" />
          <Skeleton className="h-9 w-3/4" />
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-20 w-full" />
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="flex flex-col gap-4 lg:col-span-2">
            {Array.from({ length: 3 }, (_, index) => (
              <Card key={index} className="rounded-lg!">
                <CardHeader>
                  <Skeleton className="h-5 w-32" />
                  <Skeleton className="h-4 w-48" />
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                </CardContent>
              </Card>
            ))}
          </div>
          <div className="flex flex-col gap-4">
            {Array.from({ length: 2 }, (_, index) => (
              <Card key={index} className="rounded-lg!">
                <CardHeader>
                  <Skeleton className="h-5 w-28" />
                  <Skeleton className="h-4 w-40" />
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <Skeleton className="h-5 w-full" />
                  <Skeleton className="h-5 w-full" />
                  <Skeleton className="h-5 w-3/4" />
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>
    );
  }

  if (error || !data) {
    return (
      <Alert variant="destructive">
        <AlertCircle data-icon="inline-start" aria-hidden />
        <AlertTitle>Could not load ticket {number}</AlertTitle>
        <AlertDescription>
          The ticket details are unavailable.{" "}
          <Link to="/tickets">Back to queue</Link>
        </AlertDescription>
      </Alert>
    );
  }

  const t = data as TicketDetail;

  return (
    <section className="flex flex-col gap-6">
      <div>
        <Button
          variant="ghost"
          size="sm"
          render={<Link to="/tickets" />}
          nativeButton={false}
        >
          <ArrowLeft data-icon="inline-start" />
          Back to queue
        </Button>
      </div>

      <header className="flex flex-col gap-4">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-start">
          <div className="flex min-w-0 flex-col gap-1">
            <p className="font-mono text-xs text-muted-foreground">
              {t.number}
            </p>
            <h1 className="text-2xl font-semibold tracking-tight">{t.title}</h1>
            <p className="text-sm text-muted-foreground">
              {t.requester.full_name} · {t.office} · {t.service} ·{" "}
              {t.request_type}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 md:justify-end">
            <StatusBadge code={t.status_code} label={t.status_name} />
            <PriorityBadge code={t.priority} />
            <ChannelBadge channel={t.channel} />
            <span className="text-sm tabular-nums text-muted-foreground">
              {t.age_hours.toFixed(1)}h old
            </span>
          </div>
        </div>
        {t.description && (
          <p className="max-w-4xl whitespace-pre-line text-sm leading-relaxed text-foreground">
            {t.description}
          </p>
        )}
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="flex min-w-0 flex-col gap-4 lg:col-span-2">
          <Card className="rounded-lg!">
            <CardHeader>
              <CardTitle>
                <h2>Conversation</h2>
              </CardTitle>
              <CardDescription>
                Messages exchanged with the requester.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {t.messages.length === 0 ? (
                <Empty className="min-h-24 p-4">
                  <EmptyHeader>
                    <EmptyTitle>No messages yet.</EmptyTitle>
                    <EmptyDescription>
                      Replies and requester messages will appear here.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <ul className="flex flex-col" aria-label="Ticket messages">
                  {t.messages.map((m, index) => (
                    <li key={m.id} className="flex flex-col gap-2">
                      {index > 0 ? <Separator className="mb-3" /> : null}
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs font-medium">
                          {m.direction === "outbound" ? "↑ Reply" : "↓ Inbound"}{" "}
                          · {m.author_label || "system"}
                        </p>
                        <time
                          className="text-xs text-muted-foreground"
                          dateTime={m.created_at}
                        >
                          {new Date(m.created_at).toLocaleString()}
                        </time>
                      </div>
                      <p className="whitespace-pre-line text-sm leading-relaxed">
                        {m.body_text}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
            <CardFooter className="flex-col items-stretch gap-3">
              <FieldGroup className="gap-3">
                <Field>
                  <FieldLabel htmlFor="ticket-reply">
                    Reply to requester
                  </FieldLabel>
                  <Textarea
                    id="ticket-reply"
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    placeholder="Reply to the requester…"
                    rows={3}
                  />
                </Field>
              </FieldGroup>
              <Button
                className="self-end"
                disabled={!reply.trim() || addMessage.isPending}
                onClick={() => addMessage.mutate(reply)}
              >
                {addMessage.isPending ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <Send data-icon="inline-start" />
                )}
                {addMessage.isPending ? "Sending…" : "Send reply"}
              </Button>
            </CardFooter>
          </Card>

          <Card className="rounded-lg!">
            <CardHeader>
              <CardTitle>
                <h2>Internal notes</h2>
              </CardTitle>
              <CardDescription>
                Notes are never visible to the requester.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {t.notes.length === 0 ? (
                <Empty className="min-h-24 p-4">
                  <EmptyHeader>
                    <EmptyTitle>No notes yet.</EmptyTitle>
                    <EmptyDescription>
                      Internal notes will appear here.
                    </EmptyDescription>
                  </EmptyHeader>
                </Empty>
              ) : (
                <ul className="flex flex-col" aria-label="Internal notes">
                  {t.notes.map((n, index) => (
                    <li key={n.id} className="flex flex-col gap-2">
                      {index > 0 ? <Separator className="mb-3" /> : null}
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="text-xs font-medium">
                          {n.author_subject}
                        </p>
                        <time
                          className="text-xs text-muted-foreground"
                          dateTime={n.created_at}
                        >
                          {new Date(n.created_at).toLocaleString()}
                        </time>
                      </div>
                      <p className="whitespace-pre-line text-sm leading-relaxed">
                        {n.body}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
            <CardFooter className="flex-col items-stretch gap-3">
              <FieldGroup className="gap-3">
                <Field>
                  <FieldLabel htmlFor="internal-note">
                    Add internal note
                  </FieldLabel>
                  <Textarea
                    id="internal-note"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Add an internal note…"
                    rows={2}
                  />
                </Field>
              </FieldGroup>
              <Button
                variant="secondary"
                className="self-end"
                disabled={!note.trim() || addNote.isPending}
                onClick={() => addNote.mutate(note)}
              >
                {addNote.isPending ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <StickyNote data-icon="inline-start" />
                )}
                {addNote.isPending ? "Saving…" : "Add note"}
              </Button>
            </CardFooter>
          </Card>

          <AttachmentUploader ticketNumber={t.number} />
        </div>

        <aside
          className="flex min-w-0 flex-col gap-4"
          aria-label="Ticket details"
        >
          <Card className="rounded-lg!">
            <CardHeader>
              <CardTitle>
                <h2>Requester</h2>
              </CardTitle>
              <CardDescription>
                Contact details for this ticket.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="flex flex-col text-sm">
                <div className="flex items-start justify-between gap-4">
                  <dt className="text-muted-foreground">Full name</dt>
                  <dd className="text-right font-medium">
                    {t.requester.full_name}
                  </dd>
                </div>
                {t.requester.email && (
                  <div>
                    <Separator className="mb-3" />
                    <div className="flex items-start justify-between gap-4">
                      <dt className="text-muted-foreground">Email</dt>
                      <dd className="break-all text-right">
                        {t.requester.email}
                      </dd>
                    </div>
                  </div>
                )}
                {t.requester.phone_e164 && (
                  <div>
                    <Separator className="mb-3" />
                    <div className="flex items-start justify-between gap-4">
                      <dt className="text-muted-foreground">Phone</dt>
                      <dd className="text-right">{t.requester.phone_e164}</dd>
                    </div>
                  </div>
                )}
              </dl>
            </CardContent>
          </Card>

          <Card className="rounded-lg!">
            <CardHeader>
              <CardTitle>
                <h2>Classification</h2>
              </CardTitle>
              <CardDescription>Routing and matter details.</CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="flex flex-col text-sm">
                <div className="flex items-center justify-between gap-4">
                  <dt className="text-muted-foreground">Channel</dt>
                  <dd>
                    <ChannelBadge channel={t.channel} />
                  </dd>
                </div>
                <div>
                  <Separator className="mb-3" />
                  <div className="flex items-start justify-between gap-4">
                    <dt className="text-muted-foreground">Office</dt>
                    <dd className="text-right">{t.office}</dd>
                  </div>
                </div>
                <div>
                  <Separator className="mb-3" />
                  <div className="flex items-start justify-between gap-4">
                    <dt className="text-muted-foreground">Service</dt>
                    <dd className="text-right">{t.service}</dd>
                  </div>
                </div>
                <div>
                  <Separator className="mb-3" />
                  <div className="flex items-start justify-between gap-4">
                    <dt className="text-muted-foreground">Type</dt>
                    <dd className="text-right">{t.request_type}</dd>
                  </div>
                </div>
                {t.matter_reference && (
                  <div>
                    <Separator className="mb-3" />
                    <div className="flex items-start justify-between gap-4">
                      <dt className="text-muted-foreground">Matter</dt>
                      <dd className="break-all text-right font-mono text-xs">
                        {t.matter_reference}
                      </dd>
                    </div>
                  </div>
                )}
              </dl>
            </CardContent>
          </Card>
        </aside>
      </div>
    </section>
  );
}
