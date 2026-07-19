import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ticketsApi } from "../../lib/api";

export default function PublicFormPage() {
  const [form, setForm] = useState({
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
  });
  const [submitted, setSubmitted] = useState<{ number: string; priority: string } | null>(null);

  const submit = useMutation({
    mutationFn: (data: typeof form) => ticketsApi.publicIntake(data),
    onSuccess: (r) => setSubmitted({ number: r.ticket_number, priority: r.priority }),
  });

  if (submitted) {
    return (
      <section className="mx-auto max-w-2xl space-y-4">
        <div className="rounded-md border border-green-200 bg-green-50 p-4 text-sm text-green-800">
          <h1 className="text-lg font-semibold">Your request has been received</h1>
          <p className="mt-1">
            Ticket number: <span className="font-mono">{submitted.number}</span>
          </p>
          <p className="mt-1">
            We will reply within the service-level target for priority {submitted.priority}. Keep this number
            for your records.
          </p>
          <button
            onClick={() => {
              setSubmitted(null);
              setForm({
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
              });
            }}
            className="mt-3 rounded-md border border-green-300 bg-white px-3 py-1.5 text-sm"
          >
            Submit another
          </button>
        </div>
      </section>
    );
  }

  const handle = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const v = e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value;
    setForm({ ...form, [k]: v });
  };

  return (
    <section className="mx-auto max-w-2xl space-y-4">
      <header>
        <h1 className="text-2xl font-semibold">Submit a request</h1>
        <p className="mt-1 text-sm text-ink-500">
          This form does not start a legal filing. It records your enquiry and gives you a ticket number to follow up.
        </p>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit.mutate(form);
        }}
        className="space-y-4 rounded-md border border-ink-100 bg-white p-4"
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Service">
            <select value={form.service_code} onChange={handle("service_code")} className="input">
              <option value="GEN-INFO">General information</option>
              <option value="EST-REG">Estate registration or reference</option>
              <option value="WIL-REG">Will registration or safekeeping</option>
            </select>
          </Field>
          <Field label="Type of request">
            <select value={form.request_type_code} onChange={handle("request_type_code")} className="input">
              <option value="HOURS">Office hours and contact</option>
              <option value="CALLBACK">Callback request</option>
              <option value="NEW-EST">New estate enquiry</option>
              <option value="STATUS">Estate status check</option>
              <option value="SEARCH">Will search request</option>
            </select>
          </Field>
          <Field label="Office">
            <select value={form.office_code} onChange={handle("office_code")} className="input">
              <option value="MHC-MBA">Mbabane (Main)</option>
              <option value="MHC-MAN">Manzini</option>
            </select>
          </Field>
          <Field label="Matter reference (optional)">
            <input
              type="text"
              value={form.matter_reference}
              onChange={handle("matter_reference")}
              className="input"
              maxLength={128}
            />
          </Field>
        </div>

        <Field label="Title" required>
          <input
            type="text"
            value={form.title}
            onChange={handle("title")}
            className="input"
            maxLength={255}
            required
          />
        </Field>
        <Field label="Describe your request" required>
          <textarea
            value={form.description}
            onChange={handle("description")}
            className="input"
            rows={4}
            required
          />
        </Field>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Field label="Your name" required>
            <input
              type="text"
              value={form.requester_name}
              onChange={handle("requester_name")}
              className="input"
              required
              maxLength={255}
            />
          </Field>
          <Field label="Email">
            <input
              type="email"
              value={form.requester_email}
              onChange={handle("requester_email")}
              className="input"
            />
          </Field>
          <Field label="Phone">
            <input
              type="tel"
              value={form.requester_phone}
              onChange={handle("requester_phone")}
              className="input"
              maxLength={32}
            />
          </Field>
        </div>

        <label className="flex items-start gap-2 text-sm text-ink-700">
          <input
            type="checkbox"
            checked={form.consent}
            onChange={handle("consent")}
            className="mt-1"
            required
          />
          <span>
            I consent to the Master's Office processing my contact details and the information in this
            request for the purpose of responding. I understand this is not a formal filing and that the
            Office may retain records in line with its retention schedule.
          </span>
        </label>

        {submit.isError && (
          <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {(submit.error as Error)?.message}
          </div>
        )}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={submit.isPending || !form.consent || !form.title || !form.description || !form.requester_name}
            className="rounded-md bg-brand-600 px-5 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {submit.isPending ? "Submitting…" : "Submit request"}
          </button>
        </div>
      </form>
    </section>
  );
}

function Field({ label, children, required }: { label: string; children: React.ReactNode; required?: boolean }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-700">
        {label}
        {required && <span className="text-red-600"> *</span>}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
