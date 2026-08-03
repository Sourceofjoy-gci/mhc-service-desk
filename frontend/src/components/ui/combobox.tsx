import { useEffect, useMemo, useRef, useState } from "react";
import { Combobox } from "@base-ui/react/combobox";
import { CheckIcon, ChevronDownIcon, Loader2Icon } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field";
import type { TicketAssignee } from "@/lib/api";
import { cn } from "@/lib/utils";

interface StaffMemberOption {
  kind: "staff";
  assignee: TicketAssignee;
}

interface UnassignedOption {
  kind: "unassigned";
}

type StaffOption = StaffMemberOption | UnassignedOption;

const unassignedOption: UnassignedOption = { kind: "unassigned" };

export interface StaffComboboxProps {
  id: string;
  label: string;
  value: string | null;
  options: TicketAssignee[];
  onValueChange: (value: string | null) => void;
  onSearchChange: (value: string) => void;
  allowUnassigned: boolean;
  disabled?: boolean;
  loading?: boolean;
  error?: string;
}

function optionKey(option: StaffOption) {
  return option.kind === "unassigned" ? "unassigned" : option.assignee.id;
}

function optionLabel(option: StaffOption) {
  return option.kind === "unassigned"
    ? "Unassigned"
    : option.assignee.display_name;
}

function optionSearchText(option: StaffOption) {
  if (option.kind === "unassigned") {
    return "unassigned";
  }

  const {
    display_name,
    username,
    designations,
    team_labels,
    role_summaries = [],
  } = option.assignee;
  return [display_name, username, ...designations, ...team_labels, ...role_summaries]
    .join(" ")
    .toLocaleLowerCase();
}

function matchesSearch(option: StaffOption, query: string) {
  return optionSearchText(option).includes(query.trim().toLocaleLowerCase());
}

function supportingContext(assignee: TicketAssignee) {
  const designation = assignee.designations.join(", ");
  const team = assignee.team_labels.join(", ");
  return (
    [designation, team].filter(Boolean).join(" · ") || `@${assignee.username}`
  );
}

function StaffResultsStatus({
  loading,
  error,
}: Pick<StaffComboboxProps, "loading" | "error">) {
  const filteredItems = Combobox.useFilteredItems<StaffOption>();
  const hasStaffResults = filteredItems.some(
    (option) => option.kind === "staff",
  );

  return (
    <Combobox.Status className="text-sm text-muted-foreground">
      {loading ? (
        <div className="flex items-center gap-2 px-2.5 py-2">
          <Loader2Icon
            aria-hidden="true"
            className="size-4 animate-spin motion-reduce:animate-none"
          />
          <span>Loading eligible team members…</span>
        </div>
      ) : !error && !hasStaffResults ? (
        <div className="px-2.5 py-3">No eligible team members found</div>
      ) : null}
    </Combobox.Status>
  );
}

export function StaffCombobox({
  id,
  label,
  value,
  options,
  onValueChange,
  onSearchChange,
  allowUnassigned,
  disabled = false,
  loading = false,
  error,
}: StaffComboboxProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popupLayerRef = useRef<HTMLDivElement>(null);
  const [selectedSnapshot, setSelectedSnapshot] =
    useState<StaffMemberOption | null>(null);
  const errorId = `${id}-error`;
  const staffOptions = useMemo<StaffMemberOption[]>(
    () => options.map((assignee) => ({ kind: "staff", assignee })),
    [options],
  );
  const items = useMemo(
    () =>
      allowUnassigned
        ? ([unassignedOption, ...staffOptions] satisfies StaffOption[])
        : staffOptions,
    [allowUnassigned, staffOptions],
  );
  const selectedStaffOption = staffOptions.find(
    (option) => option.assignee.id === value,
  );
  useEffect(() => {
    setSelectedSnapshot((currentSnapshot) => {
      const nextSnapshot =
        value === null
          ? null
          : (selectedStaffOption ??
            (currentSnapshot?.assignee.id === value ? currentSnapshot : null));
      return currentSnapshot === nextSnapshot ? currentSnapshot : nextSnapshot;
    });
  }, [selectedStaffOption, value]);

  const selectedOption: StaffOption | null =
    value === null
      ? allowUnassigned
        ? unassignedOption
        : null
      : (selectedStaffOption ??
        (selectedSnapshot?.assignee.id === value ? selectedSnapshot : null));

  return (
    <Combobox.Root<StaffOption>
      id={id}
      items={items}
      value={selectedOption}
      disabled={disabled}
      autoHighlight
      filter={matchesSearch}
      itemToStringLabel={optionLabel}
      isItemEqualToValue={(option, selected) =>
        optionKey(option) === optionKey(selected)
      }
      onValueChange={(nextOption) => {
        onValueChange(
          nextOption === null || nextOption.kind === "unassigned"
            ? null
            : nextOption.assignee.id,
        );
      }}
      onInputValueChange={(query, details) => {
        if (
          details.reason === "input-change" ||
          details.reason === "input-clear"
        ) {
          onSearchChange(query);
        }
      }}
    >
      <div
        data-slot="staff-combobox"
        data-disabled={disabled || undefined}
        className="flex w-full flex-col gap-2"
      >
        <Combobox.Label className="w-fit cursor-default text-sm leading-snug font-medium select-none data-disabled:opacity-50">
          {label}
        </Combobox.Label>
        <Combobox.Trigger
          ref={triggerRef}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          aria-busy={loading || undefined}
          className={cn(
            buttonVariants({ variant: "outline" }),
            "w-full justify-between px-2.5 font-normal",
          )}
        >
          <Combobox.Value placeholder="Select eligible team member" />
          <Combobox.Icon className="text-muted-foreground transition-transform duration-100 data-popup-open:rotate-180 motion-reduce:transition-none">
            <ChevronDownIcon aria-hidden="true" />
          </Combobox.Icon>
        </Combobox.Trigger>

        <div
          ref={popupLayerRef}
          data-slot="staff-combobox-popup-layer"
          className="relative z-40"
        />
        <Combobox.Portal container={popupLayerRef}>
          <Combobox.Positioner
            align="start"
            sideOffset={4}
            className="z-40 max-w-(--available-width) outline-none"
          >
            <Combobox.Popup
              initialFocus
              finalFocus={triggerRef}
              aria-label={`${label} options`}
              aria-busy={loading || undefined}
              className="w-(--anchor-width) min-w-64 origin-(--transform-origin) overflow-hidden rounded-lg bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10 transition-[transform,opacity] duration-100 data-starting-style:scale-95 data-starting-style:opacity-0 data-ending-style:scale-95 data-ending-style:opacity-0 motion-reduce:transition-none"
            >
              <Combobox.Input
                id={`${id}-search`}
                aria-label={`Search ${label}`}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? errorId : undefined}
                placeholder="Search by name, username, designation, or team"
                className="h-8 w-full min-w-0 rounded-t-lg border-b border-input bg-transparent px-2.5 py-1 text-base outline-none placeholder:text-muted-foreground focus-visible:border-ring disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive md:text-sm dark:bg-input/30 dark:disabled:bg-input/80"
              />
              <StaffResultsStatus loading={loading} error={error} />
              <Combobox.List className="max-h-[min(18rem,var(--available-height))] overflow-y-auto overscroll-contain p-1 scroll-py-1 outline-none data-empty:p-0">
                {(option: StaffOption) => (
                  <Combobox.Item
                    key={optionKey(option)}
                    value={option}
                    data-unassigned={option.kind === "unassigned" || undefined}
                    className="relative grid min-w-(--anchor-width) cursor-default grid-cols-[1rem_minmax(0,1fr)] items-center gap-x-2 rounded-md px-2 py-1.5 text-sm outline-none select-none data-highlighted:bg-muted data-highlighted:text-foreground data-selected:text-foreground data-unassigned:border-b data-unassigned:border-border data-unassigned:pb-2 data-unassigned:mb-1"
                  >
                    <Combobox.ItemIndicator
                      keepMounted
                      className="col-start-1 row-span-3 flex size-4 items-center justify-center text-primary opacity-0 data-selected:opacity-100"
                    >
                      <CheckIcon aria-hidden="true" className="size-3.5" />
                    </Combobox.ItemIndicator>
                    {option.kind === "unassigned" ? (
                      <span className="col-start-2 font-medium">
                        Unassigned
                      </span>
                    ) : (
                      <>
                        <span className="col-start-2 truncate font-medium">
                          {option.assignee.display_name}
                        </span>
                        <span className="col-start-2 truncate text-xs text-muted-foreground">
                          {supportingContext(option.assignee)}
                        </span>
                        {option.assignee.role_summaries?.map((summary) => (
                          <span
                            key={summary}
                            className="col-start-2 mt-0.5 max-w-xl text-xs text-muted-foreground"
                          >
                            {summary}
                          </span>
                        ))}
                      </>
                    )}
                  </Combobox.Item>
                )}
              </Combobox.List>
            </Combobox.Popup>
          </Combobox.Positioner>
        </Combobox.Portal>

        <FieldError id={errorId}>{error}</FieldError>
      </div>
    </Combobox.Root>
  );
}
