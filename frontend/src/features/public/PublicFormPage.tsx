import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  RotateCcw,
  ScrollText,
  Send,
  Shield,
} from "lucide-react";
import { BrandLockup } from "@/components/brand";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Field,
  FieldContent,
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
import { ticketsApi } from "@/lib/api";
import {
  getFirstInvalidFieldId,
  hasContent,
  isOptionalEmailValid,
} from "@/lib/form-validation";
import { OFFICE_OPTIONS } from "@/features/tickets/intake-options";

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
  consent: boolean;
}

const EMPTY_FORM: FormState = {
  service_code: "GEN-INFO",
  request_type_code: "HOURS",
  office_code: "MHC-MBA",
  title: "",
  description: "",
  requester_name: "",
  requester_email: "",
  requester_phone: "",
  matter_reference: "",
  consent: false,
};

export default function PublicFormPage() {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [submitted, setSubmitted] = useState<{
    number: string;
    priority: string;
  } | null>(null);
  const submissionLock = useRef(false);

  const submit = useMutation({
    mutationFn: (data: FormState) =>
      ticketsApi.publicIntake({ ...data, channel: "web" }),
    onSuccess: (r) =>
      setSubmitted({ number: r.ticket_number, priority: r.priority }),
    onSettled: () => {
      submissionLock.current = false;
    },
  });

  if (submitted) {
    return (
      <SuccessPanel
        data={submitted}
        onReset={() => {
          setSubmitted(null);
          setForm(EMPTY_FORM);
          setSubmitAttempted(false);
          submissionLock.current = false;
        }}
      />
    );
  }

  const update =
    <K extends keyof FormState>(key: K) =>
    (value: FormState[K]) =>
      setForm((prev) => ({ ...prev, [key]: value }));

  const validation = {
    title: hasContent(form.title),
    description: hasContent(form.description),
    requesterName: hasContent(form.requester_name),
    requesterEmail: isOptionalEmailValid(form.requester_email),
    consent: form.consent,
  };
  const firstInvalidFieldId = getFirstInvalidFieldId([
    { id: "public-title", valid: validation.title },
    { id: "public-desc", valid: validation.description },
    { id: "public-name", valid: validation.requesterName },
    { id: "public-email", valid: validation.requesterEmail },
    { id: "public-consent", valid: validation.consent },
  ]);
  const canSubmit = firstInvalidFieldId === null;

  return (
    <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <Card className="rounded-lg!">
        <CardHeader>
          <Badge variant="secondary" className="w-fit gap-2 text-xs">
            <Shield aria-hidden />
            Public intake · Currently disabled
          </Badge>
          <CardTitle>
            <h1 className="text-2xl">Submit a request</h1>
          </CardTitle>
          <CardDescription>
            This form does not start a legal filing. It records your enquiry and
            gives you a ticket number to follow up.
          </CardDescription>
        </CardHeader>
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
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
          }}
        >
          <CardContent className="flex flex-col gap-5">
            <FieldSet>
              <FieldLegend>Service details</FieldLegend>
              <FieldGroup className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="public-service">Service</FieldLabel>
                  <Select
                    items={SERVICES}
                    value={form.service_code}
                    onValueChange={(v) => {
                      if (v == null) return;
                      update("service_code")(v);
                    }}
                  >
                    <SelectTrigger id="public-service">
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
                  <FieldLabel htmlFor="public-request-type">
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
                    <SelectTrigger id="public-request-type">
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
                  <FieldLabel htmlFor="public-office">Office</FieldLabel>
                  <Select
                    items={OFFICE_OPTIONS}
                    value={form.office_code}
                    onValueChange={(v) => {
                      if (v == null) return;
                      update("office_code")(v);
                    }}
                  >
                    <SelectTrigger id="public-office">
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
                  <FieldLabel htmlFor="public-matter">
                    Matter reference
                  </FieldLabel>
                  <Input
                    id="public-matter"
                    value={form.matter_reference}
                    onChange={(e) => update("matter_reference")(e.target.value)}
                    maxLength={128}
                    placeholder="EST-1234"
                  />
                  <FieldDescription>
                    Optional. Estate or will reference, if you have one.
                  </FieldDescription>
                </Field>
              </FieldGroup>
            </FieldSet>

            <FieldSet>
              <FieldLegend>Your request</FieldLegend>
              <FieldGroup className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <Field data-invalid={submitAttempted && !validation.title}>
                  <FieldLabel htmlFor="public-title">
                    Title (required)
                  </FieldLabel>
                  <Input
                    id="public-title"
                    value={form.title}
                    onChange={(e) => update("title")(e.target.value)}
                    maxLength={255}
                    required
                    aria-invalid={submitAttempted && !validation.title}
                    aria-describedby={
                      submitAttempted && !validation.title
                        ? "public-title-error"
                        : undefined
                    }
                    placeholder="A short summary"
                  />
                  {submitAttempted && !validation.title ? (
                    <FieldError id="public-title-error">
                      Enter a short title.
                    </FieldError>
                  ) : null}
                </Field>
                <Field
                  data-invalid={submitAttempted && !validation.description}
                >
                  <FieldLabel htmlFor="public-desc">
                    Describe your request (required)
                  </FieldLabel>
                  <Textarea
                    id="public-desc"
                    rows={5}
                    value={form.description}
                    onChange={(e) => update("description")(e.target.value)}
                    required
                    aria-invalid={submitAttempted && !validation.description}
                    aria-describedby={
                      submitAttempted && !validation.description
                        ? "public-description-error"
                        : undefined
                    }
                    placeholder="What is the request about? Include dates, people, and any context that helps us respond."
                  />
                  {submitAttempted && !validation.description ? (
                    <FieldError id="public-description-error">
                      Describe the request.
                    </FieldError>
                  ) : null}
                </Field>
              </FieldGroup>
            </FieldSet>

            <FieldSet>
              <FieldLegend>Your details</FieldLegend>
              <FieldGroup className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <Field
                  data-invalid={submitAttempted && !validation.requesterName}
                >
                  <FieldLabel htmlFor="public-name">
                    Your name (required)
                  </FieldLabel>
                  <Input
                    id="public-name"
                    value={form.requester_name}
                    onChange={(e) => update("requester_name")(e.target.value)}
                    maxLength={255}
                    required
                    aria-invalid={submitAttempted && !validation.requesterName}
                    aria-describedby={
                      submitAttempted && !validation.requesterName
                        ? "public-name-error"
                        : undefined
                    }
                    autoComplete="name"
                  />
                  {submitAttempted && !validation.requesterName ? (
                    <FieldError id="public-name-error">
                      Enter your name.
                    </FieldError>
                  ) : null}
                </Field>
                <Field
                  data-invalid={submitAttempted && !validation.requesterEmail}
                >
                  <FieldLabel htmlFor="public-email">Email</FieldLabel>
                  <Input
                    id="public-email"
                    type="email"
                    value={form.requester_email}
                    onChange={(e) => update("requester_email")(e.target.value)}
                    placeholder="you@example.com"
                    autoComplete="email"
                    aria-invalid={submitAttempted && !validation.requesterEmail}
                    aria-describedby={
                      submitAttempted && !validation.requesterEmail
                        ? "public-email-error"
                        : undefined
                    }
                  />
                  {submitAttempted && !validation.requesterEmail ? (
                    <FieldError id="public-email-error">
                      Enter a valid email address.
                    </FieldError>
                  ) : null}
                </Field>
                <Field>
                  <FieldLabel htmlFor="public-phone">Phone</FieldLabel>
                  <Input
                    id="public-phone"
                    type="tel"
                    autoComplete="tel"
                    value={form.requester_phone}
                    onChange={(e) => update("requester_phone")(e.target.value)}
                    maxLength={32}
                    placeholder="+268 …"
                  />
                </Field>
              </FieldGroup>
            </FieldSet>

            <FieldSet>
              <FieldLegend variant="label">Consent</FieldLegend>
              <FieldGroup className="gap-4">
                <Field
                  orientation="horizontal"
                  data-invalid={submitAttempted && !validation.consent}
                >
                  <Checkbox
                    id="public-consent"
                    checked={form.consent}
                    onCheckedChange={(v) => update("consent")(v === true)}
                    required
                    aria-invalid={submitAttempted && !validation.consent}
                    aria-describedby={
                      submitAttempted && !validation.consent
                        ? "public-consent-error"
                        : undefined
                    }
                  />
                  <FieldContent>
                    <FieldLabel htmlFor="public-consent">
                      I consent to the Master's Office processing my contact
                      details and the information in this request for the
                      purpose of responding. I understand this is not a formal
                      filing and that the Office may retain records in line with
                      its retention schedule.
                    </FieldLabel>
                  </FieldContent>
                </Field>
                {submitAttempted && !validation.consent ? (
                  <FieldError id="public-consent-error">
                    Consent is required.
                  </FieldError>
                ) : null}
                {submit.isError ? (
                  <Alert variant="destructive">
                    <AlertCircle aria-hidden />
                    <AlertTitle>Could not submit request</AlertTitle>
                    <AlertDescription>
                      Could not submit:{" "}
                      {(submit.error as Error | null)?.message ??
                        "Unknown error"}
                      . Please try again, or contact the office by phone.
                    </AlertDescription>
                  </Alert>
                ) : null}
              </FieldGroup>
            </FieldSet>
          </CardContent>
          <CardFooter className="flex-wrap justify-between gap-4">
            <p className="text-xs text-muted-foreground">
              Submitting creates a ticket in the operational queue.
            </p>
            <Button type="submit" disabled={submit.isPending}>
              {submit.isPending ? (
                <Spinner aria-hidden data-icon="inline-start" />
              ) : (
                <Send data-icon="inline-start" />
              )}
              Submit request
            </Button>
          </CardFooter>
        </form>
      </Card>

      <ReassurancePanel />
    </div>
  );
}

function SuccessPanel({
  data,
  onReset,
}: {
  data: { number: string; priority: string };
  onReset: () => void;
}) {
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
              Your request has been received
            </h1>
          </CardTitle>
          <CardDescription>
            Keep this ticket number for your records. We will respond within the
            service-level target for priority{" "}
            <Badge variant="secondary">{data.priority}</Badge>.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-center">
          <p className="rounded-lg border border-border/60 bg-muted/40 px-5 py-3 text-lg font-semibold tracking-wider tabular-nums">
            {data.number}
          </p>
        </CardContent>
        <CardFooter className="flex-wrap justify-center gap-2">
          <Button onClick={onReset} variant="outline">
            <RotateCcw data-icon="inline-start" />
            Submit another request
          </Button>
          <Button
            render={<Link to="/health" />}
            nativeButton={false}
            variant="ghost"
          >
            <FileText data-icon="inline-start" />
            View service status
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

function ReassurancePanel() {
  return (
    <aside className="flex flex-col gap-4" aria-label="Submission guidance">
      <Card className="rounded-lg!">
        <CardHeader>
          <BrandLockup size="sm" />
          <CardTitle>
            <h2>What happens next</h2>
          </CardTitle>
          <CardDescription>
            Public submission is disabled during the current phase. Requests are
            captured by authorised staff and recorded for audit purposes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col gap-2 text-sm text-muted-foreground">
            <li className="flex items-start gap-2">
              <CheckCircle2 className="mt-1 size-4 shrink-0 text-success" />
              Your enquiry becomes a tracked ticket with a unique number.
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="mt-1 size-4 shrink-0 text-success" />
              Replies come from a Master of the High Court officer, not an
              automated bot.
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="mt-1 size-4 shrink-0 text-success" />
              Records retained per the published retention schedule (7 years
              operational).
            </li>
          </ul>
        </CardContent>
      </Card>
      <Card className="rounded-lg!" size="sm">
        <CardHeader>
          <CardTitle>
            <h2>Prefer another channel?</h2>
          </CardTitle>
          <CardDescription>
            In-person support and formal filing remain available.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <ChannelLink
            icon={Shield}
            title="Visit the office"
            description="Mbabane (Main) and Manzini, weekdays 08:00–16:30."
          />
          <ChannelLink
            icon={ScrollText}
            title="Formal filing"
            description="Use the official filing channels for matters with legal effect."
          />
        </CardContent>
      </Card>
    </aside>
  );
}

function ChannelLink({
  icon: Icon,
  title,
  description,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-border/40 p-3">
      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
        <Icon className="size-4" />
      </span>
      <div className="flex flex-col">
        <span className="text-sm font-medium">{title}</span>
        <span className="text-xs text-muted-foreground">{description}</span>
      </div>
    </div>
  );
}
