import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Phone,
  RotateCcw,
  User,
} from "lucide-react";
import { ticketsApi } from "@/lib/api";
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
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
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

interface ChannelIntakeProps {
  channel: "call" | "walk_in";
  title: string;
  description: string;
}

const CHANNEL_META: Record<
  ChannelIntakeProps["channel"],
  { label: string; icon: typeof Phone; tone: string }
> = {
  call: {
    label: "Call centre",
    icon: Phone,
    tone: "info",
  },
  walk_in: {
    label: "Walk-in",
    icon: User,
    tone: "gold",
  },
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

export default function ChannelIntakePage({
  channel,
  title,
  description,
}: ChannelIntakeProps) {
  const location = useLocation();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [submitted, setSubmitted] = useState<{
    number: string;
    priority: string;
  } | null>(null);
  const meta = CHANNEL_META[channel];
  const Icon = meta.icon;

  const submit = useMutation({
    mutationFn: (data: FormState) =>
      ticketsApi.publicIntake({ ...data, consent: true, channel }),
    onSuccess: (r) =>
      setSubmitted({ number: r.ticket_number, priority: r.priority }),
  });

  const update =
    <K extends keyof FormState>(key: K) =>
    (value: FormState[K]) =>
      setForm((prev) => ({ ...prev, [key]: value }));

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
          <CardContent className="text-center">
            <p className="text-sm text-muted-foreground">
              Ticket <span className="tabular-nums">{submitted.number}</span> at
              priority <Badge variant="secondary">{submitted.priority}</Badge>{" "}
              has been created.
            </p>
          </CardContent>
          <CardFooter className="flex-wrap justify-center gap-2">
            <Button
              render={<Link to={`/tickets/${submitted.number}`} />}
              nativeButton={false}
            >
              Open ticket
              <ArrowRight data-icon="inline-end" />
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setSubmitted(null);
                setForm(EMPTY);
              }}
            >
              <RotateCcw data-icon="inline-start" />
              New capture
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <Card className="rounded-lg!">
        <CardHeader>
          <div className="flex items-center gap-2">
            <span
              className="grid size-9 place-items-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20"
              aria-hidden
            >
              <Icon className="size-4" />
            </span>
            <Badge variant="secondary" className="font-normal">
              {meta.label} · {location.pathname}
            </Badge>
          </div>
          <CardTitle>
            <h1 className="text-2xl">{title}</h1>
          </CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit.mutate(form);
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
                    items={OFFICES}
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
                        {OFFICES.map((s) => (
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
                    onChange={(e) => update("matter_reference")(e.target.value)}
                    maxLength={128}
                  />
                </Field>
              </FieldGroup>

              <Field data-invalid={!form.title}>
                <FieldLabel htmlFor="intake-title">Title *</FieldLabel>
                <Input
                  id="intake-title"
                  value={form.title}
                  onChange={(e) => update("title")(e.target.value)}
                  maxLength={255}
                  required
                  aria-invalid={!form.title}
                />
              </Field>
              <Field data-invalid={!form.description}>
                <FieldLabel htmlFor="intake-description">Notes *</FieldLabel>
                <Textarea
                  id="intake-description"
                  value={form.description}
                  onChange={(e) => update("description")(e.target.value)}
                  rows={4}
                  required
                  aria-invalid={!form.description}
                />
              </Field>

              <FieldGroup className="grid grid-cols-1 gap-4 md:grid-cols-3">
                <Field data-invalid={!form.requester_name}>
                  <FieldLabel htmlFor="intake-requester-name">
                    Requester name *
                  </FieldLabel>
                  <Input
                    id="intake-requester-name"
                    value={form.requester_name}
                    onChange={(e) => update("requester_name")(e.target.value)}
                    maxLength={255}
                    required
                    aria-invalid={!form.requester_name}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="intake-requester-email">
                    Email
                  </FieldLabel>
                  <Input
                    id="intake-requester-email"
                    type="email"
                    value={form.requester_email}
                    onChange={(e) => update("requester_email")(e.target.value)}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="intake-requester-phone">
                    Phone
                  </FieldLabel>
                  <Input
                    id="intake-requester-phone"
                    type="tel"
                    value={form.requester_phone}
                    onChange={(e) => update("requester_phone")(e.target.value)}
                    maxLength={32}
                  />
                </Field>
              </FieldGroup>
            </FieldGroup>
          </CardContent>
          <CardFooter className="justify-end">
            <Button
              type="submit"
              disabled={
                submit.isPending ||
                !form.title ||
                !form.description ||
                !form.requester_name
              }
            >
              {submit.isPending ? <Spinner data-icon="inline-start" /> : null}
              {submit.isPending ? "Saving…" : "Capture ticket"}
              {!submit.isPending ? <ArrowRight data-icon="inline-end" /> : null}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
