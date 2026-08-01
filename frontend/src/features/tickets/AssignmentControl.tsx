import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ShieldAlert } from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
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

interface AssignmentMutationInput {
  selected: TicketAssignee | null;
  submittedReason: string;
  ticketNumber: string;
  expectedUpdatedAt: string;
  requestId: number;
}

interface CandidateRevalidation {
  dataUpdatedAt: number;
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

function formatReceiptDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "date/time unavailable";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function receiptSummary(receipt: AssignmentReceipt) {
  const occurredAt = formatReceiptDateTime(receipt.occurred_at);
  return `${receipt.ticket_number} ${receipt.action}: ${assignmentPartyName(receipt.previous_assignee)} → ${assignmentPartyName(receipt.new_assignee)} on ${occurredAt} by ${receipt.performed_by.display_name}.`;
}

function assigneeContext(assignee: TicketAssignee) {
  const designation = assignee.designations.join(", ");
  const team = assignee.team_labels.join(", ");
  return [designation, team].filter(Boolean).join(" · ");
}

function isTargetEligibilityProblem(
  error: unknown,
  problem: ApiProblem | null,
) {
  return (
    error instanceof ApiError &&
    error.status === 400 &&
    (problem?.code === "ineligible_assignee" ||
      Boolean(problem?.fields.assignee_id?.length))
  );
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
  const queryClient = useQueryClient();
  const panelRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLButtonElement | null>(null);
  const submitLockRef = useRef(false);
  const scopeActiveRef = useRef(true);
  const scopeTicketNumberRef = useRef(ticket.number);
  const currentTicketRef = useRef({
    number: ticket.number,
    updatedAt: ticket.updated_at,
  });
  const nextRequestIdRef = useRef(1);
  const activeRequestIdRef = useRef<number | null>(null);
  const candidateSnapshots = useRef(new Map<string, TicketAssignee>());
  const candidateDirectoryReadyRef = useRef(false);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search, 250);
  const [proposal, setProposal] = useState<AssignmentProposal | undefined>();
  const [reason, setReason] = useState("");
  const [receipt, setReceipt] = useState<string | null>(null);
  const [candidateRevalidation, setCandidateRevalidation] =
    useState<CandidateRevalidation | null>(null);
  const [permissionProblem, setPermissionProblem] = useState<ApiProblem | null>(
    null,
  );

  useLayoutEffect(() => {
    scopeActiveRef.current = true;
    return () => {
      scopeActiveRef.current = false;
    };
  }, []);

  const candidateQueryKey = [
    "ticket",
    ticket.number,
    "assignees",
    debouncedSearch,
  ] as const;
  const candidates = useQuery({
    queryKey: candidateQueryKey,
    queryFn: () => ticketsApi.assignees(ticket.number, debouncedSearch),
    enabled: ticket.capabilities.can_assign,
  });
  const candidateOptions = candidates.data?.results ?? [];
  if (candidates.data !== undefined) {
    candidateDirectoryReadyRef.current = true;
  }
  for (const candidate of candidateOptions) {
    candidateSnapshots.current.set(candidate.id, candidate);
  }

  const requestIsCurrent = (values: AssignmentMutationInput) => {
    const currentTicket = currentTicketRef.current;
    return (
      scopeActiveRef.current &&
      values.requestId === activeRequestIdRef.current &&
      values.ticketNumber === scopeTicketNumberRef.current &&
      values.ticketNumber === currentTicket.number &&
      values.expectedUpdatedAt === currentTicket.updatedAt
    );
  };

  const mutation = useMutation({
    mutationFn: (values: AssignmentMutationInput) =>
      ticketsApi.assign(values.ticketNumber, {
        assignee_id: values.selected?.id ?? null,
        expected_updated_at: values.expectedUpdatedAt,
        reason: values.submittedReason,
      }),
    onSuccess: async (response, values) => {
      if (
        !requestIsCurrent(values) ||
        response.ticket.number !== values.ticketNumber ||
        response.receipt.ticket_number !== values.ticketNumber
      ) {
        return;
      }
      onUpdated(response.ticket);
      const summary = receiptSummary(response.receipt);
      setReceipt(summary);
      toast.success(summary);
      setProposal(undefined);
      setReason("");
      await onActivityChanged?.();
    },
    onError: (error, values) => {
      if (!requestIsCurrent(values)) return;
      const problem = apiProblem(error);
      if (error instanceof ApiError && error.status === 403) {
        setPermissionProblem(problem);
        setProposal(undefined);
        setReason("");
        window.setTimeout(() => returnFocusRef.current?.focus(), 0);
        return;
      }
      if (isTargetEligibilityProblem(error, problem)) {
        setCandidateRevalidation({
          dataUpdatedAt: candidates.dataUpdatedAt,
        });
        void queryClient
          .invalidateQueries({
            queryKey: ["ticket", values.ticketNumber, "assignees"],
          })
          .then(() => {
            if (!requestIsCurrent(values)) return;
            const queryState = queryClient.getQueryState(candidateQueryKey);
            if (queryState?.status === "success") {
              setCandidateRevalidation(null);
            }
          });
      }
      if (problem?.fields.reason?.length) {
        window.setTimeout(() => {
          document
            .getElementById(`assignment-reason-${values.ticketNumber}`)
            ?.focus();
        }, 0);
      }
    },
    onSettled: (_response, _error, values) => {
      if (
        scopeActiveRef.current &&
        activeRequestIdRef.current === values.requestId
      ) {
        submitLockRef.current = false;
      }
    },
  });

  useLayoutEffect(() => {
    const previousTicket = currentTicketRef.current;
    const versionChanged =
      previousTicket.number !== ticket.number ||
      previousTicket.updatedAt !== ticket.updated_at;
    currentTicketRef.current = {
      number: ticket.number,
      updatedAt: ticket.updated_at,
    };
    if (versionChanged) {
      activeRequestIdRef.current = null;
      submitLockRef.current = false;
      mutation.reset();
    }
  }, [mutation, ticket.number, ticket.updated_at]);

  const currentId = ticket.assignee_detail?.id ?? null;
  const selectedId =
    proposal === undefined ? currentId : (proposal.selected?.id ?? null);
  const action =
    proposal === undefined
      ? null
      : proposedAction(currentId, proposal.selected);
  const reasonRequired = action === "transfer" || action === "unassign";
  const mutationIsCurrent =
    mutation.variables === undefined || requestIsCurrent(mutation.variables);
  const disabled = mutation.isPending && mutationIsCurrent;
  const mutationProblem = mutationIsCurrent ? apiProblem(mutation.error) : null;
  const stale =
    mutationIsCurrent &&
    mutation.error instanceof ApiError &&
    mutation.error.status === 409;
  const forbidden =
    mutationIsCurrent &&
    mutation.error instanceof ApiError &&
    mutation.error.status === 403;
  const missing =
    mutationIsCurrent &&
    mutation.error instanceof ApiError &&
    mutation.error.status === 404;
  const targetEligibilityChanged = isTargetEligibilityProblem(
    mutationIsCurrent ? mutation.error : null,
    mutationProblem,
  );
  const candidateProblem = apiProblem(candidates.error);
  const candidateDirectoryUnavailable =
    ticket.capabilities.can_assign &&
    (!candidateDirectoryReadyRef.current || candidates.isError);
  const candidateConfirmationUnavailable =
    candidateDirectoryUnavailable || candidates.isFetching;
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
  const proposalTargetMissing =
    targetEligibilityChanged &&
    proposal?.source === "directory" &&
    proposal.selected !== null &&
    !candidateOptions.some(
      (candidate) => candidate.id === proposal.selected?.id,
    );
  const directoryProposalBlocked =
    proposal?.source === "directory" &&
    (candidateConfirmationUnavailable ||
      candidateRevalidation !== null ||
      proposalTargetMissing);

  useEffect(() => {
    if (
      candidateRevalidation !== null &&
      candidates.isSuccess &&
      !candidates.isFetching &&
      candidates.dataUpdatedAt > candidateRevalidation.dataUpdatedAt
    ) {
      setCandidateRevalidation(null);
    }
  }, [
    candidateRevalidation,
    candidates.dataUpdatedAt,
    candidates.isFetching,
    candidates.isSuccess,
  ]);

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
      (source === "directory" &&
        (candidateConfirmationUnavailable || candidateRevalidation !== null)) ||
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
      directoryProposalBlocked ||
      submitLockRef.current ||
      disabled ||
      (reasonRequired && !reason.trim())
    ) {
      return;
    }
    submitLockRef.current = true;
    const requestId = nextRequestIdRef.current;
    nextRequestIdRef.current += 1;
    activeRequestIdRef.current = requestId;
    mutation.mutate({
      selected: proposal.selected,
      submittedReason: reason.trim(),
      ticketNumber: ticket.number,
      expectedUpdatedAt: ticket.updated_at,
      requestId,
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
          disabled={
            disabled ||
            candidateDirectoryUnavailable ||
            candidateRevalidation !== null
          }
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
                  <span className="font-medium">
                    {ticket.number} — {ticket.title}
                  </span>
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
                {proposal.selected ? (
                  <p>
                    <span className="text-muted-foreground">
                      Designation / team:
                    </span>{" "}
                    <span className="font-medium">
                      {assigneeContext(proposal.selected)}
                    </span>
                  </p>
                ) : null}
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
              ) : missing ? (
                <Alert variant="destructive">
                  <AlertCircle aria-hidden="true" />
                  <AlertTitle>Ticket is no longer available</AlertTitle>
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
              ) : targetEligibilityChanged ? (
                <Alert variant="destructive">
                  <AlertCircle aria-hidden="true" />
                  <AlertTitle>
                    Selected staff member is no longer eligible
                  </AlertTitle>
                  <AlertDescription>
                    {mutationProblem ? (
                      <>
                        <p>{mutationProblem.detail}</p>
                        {mutationProblem.fields.assignee_id?.map((message) => (
                          <p key={message}>{message}</p>
                        ))}
                        <p>Reference: {mutationProblem.correlation_id}</p>
                      </>
                    ) : (
                      mutationErrorDetail
                    )}
                  </AlertDescription>
                </Alert>
              ) : mutation.isError && mutationIsCurrent && !forbidden ? (
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
                {stale || missing ? (
                  <Button type="button" disabled={disabled} onClick={onReload}>
                    Reload
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    disabled={
                      disabled ||
                      !proposalAllowed ||
                      directoryProposalBlocked ||
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
