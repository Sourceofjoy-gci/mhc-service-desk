import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  apiProblem,
  ticketsApi,
  type TicketDetail,
  type TicketWorkStateUpdate,
} from "@/lib/api";

interface OperationsPanelProps {
  ticket: TicketDetail;
  onUpdated: (ticket: TicketDetail) => void;
  onReload: () => void;
  onActivityChanged?: () => void | Promise<void>;
}

interface FormValues {
  assignee: string;
  team: string;
  waiting_reason: string;
  blocked_reason: string;
  next_action: string;
  next_action_at: string;
  confidentiality: string;
}

type EditableField = keyof FormValues;
type DirtyFields = Partial<Record<EditableField, true>>;

const WAITING_REASONS = [
  { value: "", label: "None" },
  { value: "requester", label: "Requester" },
  { value: "third_party", label: "Third party" },
  { value: "internal", label: "Internal dependency" },
];

const CONFIDENTIALITY_OPTIONS = [
  { value: "normal", label: "Normal" },
  { value: "sensitive", label: "Sensitive" },
  { value: "restricted", label: "Restricted" },
];

const controlClassName =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50";

function humanize(value: string) {
  if (!value) return "None";
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function toLocalDateTime(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toApiDateTime(value: string) {
  return value ? new Date(value).toISOString() : null;
}

function valuesFromTicket(ticket: TicketDetail): FormValues {
  return {
    assignee: ticket.assignee ?? "",
    team: ticket.team,
    waiting_reason: ticket.waiting_reason,
    blocked_reason: ticket.blocked_reason,
    next_action: ticket.next_action,
    next_action_at: toLocalDateTime(ticket.next_action_at),
    confidentiality: ticket.confidentiality,
  };
}

function ReadOnlyValue({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0 border-b border-border/60 pb-2 last:border-0">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 break-words text-sm">{children || "None"}</dd>
    </div>
  );
}

export function OperationsPanel({
  ticket,
  onUpdated,
  onReload,
  onActivityChanged,
}: OperationsPanelProps) {
  const initialValues = valuesFromTicket(ticket);
  const [values, setValues] = useState<FormValues>(initialValues);
  const [baseline, setBaseline] = useState<FormValues>(initialValues);
  const [dirty, setDirty] = useState<DirtyFields>({});
  const inFlight = useRef(false);

  const assignees = useQuery({
    queryKey: ["ticket", ticket.number, "assignees"],
    queryFn: () => ticketsApi.assignees(ticket.number),
    enabled: ticket.capabilities.can_reassign,
  });

  const update = useMutation({
    mutationFn: (payload: TicketWorkStateUpdate) =>
      ticketsApi.updateWorkState(ticket.number, payload),
    onSuccess: async (refreshedTicket) => {
      const refreshedValues = valuesFromTicket(refreshedTicket);
      setValues(refreshedValues);
      setBaseline(refreshedValues);
      setDirty({});
      onUpdated(refreshedTicket);
      await onActivityChanged?.();
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });
  const resetUpdate = update.reset;

  useEffect(() => {
    const refreshedValues = valuesFromTicket(ticket);
    setValues(refreshedValues);
    setBaseline(refreshedValues);
    setDirty({});
    resetUpdate();
  }, [resetUpdate, ticket]);

  const mutate = (payload: TicketWorkStateUpdate) => {
    if (inFlight.current) return;
    inFlight.current = true;
    update.mutate(payload);
  };

  const change = (field: EditableField, value: string) => {
    update.reset();
    setValues((current) => ({ ...current, [field]: value }));
    setDirty((current) => {
      const next = { ...current };
      if (value === baseline[field]) delete next[field];
      else next[field] = true;
      return next;
    });
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (update.isPending || Object.keys(dirty).length === 0) return;

    const payload: TicketWorkStateUpdate = { updated_at: ticket.updated_at };
    for (const field of Object.keys(dirty) as EditableField[]) {
      if (field === "next_action_at") {
        payload.next_action_at = toApiDateTime(values.next_action_at);
      } else if (field === "assignee") {
        payload.assignee = values.assignee || null;
      } else {
        payload[field] = values[field];
      }
    }
    mutate(payload);
  };

  const selfAssign = () => {
    const selfAssigneeId = ticket.capabilities.self_assignee_id;
    if (!selfAssigneeId || update.isPending) return;
    mutate({
      assignee: selfAssigneeId,
      updated_at: ticket.updated_at,
    });
  };

  const problem = apiProblem(update.error);
  const assigneesProblem = apiProblem(assignees.error);
  const stale = update.isError && problem?.code === "stale_ticket";
  const fieldErrors = problem?.fields ?? {};
  const canEditWorkState = ticket.capabilities.can_update_work_state;
  const canReassign = ticket.capabilities.can_reassign;
  const canChangeConfidentiality =
    ticket.capabilities.can_change_confidentiality;
  const hasEditableFields =
    canEditWorkState || canReassign || canChangeConfidentiality;
  const disabled = update.isPending;
  const waitingReasonIsKnown = WAITING_REASONS.some(
    (option) => option.value === values.waiting_reason,
  );

  return (
    <section className="space-y-4" aria-labelledby="operations-heading">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 id="operations-heading" className="text-base font-semibold">
            Operations
          </h2>
          <p className="text-sm text-muted-foreground">
            Assignment, ownership, and the next planned action.
          </p>
        </div>
        {ticket.assignee === null &&
        ticket.capabilities.can_self_assign &&
        ticket.capabilities.self_assignee_id ? (
          <Button
            type="button"
            size="sm"
            disabled={disabled}
            onClick={selfAssign}
          >
            {disabled ? "Assigning…" : "Self-assign"}
          </Button>
        ) : null}
      </div>

      {hasEditableFields ? (
        <form onSubmit={submit} className="space-y-4">
          <FieldGroup className="gap-3">
            {canReassign ? (
              <Field data-invalid={Boolean(fieldErrors.assignee)}>
                <FieldLabel htmlFor="operations-assignee">Assignee</FieldLabel>
                <select
                  id="operations-assignee"
                  className={controlClassName}
                  value={values.assignee}
                  disabled={
                    disabled || assignees.isLoading || assignees.isError
                  }
                  aria-invalid={Boolean(fieldErrors.assignee)}
                  onChange={(event) => change("assignee", event.target.value)}
                >
                  <option value="">Unassigned</option>
                  {!assignees.isSuccess &&
                  values.assignee &&
                  ticket.assignee_detail ? (
                    <option value={values.assignee}>
                      {ticket.assignee_detail.display_name}
                    </option>
                  ) : null}
                  {assignees.data?.results.map((assignee) => (
                    <option key={assignee.id} value={assignee.id}>
                      {assignee.display_name}
                    </option>
                  ))}
                </select>
                <FieldError
                  errors={fieldErrors.assignee?.map((message) => ({ message }))}
                />
              </Field>
            ) : (
              <dl>
                <ReadOnlyValue label="Assignee">
                  {ticket.assignee_detail?.display_name ?? "Unassigned"}
                </ReadOnlyValue>
              </dl>
            )}

            {canEditWorkState ? (
              <>
                <Field data-invalid={Boolean(fieldErrors.team)}>
                  <FieldLabel htmlFor="operations-team">Team</FieldLabel>
                  <Input
                    id="operations-team"
                    value={values.team}
                    disabled={disabled}
                    aria-invalid={Boolean(fieldErrors.team)}
                    onChange={(event) => change("team", event.target.value)}
                  />
                  <FieldError
                    errors={fieldErrors.team?.map((message) => ({ message }))}
                  />
                </Field>

                <Field data-invalid={Boolean(fieldErrors.waiting_reason)}>
                  <FieldLabel htmlFor="operations-waiting-reason">
                    Waiting reason
                  </FieldLabel>
                  <select
                    id="operations-waiting-reason"
                    className={controlClassName}
                    value={values.waiting_reason}
                    disabled={disabled}
                    aria-invalid={Boolean(fieldErrors.waiting_reason)}
                    onChange={(event) =>
                      change("waiting_reason", event.target.value)
                    }
                  >
                    {!waitingReasonIsKnown ? (
                      <option value={values.waiting_reason}>
                        {humanize(values.waiting_reason)}
                      </option>
                    ) : null}
                    {WAITING_REASONS.map((reason) => (
                      <option key={reason.value} value={reason.value}>
                        {reason.label}
                      </option>
                    ))}
                  </select>
                  <FieldError
                    errors={fieldErrors.waiting_reason?.map((message) => ({
                      message,
                    }))}
                  />
                </Field>

                <Field data-invalid={Boolean(fieldErrors.blocked_reason)}>
                  <FieldLabel htmlFor="operations-blocked-reason">
                    Blocked reason
                  </FieldLabel>
                  <Textarea
                    id="operations-blocked-reason"
                    value={values.blocked_reason}
                    disabled={disabled}
                    aria-invalid={Boolean(fieldErrors.blocked_reason)}
                    onChange={(event) =>
                      change("blocked_reason", event.target.value)
                    }
                  />
                  <FieldError
                    errors={fieldErrors.blocked_reason?.map((message) => ({
                      message,
                    }))}
                  />
                </Field>

                <Field data-invalid={Boolean(fieldErrors.next_action)}>
                  <FieldLabel htmlFor="operations-next-action">
                    Next action
                  </FieldLabel>
                  <Input
                    id="operations-next-action"
                    value={values.next_action}
                    disabled={disabled}
                    aria-invalid={Boolean(fieldErrors.next_action)}
                    onChange={(event) =>
                      change("next_action", event.target.value)
                    }
                  />
                  <FieldError
                    errors={fieldErrors.next_action?.map((message) => ({
                      message,
                    }))}
                  />
                </Field>

                <Field data-invalid={Boolean(fieldErrors.next_action_at)}>
                  <FieldLabel htmlFor="operations-next-action-at">
                    Next action time
                  </FieldLabel>
                  <Input
                    id="operations-next-action-at"
                    type="datetime-local"
                    value={values.next_action_at}
                    disabled={disabled}
                    aria-invalid={Boolean(fieldErrors.next_action_at)}
                    onChange={(event) =>
                      change("next_action_at", event.target.value)
                    }
                  />
                  <FieldError
                    errors={fieldErrors.next_action_at?.map((message) => ({
                      message,
                    }))}
                  />
                </Field>
              </>
            ) : (
              <dl className="grid gap-3">
                <ReadOnlyValue label="Team">{ticket.team}</ReadOnlyValue>
                <ReadOnlyValue label="Waiting reason">
                  {humanize(ticket.waiting_reason)}
                </ReadOnlyValue>
                <ReadOnlyValue label="Blocked reason">
                  {ticket.blocked_reason}
                </ReadOnlyValue>
                <ReadOnlyValue label="Next action">
                  {ticket.next_action}
                </ReadOnlyValue>
                <ReadOnlyValue label="Next action time">
                  {ticket.next_action_at ? (
                    <time dateTime={ticket.next_action_at}>
                      {new Intl.DateTimeFormat(undefined, {
                        dateStyle: "medium",
                        timeStyle: "short",
                      }).format(new Date(ticket.next_action_at))}
                    </time>
                  ) : (
                    "None"
                  )}
                </ReadOnlyValue>
              </dl>
            )}

            {canChangeConfidentiality ? (
              <Field data-invalid={Boolean(fieldErrors.confidentiality)}>
                <FieldLabel htmlFor="operations-confidentiality">
                  Confidentiality
                </FieldLabel>
                <select
                  id="operations-confidentiality"
                  className={controlClassName}
                  value={values.confidentiality}
                  disabled={disabled}
                  aria-invalid={Boolean(fieldErrors.confidentiality)}
                  onChange={(event) =>
                    change("confidentiality", event.target.value)
                  }
                >
                  {CONFIDENTIALITY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <FieldError
                  errors={fieldErrors.confidentiality?.map((message) => ({
                    message,
                  }))}
                />
              </Field>
            ) : (
              <dl>
                <ReadOnlyValue label="Confidentiality">
                  {humanize(ticket.confidentiality)}
                </ReadOnlyValue>
              </dl>
            )}
          </FieldGroup>

          {assignees.isError ? (
            <Alert variant="destructive">
              <AlertCircle data-icon="inline-start" aria-hidden />
              <AlertTitle>Could not load eligible assignees</AlertTitle>
              <AlertDescription>
                {assigneesProblem?.detail ??
                  "Please reload the ticket and try again."}
                {assigneesProblem
                  ? ` Reference: ${assigneesProblem.correlation_id}`
                  : ""}
              </AlertDescription>
            </Alert>
          ) : null}

          {stale ? (
            <Alert variant="destructive">
              <AlertCircle data-icon="inline-start" aria-hidden />
              <AlertTitle>This ticket changed since you opened it</AlertTitle>
              <AlertDescription>
                Reload the current ticket before saving these changes.
              </AlertDescription>
            </Alert>
          ) : update.isError && problem ? (
            <Alert variant="destructive">
              <AlertCircle data-icon="inline-start" aria-hidden />
              <AlertTitle>Could not update operations</AlertTitle>
              <AlertDescription>
                {problem.detail} Reference: {problem.correlation_id}
              </AlertDescription>
            </Alert>
          ) : update.isError ? (
            <Alert variant="destructive">
              <AlertCircle data-icon="inline-start" aria-hidden />
              <AlertTitle>Could not update operations</AlertTitle>
              <AlertDescription>Please try again.</AlertDescription>
            </Alert>
          ) : null}

          <div className="flex justify-end">
            {stale ? (
              <Button type="button" disabled={disabled} onClick={onReload}>
                Reload
              </Button>
            ) : (
              <Button
                type="submit"
                disabled={disabled || Object.keys(dirty).length === 0}
              >
                {disabled ? "Saving…" : "Save"}
              </Button>
            )}
          </div>
        </form>
      ) : (
        <dl className="grid gap-3" aria-label="Read-only ticket operations">
          <ReadOnlyValue label="Assignee">
            {ticket.assignee_detail?.display_name ?? "Unassigned"}
          </ReadOnlyValue>
          <ReadOnlyValue label="Team">{ticket.team}</ReadOnlyValue>
          <ReadOnlyValue label="Waiting reason">
            {humanize(ticket.waiting_reason)}
          </ReadOnlyValue>
          <ReadOnlyValue label="Blocked reason">
            {ticket.blocked_reason}
          </ReadOnlyValue>
          <ReadOnlyValue label="Next action">{ticket.next_action}</ReadOnlyValue>
          <ReadOnlyValue label="Next action time">
            {ticket.next_action_at ? (
              <time dateTime={ticket.next_action_at}>
                {new Intl.DateTimeFormat(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                }).format(new Date(ticket.next_action_at))}
              </time>
            ) : (
              "None"
            )}
          </ReadOnlyValue>
          <ReadOnlyValue label="Confidentiality">
            {humanize(ticket.confidentiality)}
          </ReadOnlyValue>
        </dl>
      )}
    </section>
  );
}
