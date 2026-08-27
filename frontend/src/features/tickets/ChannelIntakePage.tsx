import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Copy,
  RotateCcw,
  SearchCheck,
} from "lucide-react";
import { ticketsApi } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import {
  getFirstInvalidFieldId,
  hasContent,
  isOptionalEmailValid,
} from "@/lib/form-validation";
import { OFFICE_OPTIONS } from "./intake-options";

interface ChannelIntakeProps {
  channel: "call" | "walk_in";
  title: string;
  description: string;
}

// Only the label survives: the icon and tone existed for the header chip and
// badge, which duplicated the page heading and the active nav item.
const CHANNEL_META: Record<ChannelIntakeProps["channel"], { label: string }> = {
  call: { label: "Call centre" },
  walk_in: { label: "Walk-in" },
};

interface FormState {
  service_code: string;
  request_type_code: string;
  office_code: string;
  title: string;
  description: string;
  requester_name: string;
  requester_email: string;
  requester_phone: string;
  matter_reference: string;
}

const EMPTY: FormState = {
  service_code: "GEN-INFO",
  request_type_code: "HOURS",
  office_code: "MHC-MBA",
  title: "",
  description: "",
  requester_name: "",
  requester_email: "",
  requester_phone: "",
  matter_reference: "",
};

/**
 * A clerk works at one office all day. Remembering the last one they used
 * turns a per-capture decision back into a default; Mbabane stays the fallback
 * for a fresh browser.
 */
const OFFICE_STORAGE_KEY = "mhc.intake.office";

function rememberedOffice(): string {
  try {
    const stored = localStorage.getItem(OFFICE_STORAGE_KEY);
    if (stored && OFFICE_OPTIONS.some((option) => option.value === stored)) {
      return stored;
    }
  } catch {
    // Storage can be unavailable (private mode, blocked cookies); the default stands.
  }
  return EMPTY.office_code;
}

function blankCapture(): FormState {
  return { ...EMPTY, office_code: rememberedOffice() };
}

const SERVICES = [
  { value: "GEN-INFO", label: "General information" },
  { value: "EST-REG", label: "Estate registration or reference" },
  { value: "WIL-REG", label: "Will registration or safekeeping" },
];
const REQUEST_TYPES = [
  { value: "HOURS", label: "Office hours and contact" },
  { value: "CALLBACK", label: "Callback request" },
  { value: "NEW-EST", label: "New estate enquiry" },
  { value: "STATUS", label: "Estate status check" },
  { value: "SEARCH", label: "Will search request" },
];
export default function ChannelIntakePage({
  channel,
  title,
  description,
}: ChannelIntakeProps) {
  const [form, setForm] = useState<FormState>(blankCapture);
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [submitted, setSubmitted] = useState<{
    number: string;
    priority: string;
  } | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const submissionLock = useRef(false);
  const meta = CHANNEL_META[channel];

  const submit = useMutation({
    mutationFn: (data: FormState) =>
      ticketsApi.publicIntake({ ...data, consent: true, channel }),
    onSuccess: (r) => {
      setCopyError(null);
      setSubmitted({ number: r.ticket_number, priority: r.priority });
    },
    onSettled: () => {
      submissionLock.current = false;
    },
  });

  const update =
    <K extends keyof FormState>(key: K) =>
    (value: FormState[K]) => {
      if (key === "office_code" && typeof value === "string") {
        try {
          localStorage.setItem(OFFICE_STORAGE_KEY, value);
        } catch {
          // Not being able to remember the office is not worth failing a capture over.
        }
      }
      setForm((prev) => ({ ...prev, [key]: value }));
    };

  const validation = {
    title: hasContent(form.title),
    description: hasContent(form.description),
    requesterName: hasContent(form.requester_name),
    requesterEmail: isOptionalEmailValid(form.requester_email),
  };
  const firstInvalidFieldId = getFirstInvalidFieldId([
    { id: "intake-title", valid: validation.title },
    { id: "intake-description", valid: validation.description },
    { id: "intake-requester-name", valid: validation.requesterName },
    { id: "intake-requester-email", valid: validation.requesterEmail },
  ]);
  const canSubmit = firstInvalidFieldId === null;

  function attemptSubmit() {
    setSubmitAttempted(true);
    if (!canSubmit) {
      if (firstInvalidFieldId) {
        document.getElementById(firstInvalidFieldId)?.focus();
      }
      return;
    }
    if (submissionLock.current) return;
    submissionLock.current = true;
    submit.mutate(form);
  }

  async function copyReference(reference: string) {
    try {
      await navigator.clipboard.writeText(reference);
      setCopyError(null);
    } catch {
      setCopyError(
        "The reference could not be copied. Select it and copy it manually.",
      );
    }
  }

  if (submitted) {
    return (
      <div className="mx-auto max-w-2xl">
        <Card className="rounded-lg!">
          <CardHeader className="justify-items-center text-center">
            <span
              className="grid size-14 place-items-center rounded-full bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30"
              aria-hidden
            >
              <CheckCircle2 className="size-7" />
            </span>
            <CardTitle>
              <h1 className="text-2xl font-semibold tracking-tight">
                {meta.label} capture complete
              </h1>
            </CardTitle>
            <CardDescription>
              The request has been added to the operational queue.
            </CardDescription>
          </CardHeader>
          <CardContent role="status" className="space-y-3 text-center">
            <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Reference number
            </p>
            <p className="font-mono text-2xl font-semibold tracking-wide tabular-nums">
              {submitted.number}
            </p>
            <p className="text-sm text-muted-foreground">
              Priority <Badge variant="secondary">{submitted.priority}</Badge>
            </p>
            {copyError ? (
              <p role="alert" className="text-sm text-destructive">
                {copyError}
              </p>
            ) : null}
          </CardContent>
          <CardFooter className="flex-wrap justify-center gap-2">
            {/* At a counter the next thing that happens is almost always the
                next visitor, not tracking the ticket just created. This leads,
                takes the primary weight, and holds focus so Enter starts the
                next capture without a mouse. */}
            <Button
              type="button"
              autoFocus
              onClick={() => {
                setSubmitted(null);
                setForm(blankCapture());
                setSubmitAttempted(false);
                setCopyError(null);
                submissionLock.current = false;
              }}
            >
              <RotateCcw data-icon="inline-start" />
              Start next capture
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => void copyReference(submitted.number)}
            >
              <Copy data-icon="inline-start" />
              Copy reference
            </Button>
            <Link
              className={buttonVariants({ variant: "outline" })}
              to={`/ticket-tracking?reference=${encodeURIComponent(submitted.number)}`}
            >
              <SearchCheck data-icon="inline-start" />
              Track this ticket
            </Link>
          </CardFooter>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <Card className="rounded-lg!">
        <CardHeader>
          <CardTitle>
            <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          </CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            attemptSubmit();
          }}
          // A capture happens with someone waiting at the counter. Ctrl+Enter
          // submits from any field, including the textarea, so the clerk never
          // has to leave the keyboard to reach the button.
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              attemptSubmit();
            }
          }}
        >
          <CardContent>
            <FieldGroup>
              {submit.isError ? (
                <Alert variant="destructive">
                  <AlertCircle aria-hidden />
                  <AlertTitle>Could not capture ticket</AlertTitle>
                  <AlertDescription>
                    {(submit.error as Error | null)?.message ?? "Unknown error"}
                    . Please try again.
                  </AlertDescription>
                </Alert>
              ) : null}

              <FieldSet>
                <FieldLegend>Service details</FieldLegend>
                <FieldDescription>
                  Classify the request before recording its details.
                </FieldDescription>
                <FieldGroup className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <Field>
                    <FieldLabel htmlFor="intake-service">Service</FieldLabel>
                    <Select
                      items={SERVICES}
                      value={form.service_code}
                      onValueChange={(v) => {
                        if (v == null) return;
                        update("service_code")(v);
                      }}
                    >
                      <SelectTrigger id="intake-service">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {SERVICES.map((s) => (
                            <SelectItem key={s.value} value={s.value}>
                              {s.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="intake-request-type">
                      Type of request
                    </FieldLabel>
                    <Select
                      items={REQUEST_TYPES}
                      value={form.request_type_code}
                      onValueChange={(v) => {
                        if (v == null) return;
                        update("request_type_code")(v);
                      }}
                    >
                      <SelectTrigger id="intake-request-type">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {REQUEST_TYPES.map((s) => (
                            <SelectItem key={s.value} value={s.value}>
                              {s.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="intake-office">Office</FieldLabel>
                    <Select
                      items={OFFICE_OPTIONS}
                      value={form.office_code}
                      onValueChange={(v) => {
                        if (v == null) return;
                        update("office_code")(v);
                      }}
                    >
                      <SelectTrigger id="intake-office">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                          {OFFICE_OPTIONS.map((s) => (
                            <SelectItem key={s.value} value={s.value}>
                              {s.label}
                            </SelectItem>
                          ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="intake-matter-reference">
                      Matter reference (optional)
                    </FieldLabel>
                    <Input
                      id="intake-matter-reference"
                      value={form.matter_reference}
                      onChange={(e) =>
                        update("matter_reference")(e.target.value)
                      }
                      maxLength={128}
                    />
                    <FieldDescription>
                      Optional estate or will reference.
                    </FieldDescription>
                  </Field>
                </FieldGroup>
              </FieldSet>

              <FieldSet className="border-t border-border/60 pt-6">
                <FieldLegend>Request details</FieldLegend>
                <FieldGroup>
                  <Field data-invalid={submitAttempted && !validation.title}>
                    <FieldLabel htmlFor="intake-title">
                      Title
                    </FieldLabel>
                    <Input
                      id="intake-title"
                      value={form.title}
                      onChange={(e) => update("title")(e.target.value)}
                      maxLength={255}
                      required
                      aria-invalid={submitAttempted && !validation.title}
                      aria-describedby={
                        submitAttempted && !validation.title
                          ? "intake-title-error"
                          : undefined
                      }
                    />
                    {submitAttempted && !validation.title ? (
                      <FieldError id="intake-title-error">
                        Enter a short title.
                      </FieldError>
                    ) : null}
                  </Field>
                  <Field
                    data-invalid={submitAttempted && !validation.description}
                  >
                    <FieldLabel htmlFor="intake-description">
                      Description
                    </FieldLabel>
                    <FieldDescription id="intake-description-hint">
                      What the requester needs, in their own words.
                    </FieldDescription>
                    <Textarea
                      id="intake-description"
                      className="min-h-32"
                      value={form.description}
                      onChange={(e) => update("description")(e.target.value)}
                      rows={6}
                      required
                      aria-invalid={submitAttempted && !validation.description}
                      // FieldDescription renders a plain <p>, so the hint is
                      // only reachable if it is named here alongside the error.
                      aria-describedby={
                        submitAttempted && !validation.description
                          ? "intake-description-hint intake-description-error"
                          : "intake-description-hint"
                      }
                    />
                    {submitAttempted && !validation.description ? (
                      <FieldError id="intake-description-error">
                        Describe what the requester needs.
                      </FieldError>
                    ) : null}
                  </Field>
                </FieldGroup>
              </FieldSet>

              <FieldSet className="border-t border-border/60 pt-6">
                <FieldLegend>Requester details</FieldLegend>
                <FieldDescription>
                  Record who contacted the office and how they can be reached.
                </FieldDescription>
                <FieldGroup className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <Field
                    data-invalid={submitAttempted && !validation.requesterName}
                  >
                    <FieldLabel htmlFor="intake-requester-name">
                      Requester name
                    </FieldLabel>
                    <Input
                      id="intake-requester-name"
                      value={form.requester_name}
                      onChange={(e) => update("requester_name")(e.target.value)}
                      maxLength={255}
                      required
                      aria-invalid={
                        submitAttempted && !validation.requesterName
                      }
                      aria-describedby={
                        submitAttempted && !validation.requesterName
                          ? "intake-requester-name-error"
                          : undefined
                      }
                      autoComplete="name"
                    />
                    {submitAttempted && !validation.requesterName ? (
                      <FieldError id="intake-requester-name-error">
                        Enter the requester name.
                      </FieldError>
                    ) : null}
                  </Field>
                  <Field
                    data-invalid={submitAttempted && !validation.requesterEmail}
                  >
                    <FieldLabel htmlFor="intake-requester-email">
                      Email (optional)
                    </FieldLabel>
                    <Input
                      id="intake-requester-email"
                      type="email"
                      value={form.requester_email}
                      onChange={(e) =>
                        update("requester_email")(e.target.value)
                      }
                      autoComplete="email"
                      aria-invalid={
                        submitAttempted && !validation.requesterEmail
                      }
                      aria-describedby={
                        submitAttempted && !validation.requesterEmail
                          ? "intake-requester-email-error"
                          : undefined
                      }
                    />
                    {submitAttempted && !validation.requesterEmail ? (
                      <FieldError id="intake-requester-email-error">
                        Enter a valid email address.
                      </FieldError>
                    ) : null}
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="intake-requester-phone">
                      Phone (optional)
                    </FieldLabel>
                    <Input
                      id="intake-requester-phone"
                      type="tel"
                      value={form.requester_phone}
                      onChange={(e) =>
                        update("requester_phone")(e.target.value)
                      }
                      maxLength={32}
                      autoComplete="tel"
                    />
                  </Field>
                </FieldGroup>
              </FieldSet>
            </FieldGroup>
          </CardContent>
          <CardFooter className="flex-wrap justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Press <kbd className="font-mono font-medium">Ctrl</kbd> +{" "}
              <kbd className="font-mono font-medium">Enter</kbd> to capture.
            </p>
            <Button type="submit" disabled={submit.isPending}>
              {submit.isPending ? (
                <Spinner aria-hidden data-icon="inline-start" />
              ) : null}
              Capture ticket
              {!submit.isPending ? <ArrowRight data-icon="inline-end" /> : null}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
