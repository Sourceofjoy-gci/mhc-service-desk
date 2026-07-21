import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { Phone, User, ArrowRight, CheckCircle2, RotateCcw } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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
  const [submitted, setSubmitted] = useState<{ number: string; priority: string } | null>(null);
  const meta = CHANNEL_META[channel];
  const Icon = meta.icon;

  const submit = useMutation({
    mutationFn: (data: FormState) =>
      ticketsApi.publicIntake({ ...data, consent: true, channel }),
    onSuccess: (r) =>
      setSubmitted({ number: r.ticket_number, priority: r.priority }),
  });

  const update = <K extends keyof FormState>(key: K) => (value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  if (submitted) {
    return (
      <div className="mx-auto max-w-2xl">
        <Card>
          <CardContent className="flex flex-col items-center gap-5 p-10 text-center">
            <div className="grid size-14 place-items-center rounded-full bg-success/15 text-success-foreground ring-1 ring-inset ring-success/30">
              <CheckCircle2 className="size-7" />
            </div>
            <div className="flex flex-col gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">
                {meta.label} capture complete
              </h1>
              <p className="text-sm text-muted-foreground">
                Ticket <span className="font-mono">{submitted.number}</span> at priority{" "}
                <Badge variant="secondary" className="font-mono">
                  {submitted.priority}
                </Badge>{" "}
                has been created.
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button render={<Link to={`/tickets/${submitted.number}`} />} data-icon>
                Open ticket
                <ArrowRight data-icon="inline-end" />
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setSubmitted(null);
                  setForm(EMPTY);
                }}
                data-icon
              >
                <RotateCcw data-icon="inline-start" />
                New capture
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <span
              className="grid size-9 place-items-center rounded-md bg-primary/10 text-primary ring-1 ring-inset ring-primary/20"
              aria-hidden
            >
              <Icon className="size-4" />
            </span>
            <Badge variant="secondary" className="font-normal">
              {meta.label} · {location.pathname}
            </Badge>
          </div>
          <CardTitle className="text-2xl">{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit.mutate(form);
          }}
        >
          <CardContent className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <Field label="Service">
                <Select
                  value={form.service_code}
                  onValueChange={(v) => { if (v == null) return; update("service_code")(v) }}
                >
                  <SelectTrigger>
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
              <Field label="Type of request">
                <Select
                  value={form.request_type_code}
                  onValueChange={(v) => { if (v == null) return; update("request_type_code")(v) }}
                >
                  <SelectTrigger>
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
              <Field label="Office">
                <Select
                  value={form.office_code}
                  onValueChange={(v) => { if (v == null) return; update("office_code")(v) }}
                >
                  <SelectTrigger>
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
              <Field label="Matter reference (optional)">
                <Input
                  value={form.matter_reference}
                  onChange={(e) => update("matter_reference")(e.target.value)}
                  maxLength={128}
                />
              </Field>
            </div>
            <Field label="Title" required>
              <Input
                value={form.title}
                onChange={(e) => update("title")(e.target.value)}
                maxLength={255}
                required
              />
            </Field>
            <Field label="Notes" required>
              <Textarea
                value={form.description}
                onChange={(e) => update("description")(e.target.value)}
                rows={4}
                required
              />
            </Field>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <Field label="Requester name" required>
                <Input
                  value={form.requester_name}
                  onChange={(e) => update("requester_name")(e.target.value)}
                  maxLength={255}
                  required
                />
              </Field>
              <Field label="Email">
                <Input
                  type="email"
                  value={form.requester_email}
                  onChange={(e) => update("requester_email")(e.target.value)}
                />
              </Field>
              <Field label="Phone">
                <Input
                  type="tel"
                  value={form.requester_phone}
                  onChange={(e) => update("requester_phone")(e.target.value)}
                  maxLength={32}
                />
              </Field>
            </div>
          </CardContent>
          <CardFooter className="flex justify-end">
            <Button
              type="submit"
              disabled={
                submit.isPending ||
                !form.title ||
                !form.description ||
                !form.requester_name
              }
              data-icon
            >
              {submit.isPending ? "Saving…" : "Capture ticket"}
              <ArrowRight data-icon="inline-end" />
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-foreground/80">
        {label}
        {required ? <span className="text-destructive"> *</span> : null}
      </label>
      {children}
    </div>
  );
}
