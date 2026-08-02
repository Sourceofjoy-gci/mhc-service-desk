import { useMutation } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  Check,
  Clock3,
  ExternalLink,
  SearchCheck,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, apiProblem, ticketsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

const REFERENCE_PATTERN = /^[A-Z]\d{5}$/u;

function normaliseReference(value: string): string {
  return value.trim().toUpperCase();
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function trackingErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "The ticket could not be found or is outside your access.";
  }
  const problem = apiProblem(error);
  if (problem?.correlation_id) {
    return `The ticket could not be loaded. Support reference: ${problem.correlation_id}`;
  }
  return "The ticket could not be loaded. Try again.";
}

export default function TicketTrackingPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [reference, setReference] = useState(
    () => searchParams.get("reference") ?? "",
  );
  const [validationError, setValidationError] = useState<string | null>(null);
  const submissionLock = useRef(false);
  const autoSubmittedReference = useRef<string | null>(null);
  const lookup = useMutation({
    mutationFn: (nextReference: string) => ticketsApi.track(nextReference),
  });
  const mutateTracking = lookup.mutateAsync;

  const submitReference = useCallback(
    async (rawReference: string, updateLocation: boolean) => {
      if (submissionLock.current) return;
      const normalised = normaliseReference(rawReference);
      if (!REFERENCE_PATTERN.test(normalised)) {
        setValidationError(
          "Enter a valid ticket reference with one letter and five digits, for example O00123.",
        );
        document.getElementById("ticket-reference")?.focus();
        return;
      }

      submissionLock.current = true;
      setReference(normalised);
      setValidationError(null);
      if (updateLocation) {
        setSearchParams(new URLSearchParams({ reference: normalised }), {
          replace: true,
        });
      }
      try {
        await mutateTracking(normalised);
      } catch {
        // The mutation retains the structured error for the accessible alert.
      } finally {
        submissionLock.current = false;
      }
    },
    [mutateTracking, setSearchParams],
  );

  useEffect(() => {
    const supplied = searchParams.get("reference");
    if (!supplied) return;
    const normalised = normaliseReference(supplied);
    setReference(normalised);
    if (!REFERENCE_PATTERN.test(normalised)) {
      setValidationError(
        "Enter a valid ticket reference with one letter and five digits, for example O00123.",
      );
      return;
    }
    if (autoSubmittedReference.current === normalised) return;
    autoSubmittedReference.current = normalised;
    if (supplied !== normalised) {
      setSearchParams(new URLSearchParams({ reference: normalised }), {
        replace: true,
      });
    }
    void submitReference(normalised, false);
  }, [searchParams, setSearchParams, submitReference]);

  const normalisedInput = normaliseReference(reference);
  const lookupMatchesInput = lookup.variables === normalisedInput;
  const result = lookupMatchesInput ? lookup.data : undefined;
  const lookupError = lookup.isError && lookupMatchesInput ? lookup.error : null;

  return (
    <section className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <header className="page-heading mb-0">
        <p className="text-xs font-semibold tracking-[0.18em] text-gold uppercase">
          Helpdesk workspace
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Track a ticket</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Enter the reference given to the requester to check progress within your
          authorised helpdesk scope.
        </p>
      </header>

      <Card className="border-l-4 border-l-primary">
        <CardHeader>
          <CardTitle>Ticket reference</CardTitle>
          <CardDescription>
            References contain one letter followed by five digits, for example O00123.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(event) => {
              event.preventDefault();
              void submitReference(reference, true);
            }}
            noValidate
          >
            <div className="flex min-w-0 flex-1 flex-col gap-2">
              <Label htmlFor="ticket-reference">Reference number</Label>
              <Input
                id="ticket-reference"
                name="reference"
                autoComplete="off"
                spellCheck={false}
                value={reference}
                aria-invalid={validationError ? true : undefined}
                aria-describedby={
                  validationError ? "ticket-reference-error" : undefined
                }
                placeholder="O00123"
                className="font-mono uppercase tabular-nums"
                onChange={(event) => {
                  setReference(event.target.value);
                  if (validationError) setValidationError(null);
                }}
              />
            </div>
            <Button type="submit" size="lg" disabled={lookup.isPending}>
              {lookup.isPending ? (
                <Spinner aria-hidden data-icon="inline-start" />
              ) : (
                <SearchCheck aria-hidden data-icon="inline-start" />
              )}
              {lookup.isPending ? "Checking ticket" : "Track ticket"}
            </Button>
          </form>
          {validationError ? (
            <p
              id="ticket-reference-error"
              role="alert"
              className="mt-3 text-sm text-destructive"
            >
              {validationError}
            </p>
          ) : null}
        </CardContent>
      </Card>

      {lookupError ? (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertTitle>Unable to track ticket</AlertTitle>
          <AlertDescription>{trackingErrorMessage(lookupError)}</AlertDescription>
        </Alert>
      ) : null}

      {result ? (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.78fr)]">
          <Card>
            <CardHeader className="border-b">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 space-y-1">
                  <p className="font-mono text-xs font-semibold tracking-wide text-muted-foreground uppercase tabular-nums">
                    {result.reference}
                  </p>
                  <CardTitle>
                    <h2 className="text-xl font-semibold tracking-tight">
                      {result.title}
                    </h2>
                  </CardTitle>
                </div>
                <Badge>{result.tracking_status}</Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-5">
              <dl className="grid gap-4 sm:grid-cols-2">
                <div>
                  <dt className="text-xs font-medium text-muted-foreground uppercase">
                    Office
                  </dt>
                  <dd className="mt-1 font-medium">{result.office}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-muted-foreground uppercase">
                    Service
                  </dt>
                  <dd className="mt-1 font-medium">{result.service}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-muted-foreground uppercase">
                    Submitted
                  </dt>
                  <dd className="mt-1">{formatDateTime(result.created_at)}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-muted-foreground uppercase">
                    Status updated
                  </dt>
                  <dd className="mt-1">
                    {formatDateTime(result.status_updated_at)}
                  </dd>
                </div>
              </dl>
              <Link
                to={`/tickets/${encodeURIComponent(result.reference)}`}
                className={cn(buttonVariants({ variant: "outline" }), "w-fit")}
              >
                Open full ticket
                <ExternalLink aria-hidden data-icon="inline-end" />
              </Link>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="border-b">
              <CardTitle>Progress</CardTitle>
              <CardDescription>
                Requester-safe milestones in chronological order.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ol aria-label="Ticket progress" className="space-y-0">
                {result.progress.map((item, index) => {
                  const current = index === result.progress.length - 1;
                  return (
                    <li
                      key={`${item.occurred_at}:${item.status}:${index}`}
                      className="relative grid grid-cols-[1.5rem_1fr] gap-3 pb-5 last:pb-0"
                    >
                      {index < result.progress.length - 1 ? (
                        <span
                          aria-hidden
                          className="absolute top-5 bottom-0 left-[0.7rem] w-px bg-border"
                        />
                      ) : null}
                      <span
                        aria-hidden
                        className={cn(
                          "relative z-10 mt-0.5 flex size-6 items-center justify-center rounded-full border bg-background",
                          current && "border-primary bg-primary text-primary-foreground",
                        )}
                      >
                        {current ? <Check className="size-3.5" /> : <Clock3 className="size-3" />}
                      </span>
                      <div className="min-w-0">
                        <span className="font-medium">{item.status}</span>
                        <time
                          dateTime={item.occurred_at}
                          className="mt-0.5 block text-xs text-muted-foreground"
                        >
                          {formatDateTime(item.occurred_at)}
                        </time>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </section>
  );
}
