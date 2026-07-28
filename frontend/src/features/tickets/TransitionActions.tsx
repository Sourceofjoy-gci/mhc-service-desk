import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  apiProblem,
  ticketsApi,
  type AvailableTransition,
  type TicketDetail,
  type TicketTransitionRequest,
} from "@/lib/api";

interface TransitionActionsProps {
  ticket: TicketDetail;
  onUpdated: (ticket: TicketDetail) => void;
}

type TransitionValues = Omit<TicketTransitionRequest, "updated_at">;

interface FormValues {
  reason: string;
  resolution_code: string;
  resolution_summary: string;
}

const EMPTY_VALUES: FormValues = {
  reason: "",
  resolution_code: "",
  resolution_summary: "",
};

function firstMessages(fields: Record<string, string[]> | undefined) {
  return fields ?? {};
}

export function TransitionActions({
  ticket,
  onUpdated,
}: TransitionActionsProps) {
  const [chosen, setChosen] = useState<AvailableTransition | null>(null);
  const [values, setValues] = useState<FormValues>(EMPTY_VALUES);
  const [clientErrors, setClientErrors] = useState<Record<string, string[]>>({});
  const [isReloading, setIsReloading] = useState(false);
  const [reloadError, setReloadError] = useState<unknown>(null);

  const transition = useMutation({
    mutationFn: (submitted: TransitionValues) =>
      ticketsApi.transition(ticket.number, {
        ...submitted,
        updated_at: ticket.updated_at,
      }),
    onSuccess: (refreshedTicket) => {
      onUpdated(refreshedTicket);
      setChosen(null);
    },
  });

  const choose = (next: AvailableTransition) => {
    if (transition.isPending) return;
    transition.reset();
    setClientErrors({});
    setReloadError(null);
    setValues(EMPTY_VALUES);
    setChosen(next);
  };

  const close = () => {
    if (transition.isPending || isReloading) return;
    setChosen(null);
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!chosen || transition.isPending) return;

    const errors: Record<string, string[]> = {};
    if (chosen.requires_reason && !values.reason.trim()) {
      errors.reason = ["Reason is required."];
    }
    if (chosen.requires_resolution && !values.resolution_code.trim()) {
      errors.resolution_code = ["Resolution code is required."];
    }
    if (chosen.requires_resolution && !values.resolution_summary.trim()) {
      errors.resolution_summary = ["Resolution summary is required."];
    }
    setClientErrors(errors);
    if (Object.keys(errors).length > 0) return;

    const submitted: TransitionValues = { to_status: chosen.to_status };
    if (chosen.requires_reason) submitted.reason = values.reason.trim();
    if (chosen.requires_resolution) {
      submitted.resolution_code = values.resolution_code.trim();
      submitted.resolution_summary = values.resolution_summary.trim();
    }
    transition.mutate(submitted);
  };

  const problem = apiProblem(transition.error);
  const stale = problem?.code === "stale_ticket" && transition.error !== null;
  const fieldErrors = firstMessages(problem?.fields ?? clientErrors);

  const reload = async () => {
    if (isReloading) return;
    setIsReloading(true);
    setReloadError(null);
    try {
      const refreshedTicket = await ticketsApi.get(ticket.number);
      onUpdated(refreshedTicket);
      setChosen(null);
    } catch (error) {
      setReloadError(error);
    } finally {
      setIsReloading(false);
    }
  };

  const reloadProblem = apiProblem(reloadError);
  const disabled = transition.isPending || isReloading;

  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Ticket actions">
      {ticket.available_transitions.map((available) => (
        <Button
          key={available.to_status}
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => choose(available)}
        >
          {available.label}
        </Button>
      ))}

      <Dialog
        open={chosen !== null}
        onOpenChange={(open) => {
          if (!open) close();
        }}
      >
        <DialogContent showCloseButton={!disabled}>
          {chosen ? (
            <form onSubmit={submit} className="contents">
              <DialogHeader>
                <DialogTitle>{chosen.label}</DialogTitle>
                <DialogDescription>
                  Confirm this ticket transition before it is applied.
                </DialogDescription>
              </DialogHeader>

              <FieldGroup className="gap-3">
                {chosen.requires_reason ? (
                  <Field data-invalid={Boolean(fieldErrors.reason)}>
                    <FieldLabel htmlFor="transition-reason">Reason</FieldLabel>
                    <Textarea
                      id="transition-reason"
                      name="reason"
                      required
                      disabled={disabled}
                      aria-invalid={Boolean(fieldErrors.reason)}
                      value={values.reason}
                      onChange={(event) =>
                        setValues((current) => ({
                          ...current,
                          reason: event.target.value,
                        }))
                      }
                    />
                    <FieldError
                      errors={fieldErrors.reason?.map((message) => ({ message }))}
                    />
                  </Field>
                ) : null}

                {chosen.requires_resolution ? (
                  <>
                    <Field data-invalid={Boolean(fieldErrors.resolution_code)}>
                      <FieldLabel htmlFor="transition-resolution-code">
                        Resolution code
                      </FieldLabel>
                      <Input
                        id="transition-resolution-code"
                        name="resolution_code"
                        required
                        disabled={disabled}
                        aria-invalid={Boolean(fieldErrors.resolution_code)}
                        value={values.resolution_code}
                        onChange={(event) =>
                          setValues((current) => ({
                            ...current,
                            resolution_code: event.target.value,
                          }))
                        }
                      />
                      <FieldError
                        errors={fieldErrors.resolution_code?.map((message) => ({
                          message,
                        }))}
                      />
                    </Field>
                    <Field data-invalid={Boolean(fieldErrors.resolution_summary)}>
                      <FieldLabel htmlFor="transition-resolution-summary">
                        Resolution summary
                      </FieldLabel>
                      <Textarea
                        id="transition-resolution-summary"
                        name="resolution_summary"
                        required
                        disabled={disabled}
                        aria-invalid={Boolean(fieldErrors.resolution_summary)}
                        value={values.resolution_summary}
                        onChange={(event) =>
                          setValues((current) => ({
                            ...current,
                            resolution_summary: event.target.value,
                          }))
                        }
                      />
                      <FieldError
                        errors={fieldErrors.resolution_summary?.map((message) => ({
                          message,
                        }))}
                      />
                    </Field>
                  </>
                ) : null}
              </FieldGroup>

              {stale ? (
                <Alert variant="destructive">
                  <AlertCircle data-icon="inline-start" aria-hidden />
                  <AlertTitle>This ticket changed since you opened it</AlertTitle>
                  <AlertDescription>
                    Reload the current ticket before choosing another action.
                  </AlertDescription>
                </Alert>
              ) : transition.isError && problem ? (
                <Alert variant="destructive">
                  <AlertCircle data-icon="inline-start" aria-hidden />
                  <AlertTitle>Could not update the ticket</AlertTitle>
                  <AlertDescription>
                    {problem.detail} Reference: {problem.correlation_id}
                  </AlertDescription>
                </Alert>
              ) : transition.isError ? (
                <Alert variant="destructive">
                  <AlertCircle data-icon="inline-start" aria-hidden />
                  <AlertTitle>Could not update the ticket</AlertTitle>
                  <AlertDescription>Please try again.</AlertDescription>
                </Alert>
              ) : null}

              {reloadError ? (
                <Alert variant="destructive">
                  <AlertCircle data-icon="inline-start" aria-hidden />
                  <AlertTitle>Could not reload the ticket</AlertTitle>
                  <AlertDescription>
                    {reloadProblem?.detail ?? "Please try again."}
                    {reloadProblem
                      ? ` Reference: ${reloadProblem.correlation_id}`
                      : ""}
                  </AlertDescription>
                </Alert>
              ) : null}

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  disabled={disabled}
                  onClick={close}
                >
                  Cancel
                </Button>
                {stale ? (
                  <Button type="button" disabled={disabled} onClick={reload}>
                    {isReloading ? "Reloading…" : "Reload"}
                  </Button>
                ) : (
                  <Button type="submit" disabled={disabled}>
                    {transition.isPending
                      ? "Updating…"
                      : `Confirm ${chosen.label}`}
                  </Button>
                )}
              </DialogFooter>
            </form>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
