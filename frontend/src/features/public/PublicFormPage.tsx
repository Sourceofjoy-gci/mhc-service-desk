import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Send,
  CheckCircle2,
  RotateCcw,
  Shield,
  ScrollText,
  FileText,
  AlertCircle,
} from "lucide-react";
import { ticketsApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { BrandLockup } from "@/components/brand";
import { cn } from "@/lib/utils";

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

const OFFICES = [
  { value: "MHC-MBA", label: "Mbabane (Main)" },
  { value: "MHC-MAN", label: "Manzini" },
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
  const [submitted, setSubmitted] = useState<{ number: string; priority: string } | null>(null);

  const submit = useMutation({
    mutationFn: (data: FormState) => ticketsApi.publicIntake({ ...data, channel: "web" }),
    onSuccess: (r) => setSubmitted({ number: r.ticket_number, priority: r.priority }),
  });

  if (submitted) {
    return <SuccessPanel data={submitted} onReset={() => { setSubmitted(null); setForm(EMPTY_FORM); }} />;
  }

  const update = <K extends keyof FormState>(key: K) => (value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const canSubmit =
    form.consent &&
    form.title.length > 0 &&
    form.description.length > 0 &&
    form.requester_name.length > 0;

  return (
    <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <Card>
        <CardHeader>
          <Badge variant="secondary" className="w-fit gap-1.5 text-xs">
            <Shield className="size-3" />
            Public intake · No sign-in required
          </Badge>
          <CardTitle className="text-2xl">Submit a request</CardTitle>
          <CardDescription>
            This form does not start a legal filing. It records your enquiry
            and gives you a ticket number to follow up.
          </CardDescription>
        </CardHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!canSubmit) return;
            submit.mutate(form);
          }}
        >
          <CardContent className="flex flex-col gap-5">
            <FieldGroup label="Service details">
              <Field label="Service" htmlFor="public-service">
                <Select
                  value={form.service_code}
                  onValueChange={(v) => { if (v == null) return; update("service_code")(v) }}
                >
                  <SelectTrigger id="public-service">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SERVICES.map((s) => (
                      <SelectItem key={s.value} value={s.value}>
                        {s.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Type of request" htmlFor="public-request-type">
                <Select
                  value={form.request_type_code}
                  onValueChange={(v) => { if (v == null) return; update("request_type_code")(v) }}
                >
                  <SelectTrigger id="public-request-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {REQUEST_TYPES.map((s) => (
                      <SelectItem key={s.value} value={s.value}>
                        {s.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Office" htmlFor="public-office">
                <Select
                  value={form.office_code}
                  onValueChange={(v) => { if (v == null) return; update("office_code")(v) }}
                >
                  <SelectTrigger id="public-office">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {OFFICES.map((s) => (
                      <SelectItem key={s.value} value={s.value}>
                        {s.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field
                label="Matter reference"
                htmlFor="public-matter"
                hint="Optional. Estate or will reference, if you have one."
              >
                <Input
                  id="public-matter"
                  value={form.matter_reference}
                  onChange={(e) => update("matter_reference")(e.target.value)}
                  maxLength={128}
                  placeholder="EST-1234"
                />
              </Field>
            </FieldGroup>

            <FieldGroup label="Your request">
              <Field label="Title" htmlFor="public-title" required>
                <Input
                  id="public-title"
                  value={form.title}
                  onChange={(e) => update("title")(e.target.value)}
                  maxLength={255}
                  required
                  placeholder="A short summary"
                />
              </Field>
              <Field label="Describe your request" htmlFor="public-desc" required>
                <Textarea
                  id="public-desc"
                  rows={5}
                  value={form.description}
                  onChange={(e) => update("description")(e.target.value)}
                  required
                  placeholder="What is the request about? Include dates, people, and any context that helps us respond."
                />
              </Field>
            </FieldGroup>

            <FieldGroup label="Your details">
              <Field label="Your name" htmlFor="public-name" required>
                <Input
                  id="public-name"
                  value={form.requester_name}
                  onChange={(e) => update("requester_name")(e.target.value)}
                  maxLength={255}
                  required
                />
              </Field>
              <Field label="Email" htmlFor="public-email">
                <Input
                  id="public-email"
                  type="email"
                  value={form.requester_email}
                  onChange={(e) => update("requester_email")(e.target.value)}
                  placeholder="you@example.com"
                />
              </Field>
              <Field label="Phone" htmlFor="public-phone">
                <Input
                  id="public-phone"
                  type="tel"
                  value={form.requester_phone}
                  onChange={(e) => update("requester_phone")(e.target.value)}
                  maxLength={32}
                  placeholder="+268 …"
                />
              </Field>
            </FieldGroup>

            <ConsentField
              checked={form.consent}
              onCheckedChange={(v) => update("consent")(v)}
              error={submit.isError}
              errorMessage={(submit.error as Error | null)?.message}
            />
          </CardContent>
          <CardFooter className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Submitting creates a ticket in the operational queue.
            </p>
            <Button
              type="submit"
              disabled={!canSubmit || submit.isPending}
              data-icon
            >
              <Send data-icon="inline-start" />
              {submit.isPending ? "Submitting…" : "Submit request"}
            </Button>
          </CardFooter>
        </form>
      </Card>

      <ReassurancePanel />
    </div>
  );
}

function FieldGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">{children}</div>
    </div>
  );
}

function Field({
  label,
  htmlFor,
  hint,
  required,
  children,
  className,
}: {
  label: string;
  htmlFor?: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label
        htmlFor={htmlFor}
        className="text-xs font-medium text-foreground/80"
      >
        {label}
        {required ? <span className="text-destructive"> *</span> : null}
      </label>
      {children}
      {hint ? <p className="text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function ConsentField({
  checked,
  onCheckedChange,
  error,
  errorMessage,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  error: boolean;
  errorMessage?: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <label className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/30 p-3 text-sm transition-colors has-[button[data-state=checked]]:border-primary/50 has-[button[data-state=checked]]:bg-primary/5">
        <Checkbox
          checked={checked}
          onCheckedChange={(v) => onCheckedChange(v === true)}
          required
          className="mt-0.5"
        />
        <span className="text-pretty text-xs text-foreground/90">
          I consent to the Master's Office processing my contact details and
          the information in this request for the purpose of responding. I
          understand this is not a formal filing and that the Office may
          retain records in line with its retention schedule.
        </span>
      </label>
      {error ? (
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Could not submit: {errorMessage ?? "Unknown error"}. Please try
            again, or contact the office by phone.
          </span>
        </div>
      ) : null}
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
      <Card>
        <CardContent className="flex flex-col items-center gap-5 p-10 text-center">
          <div className="grid size-14 place-items-center rounded-full bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30">
            <CheckCircle2 className="size-7" />
          </div>
          <div className="flex flex-col gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">
              Your request has been received
            </h1>
            <p className="text-sm text-muted-foreground">
              Keep this ticket number for your records. We will respond within
              the service-level target for priority{" "}
              <Badge variant="secondary" className="font-mono">
                {data.priority}
              </Badge>
              .
            </p>
          </div>
          <div className="rounded-lg border border-border/60 bg-muted/40 px-5 py-3 font-mono text-lg font-semibold tracking-wider">
            {data.number}
          </div>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Button onClick={onReset} variant="outline" data-icon>
              <RotateCcw data-icon="inline-start" />
              Submit another request
            </Button>
            <Button render={<Link to="/health" />} variant="ghost" data-icon>
              <FileText data-icon="inline-start" />
              View service status
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function ReassurancePanel() {
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <BrandLockup size="sm" />
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm text-muted-foreground">
          <p>
            This form is the public front door to the Master of the High Court
            Service Desk. It is rate-limited, monitored, and recorded for audit
            purposes.
          </p>
          <ul className="flex flex-col gap-2 text-sm">
            <li className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
              Your enquiry becomes a tracked ticket with a unique number.
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
              Replies come from a Master of the High Court officer, not an
              automated bot.
            </li>
            <li className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
              Records retained per the published retention schedule
              (7 years operational).
            </li>
          </ul>
        </CardContent>
      </Card>
      <Card data-size="sm">
        <CardHeader>
          <CardTitle className="text-sm">Prefer another channel?</CardTitle>
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
    </div>
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
    <div className="flex items-start gap-3 rounded-md border border-border/40 p-2.5">
      <span className="grid size-8 shrink-0 place-items-center rounded-md bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
        <Icon className="size-4" />
      </span>
      <div className="flex flex-col">
        <span className="text-sm font-medium">{title}</span>
        <span className="text-xs text-muted-foreground">{description}</span>
      </div>
    </div>
  );
}
