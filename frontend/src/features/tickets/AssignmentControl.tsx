import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { StaffCombobox } from "@/components/ui/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  apiProblem,
  ticketsApi,
  type ApiProblem,
  type AssignmentReceipt,
  type TicketAssignee,
  type TicketDetail,
} from "@/lib/api";

export interface AssignmentControlProps {
  ticket: TicketDetail;
  onUpdated: (ticket: TicketDetail) => void;
  onReload: () => void;
  onActivityChanged?: () => void | Promise<void>;
}

type AssignmentAction = "assign" | "transfer" | "unassign";
type ProposalSource = "directory" | "self";

interface AssignmentProposal {
  selected: TicketAssignee | null;
  source: ProposalSource;
}

const actionLabels: Record<AssignmentAction, string> = {
  assign: "Assign",
  transfer: "Transfer",
  unassign: "Unassign",
};

const pendingLabels: Record<AssignmentAction, string> = {
  assign: "Assigning…",
  transfer: "Transferring…",
  unassign: "Unassigning…",
};

function useDebouncedValue(value: string, delay: number) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timeout);
  }, [delay, value]);

  return debounced;
}

function proposedAction(
  previousId: string | null,
  selected: TicketAssignee | null,
): AssignmentAction {
  if (selected === null) return "unassign";
  return previousId === null ? "assign" : "transfer";
}

function assignmentPartyName(party: AssignmentReceipt["previous_assignee"]) {
  return party?.display_name ?? "Unassigned";
}

function receiptSummary(receipt: AssignmentReceipt) {
  const occurredAt = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(receipt.occurred_at));
  return `${receipt.ticket_number} ${receipt.action}: ${assignmentPartyName(receipt.previous_assignee)} → ${assignmentPartyName(receipt.new_assignee)} on ${occurredAt} by ${receipt.performed_by.display_name}.`;
}

function errorDetail(problem: ApiProblem | null, fallback: string) {
  if (!problem) return fallback;
  return `${problem.detail} Reference: ${problem.correlation_id}`;
}

export function AssignmentControl({
  ticket,
  ...callbacks
}: AssignmentControlProps) {
  return (
    <ScopedAssignmentControl
      key={ticket.number}
      ticket={ticket}
      {...callbacks}
    />
  );
}

function ScopedAssignmentControl({
  ticket,
  onUpdated,
  onReload,
  onActivityChanged,
}: AssignmentControlProps) {
  const panelRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLButtonElement | null>(null);
  const submitLockRef = useRef(false);
  const scopeActiveRef = useRef(true);
  const observedUpdatedAtRef = useRef(ticket.updated_at);
  const candidateSnapshots = useRef(new Map<string, TicketAssignee>());
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 250);
  const [proposal, setProposal] = useState<AssignmentProposal | undefined>();
  const [reason, setReason] = useState("");
  const [receipt, setReceipt] = useState<string | null>(null);
  const [permissionProblem, setPermissionProblem] = useState<ApiProblem | null>(
    null,
  );

  useEffect(() => {
    scopeActiveRef.current = true;
    return () => {
      scopeActiveRef.current = false;
    };
  }, []);

  const candidates = useQuery({
    queryKey: ["ticket", ticket.number, "assignees", debouncedSearch],
    queryFn: () => ticketsApi.assignees(ticket.number, debouncedSearch),
    enabled: ticket.capabilities.can_assign,
  });
  const candidateOptions = candidates.data?.results ?? [];
  for (const candidate of candidateOptions) {
    candidateSnapshots.current.set(candidate.id, candidate);
  }

  const mutation = useMutation({
    mutationFn: (values: {
      selected: TicketAssignee | null;
      submittedReason: string;
    }) =>
      ticketsApi.assign(ticket.number, {
        assignee_id: values.selected?.id ?? null,
        expected_updated_at: ticket.updated_at,
        reason: values.submittedReason,
      }),
    onSuccess: async (response) => {
      if (!scopeActiveRef.current) return;
      onUpdated(response.ticket);
      const summary = receiptSummary(response.receipt);
      setReceipt(summary);
      toast.success(summary);
      setProposal(undefined);
      setReason("");
      await onActivityChanged?.();
    },
    onError: (error) => {
      if (!scopeActiveRef.current) return;
      if (error instanceof ApiError && error.status === 403) {
        setPermissionProblem(apiProblem(error));
        setProposal(undefined);
        setReason("");
        window.setTimeout(() => returnFocusRef.current?.focus(), 0);
      }
    },
    onSettled: () => {
      submitLockRef.current = false;
    },
  });

  const currentId = ticket.assignee_detail?.id ?? null;
  const selectedId =
    proposal === undefined ? currentId : (proposal.selected?.id ?? null);
  const action =
    proposal === undefined
      ? null
      : proposedAction(currentId, proposal.selected);
  const reasonRequired = action === "transfer" || action === "unassign";
  const disabled = mutation.isPending;
  const mutationProblem = apiProblem(mutation.error);
  const stale =
    mutation.error instanceof ApiError && mutation.error.status === 409;
  const forbidden =
    mutation.error instanceof ApiError && mutation.error.status === 403;
  const candidateProblem = apiProblem(candidates.error);
  const selfCandidate = ticket.capabilities.self_assignee_detail;
  const canSelfAssign =
    ticket.capabilities.can_self_assign && selfCandidate !== null;
  const proposalAllowed =
    proposal === undefined ||
    (proposal.source === "directory"
      ? ticket.capabilities.can_assign
      : proposal.selected !== null &&
        canSelfAssign &&
        selfCandidate.id === proposal.selected.id);

  useEffect(() => {
    const timestampChanged = observedUpdatedAtRef.current !== ticket.updated_at;
    observedUpdatedAtRef.current = ticket.updated_at;
    if (
      timestampChanged &&
      mutation.error instanceof ApiError &&
      mutation.error.status === 409
    ) {
      mutation.reset();
    }
  }, [mutation, ticket.updated_at]);

  useEffect(() => {
    if (proposal === undefined || proposalAllowed) return;
    mutation.reset();
    submitLockRef.current = false;
    setReason("");
    setProposal(undefined);
    window.setTimeout(() => returnFocusRef.current?.focus(), 0);
  }, [mutation, proposal, proposalAllowed]);

  const candidateError = candidates.isError
    ? errorDetail(
        candidateProblem,
        "Eligible team members are temporarily unavailable.",
      )
    : undefined;
  const reasonErrors = mutationProblem?.fields.reason ?? [];
  const mutationErrorDetail = errorDetail(
    mutationProblem,
    "The assignment could not be completed. Please try again.",
  );

  const rememberReturnFocus = (button?: HTMLButtonElement | null) => {
    returnFocusRef.current =
      button ??
      panelRef.current?.querySelector<HTMLButtonElement>(
        '[data-slot="staff-combobox"] [role="combobox"]',
      ) ??
      null;
  };

  const openProposal = (
    selected: TicketAssignee | null,
    source: ProposalSource,
    button?: HTMLButtonElement | null,
  ) => {
    if (
      disabled ||
      selected?.id === currentId ||
      (selected === null && currentId === null)
    ) {
      return;
    }
    rememberReturnFocus(button);
    mutation.reset();
    setPermissionProblem(null);
    setReason("");
    setProposal({ selected, source });
  };

  const selectCandidate = (id: string | null) => {
    if (id === null) {
      openProposal(null, "directory");
      return;
    }
    const selected = candidateSnapshots.current.get(id);
    if (selected) openProposal(selected, "directory");
  };

  const cancel = () => {
    if (disabled) return;
    mutation.reset();
    setReason("");
    setProposal(undefined);
    window.setTimeout(() => returnFocusRef.current?.focus(), 0);
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (
      proposal === undefined ||
      !proposalAllowed ||
      submitLockRef.current ||
      disabled ||
      (reasonRequired && !reason.trim())
    ) {
      return;
    }
    submitLockRef.current = true;
    mutation.mutate({
      selected: proposal.selected,
      submittedReason: reason.trim(),
    });
  };

  const currentOwner = ticket.assignee_detail?.display_name ?? "Unassigned";

  return (
    <section
      ref={panelRef}
      aria-labelledby="ticket-assignment-heading"
      className="flex flex-col gap-4 border-b border-border pb-5"
    >
      <div className="flex flex-col gap-1">
        <h2 id="ticket-assignment-heading" className="text-base font-semibold">
          Assignment
        </h2>
        <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
          <span className="text-muted-foreground">Current owner</span>
          <span className="font-medium text-foreground">{currentOwner}</span>
        </div>
      </div>

      {ticket.capabilities.can_assign ? (
        <StaffCombobox
          id={`assignment-${ticket.number}`}
          label="Eligible team member"
          value={selectedId}
          options={candidateOptions}
          onValueChange={selectCandidate}
          onSearchChange={setSearch}
          allowUnassigned={currentId !== null}
          disabled={disabled}
          loading={candidates.isLoading || candidates.isFetching}
          error={candidateError}
        />
      ) : canSelfAssign ? (
        <div className="flex flex-col items-start gap-1.5">
          <Button
            ref={returnFocusRef}
            type="button"
            disabled={disabled}
            onClick={(event) =>
              openProposal(
                selfCandidate,
                "self",
                event.currentTarget as HTMLButtonElement,
              )
            }
          >
            Self-assign
          </Button>
          <p className="text-sm text-muted-foreground">
            Assign this ticket to {selfCandidate.display_name}.
          </p>
        </div>
      ) : null}

      {permissionProblem ? (
        <Alert variant="destructive">
          <ShieldAlert aria-hidden="true" />
          <AlertTitle>Assignment permission changed</AlertTitle>
          <AlertDescription>
            <p>{permissionProblem.detail}</p>
            <p>Reference: {permissionProblem.correlation_id}</p>
          </AlertDescription>
        </Alert>
      ) : null}

      {receipt ? (
        <div
          role="status"
          aria-live="polite"
          className="border-l-2 border-primary bg-muted/50 px-3 py-2 text-sm text-foreground"
        >
          {receipt}
        </div>
      ) : null}

      <Dialog
        open={proposal !== undefined && proposalAllowed}
        onOpenChange={(open) => {
          if (!open) cancel();
        }}
      >
        <DialogContent showCloseButton={!disabled} finalFocus={returnFocusRef}>
          {proposal !== undefined && action ? (
            <form onSubmit={submit} className="contents">
              <DialogHeader>
                <DialogTitle>Confirm ticket assignment</DialogTitle>
                <DialogDescription>
                  Review the ownership change before it is recorded.
                </DialogDescription>
              </DialogHeader>

              <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/35 p-3 text-sm">
                <p>
                  <span className="text-muted-foreground">Ticket:</span>{" "}
                  <span className="font-medium">{ticket.number}</span>
                </p>
                <p>
                  <span className="text-muted-foreground">
                    Previous assignee:
                  </span>{" "}
                  <span className="font-medium">{currentOwner}</span>
                </p>
                <p>
                  <span className="text-muted-foreground">New assignee:</span>{" "}
                  <span className="font-medium">
                    {proposal.selected?.display_name ?? "Unassigned"}
                  </span>
                </p>
              </div>

              <Field data-invalid={reasonErrors.length > 0 || undefined}>
                <FieldLabel htmlFor={`assignment-reason-${ticket.number}`}>
                  Reason for transfer
                </FieldLabel>
                <Textarea
                  id={`assignment-reason-${ticket.number}`}
                  value={reason}
                  required={reasonRequired}
                  disabled={disabled}
                  aria-invalid={reasonErrors.length > 0 || undefined}
                  onChange={(event) => setReason(event.target.value)}
                />
                <FieldDescription>
                  {reasonRequired
                    ? "Required for transfers and unassignment."
                    : "Optional for an initial assignment."}
                </FieldDescription>
                <FieldError
                  errors={reasonErrors.map((message) => ({ message }))}
                />
              </Field>

              {stale ? (
                <Alert variant="destructive">
                  <AlertCircle aria-hidden="true" />
                  <AlertTitle>
                    This ticket changed since you opened it
                  </AlertTitle>
                  <AlertDescription>
                    Reload the current ticket, then review this proposed
                    assignment again.
                  </AlertDescription>
                </Alert>
              ) : mutation.isError && !forbidden ? (
                <Alert variant="destructive">
                  <AlertCircle aria-hidden="true" />
                  <AlertTitle>Could not update the assignment</AlertTitle>
                  <AlertDescription>
                    {mutationProblem ? (
                      <>
                        <p>{mutationProblem.detail}</p>
                        <p>Reference: {mutationProblem.correlation_id}</p>
                      </>
                    ) : (
                      mutationErrorDetail
                    )}
                  </AlertDescription>
                </Alert>
              ) : null}

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  disabled={disabled}
                  onClick={cancel}
                >
                  Cancel
                </Button>
                {stale ? (
                  <Button type="button" disabled={disabled} onClick={onReload}>
                    Reload
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    disabled={
                      disabled ||
                      !proposalAllowed ||
                      (reasonRequired && !reason.trim())
                    }
                  >
                    {disabled ? pendingLabels[action] : actionLabels[action]}
                  </Button>
                )}
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>
    </section>
  );
}
