import { Suspense, useState } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { TicketAssignee } from "@/lib/api";
import { StaffCombobox } from "./combobox";

const accountant: TicketAssignee = {
  id: "00000000-0000-0000-0000-000000000012",
  username: "amina.accountant",
  display_name: "Amina Dlamini",
  designations: ["Accountant"],
  team_labels: ["Finance"],
};

const estateExaminer: TicketAssignee = {
  id: "00000000-0000-0000-0000-000000000013",
  username: "themba.examiner",
  display_name: "Themba Nkosi",
  designations: ["Estate Examiner"],
  team_labels: ["Estate Administration"],
};

const options = [accountant, estateExaminer];
const pendingRender = new Promise<void>(() => undefined);

function SuspendRender({ suspend }: { suspend: boolean }) {
  if (suspend) {
    throw pendingRender;
  }

  return null;
}

interface HarnessProps {
  initialValue?: string | null;
  options?: TicketAssignee[];
  allowUnassigned?: boolean;
  disabled?: boolean;
  loading?: boolean;
  error?: string;
  onValueChange?: (value: string | null) => void;
  onSearchChange?: (value: string) => void;
}

function Harness({
  initialValue = null,
  options: candidateOptions = options,
  allowUnassigned = true,
  disabled,
  loading,
  error,
  onValueChange = () => undefined,
  onSearchChange = () => undefined,
}: HarnessProps) {
  const [value, setValue] = useState<string | null>(initialValue);

  return (
    <StaffCombobox
      id="ticket-assignee"
      label="Assignee"
      value={value}
      options={candidateOptions}
      onValueChange={(nextValue) => {
        setValue(nextValue);
        onValueChange(nextValue);
      }}
      onSearchChange={onSearchChange}
      allowUnassigned={allowUnassigned}
      disabled={disabled}
      loading={loading}
      error={error}
    />
  );
}

async function openStaffCombobox(user: ReturnType<typeof userEvent.setup>) {
  const trigger = screen.getByRole("combobox", { name: "Assignee" });
  await user.click(trigger);
  return {
    trigger,
    search: await screen.findByRole("combobox", {
      name: "Search Assignee",
    }),
  };
}

describe("StaffCombobox", () => {
  it("exposes its label and controlled current value on the trigger", () => {
    render(<Harness initialValue={accountant.id} />);

    const trigger = screen.getByRole("combobox", { name: "Assignee" });
    expect(trigger).toHaveTextContent("Amina Dlamini");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("preserves an omitted selected assignee as display-only context", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    const onSearchChange = vi.fn();
    const { rerender } = render(
      <StaffCombobox
        id="ticket-assignee"
        label="Assignee"
        value={accountant.id}
        options={options}
        onValueChange={onValueChange}
        onSearchChange={onSearchChange}
        allowUnassigned={false}
      />,
    );

    rerender(
      <StaffCombobox
        id="ticket-assignee"
        label="Assignee"
        value={accountant.id}
        options={[estateExaminer]}
        onValueChange={onValueChange}
        onSearchChange={onSearchChange}
        allowUnassigned={false}
      />,
    );

    const trigger = screen.getByRole("combobox", { name: "Assignee" });
    expect(trigger).toHaveTextContent("Amina Dlamini");
    expect(onValueChange).not.toHaveBeenCalled();
    const { search } = await openStaffCombobox(user);
    expect(
      screen.queryByRole("option", { name: /Amina Dlamini/ }),
    ).not.toBeInTheDocument();
    const eligibleOption = screen.getByRole("option", {
      name: /Themba Nkosi/,
    });

    await waitFor(() => expect(search).toHaveFocus());
    await user.keyboard("{ArrowDown}");
    await waitFor(() =>
      expect(eligibleOption).toHaveAttribute("data-highlighted"),
    );
    expect(onValueChange).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");

    expect(onValueChange).toHaveBeenCalledTimes(1);
    expect(onValueChange).toHaveBeenNthCalledWith(1, estateExaminer.id);
  });

  it("ignores selected staff observed only in an interrupted render", () => {
    const props = {
      id: "ticket-assignee",
      label: "Assignee",
      onValueChange: vi.fn(),
      onSearchChange: vi.fn(),
      allowUnassigned: false,
    };
    const { rerender } = render(
      <Suspense fallback={<div>Updating assignee</div>}>
        <StaffCombobox
          {...props}
          value={accountant.id}
          options={[accountant]}
        />
        <SuspendRender suspend={false} />
      </Suspense>,
    );
    expect(
      screen.getByRole("combobox", { name: "Assignee" }),
    ).toHaveTextContent("Amina Dlamini");

    rerender(
      <Suspense fallback={<div>Updating assignee</div>}>
        <StaffCombobox
          {...props}
          value={estateExaminer.id}
          options={[estateExaminer]}
        />
        <SuspendRender suspend />
      </Suspense>,
    );
    expect(screen.getByText("Updating assignee")).toBeVisible();

    rerender(
      <Suspense fallback={<div>Updating assignee</div>}>
        <StaffCombobox {...props} value={estateExaminer.id} options={[]} />
        <SuspendRender suspend={false} />
      </Suspense>,
    );
    expect(
      screen.getByRole("combobox", { name: "Assignee" }),
    ).toHaveTextContent("Select eligible team member");
  });

  it("replaces the display snapshot when the controlled value changes", () => {
    const props = {
      id: "ticket-assignee",
      label: "Assignee",
      onValueChange: vi.fn(),
      onSearchChange: vi.fn(),
      allowUnassigned: false,
    };
    const { rerender } = render(
      <StaffCombobox {...props} value={accountant.id} options={[accountant]} />,
    );

    rerender(<StaffCombobox {...props} value={accountant.id} options={[]} />);
    expect(
      screen.getByRole("combobox", { name: "Assignee" }),
    ).toHaveTextContent("Amina Dlamini");

    rerender(<StaffCombobox {...props} value="unknown-staff" options={[]} />);
    expect(
      screen.getByRole("combobox", { name: "Assignee" }),
    ).toHaveTextContent("Select eligible team member");

    rerender(
      <StaffCombobox
        {...props}
        value={estateExaminer.id}
        options={[estateExaminer]}
      />,
    );
    expect(
      screen.getByRole("combobox", { name: "Assignee" }),
    ).toHaveTextContent("Themba Nkosi");

    rerender(
      <StaffCombobox {...props} value={estateExaminer.id} options={[]} />,
    );
    expect(
      screen.getByRole("combobox", { name: "Assignee" }),
    ).toHaveTextContent("Themba Nkosi");

    rerender(<StaffCombobox {...props} value={null} options={[]} />);
    expect(
      screen.getByRole("combobox", { name: "Assignee" }),
    ).toHaveTextContent("Select eligible team member");

    rerender(
      <StaffCombobox {...props} value={estateExaminer.id} options={[]} />,
    );
    expect(
      screen.getByRole("combobox", { name: "Assignee" }),
    ).toHaveTextContent("Select eligible team member");
  });

  it("selects an eligible team member with ArrowDown and Enter", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <Harness
        allowUnassigned={false}
        options={[accountant]}
        onValueChange={onValueChange}
      />,
    );
    const { search, trigger } = await openStaffCombobox(user);
    await waitFor(() => expect(search).toHaveFocus());
    await user.keyboard("{ArrowDown}");
    const firstOption = screen.getByRole("option", { name: /Amina Dlamini/ });
    await waitFor(() =>
      expect(firstOption).toHaveAttribute("data-highlighted"),
    );
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(onValueChange).toHaveBeenCalledWith(accountant.id),
    );
    expect(trigger).toHaveTextContent("Amina Dlamini");
  });

  it.each(["finance", "accountant", "amina.accountant", "Amina Dlamini"])(
    "finds the Accountant by searching for %s",
    async (query) => {
      const user = userEvent.setup();
      const onSearchChange = vi.fn();
      render(
        <Harness allowUnassigned={false} onSearchChange={onSearchChange} />,
      );
      const { search } = await openStaffCombobox(user);

      await user.type(search, query);

      const option = screen.getByRole("option", { name: /Amina Dlamini/ });
      expect(option).toBeVisible();
      expect(
        screen.queryByRole("option", { name: /Themba Nkosi/ }),
      ).not.toBeInTheDocument();
      expect(onSearchChange).toHaveBeenLastCalledWith(query);
    },
  );

  it("finds an Estate Examiner by team and renders staff context", async () => {
    const user = userEvent.setup();
    render(<Harness allowUnassigned={false} />);
    const { search } = await openStaffCombobox(user);

    await user.type(search, "estate administration");

    const option = screen.getByRole("option", { name: /Themba Nkosi/ });
    expect(within(option).getByText("Themba Nkosi")).toBeVisible();
    expect(
      within(option).getByText("Estate Examiner · Estate Administration"),
    ).toBeVisible();
    expect(
      screen.queryByRole("option", { name: /Amina Dlamini/ }),
    ).not.toBeInTheDocument();
  });

  it("renders designation and team as supporting context", async () => {
    const user = userEvent.setup();
    render(<Harness initialValue={accountant.id} />);
    await openStaffCombobox(user);

    const option = screen.getByRole("option", { name: /Amina Dlamini/ });
    expect(within(option).getByText("Amina Dlamini")).toBeVisible();
    expect(within(option).getByText("Accountant · Finance")).toBeVisible();
  });

  it("keeps Unassigned as a distinct selectable option", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <Harness initialValue={accountant.id} onValueChange={onValueChange} />,
    );
    await openStaffCombobox(user);

    fireEvent.click(screen.getByRole("option", { name: "Unassigned" }));

    expect(onValueChange).toHaveBeenCalledWith(null);
    expect(
      screen.getByRole("combobox", { name: "Assignee" }),
    ).toHaveTextContent("Unassigned");
  });

  it("announces when no eligible team members are available", async () => {
    const user = userEvent.setup();
    render(<Harness options={[]} allowUnassigned={false} />);
    await openStaffCombobox(user);

    expect(screen.getByText(/No eligible team members found/)).toBeVisible();
  });

  it("announces no staff while keeping Unassigned selectable", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <Harness options={[]} allowUnassigned onValueChange={onValueChange} />,
    );
    await openStaffCombobox(user);

    expect(screen.getByText(/No eligible team members found/)).toBeVisible();
    const unassigned = screen.getByRole("option", { name: "Unassigned" });
    expect(unassigned).toBeVisible();
    fireEvent.click(unassigned);
    expect(onValueChange).toHaveBeenCalledWith(null);
  });

  it("announces no staff match when search retains only Unassigned", async () => {
    const user = userEvent.setup();
    render(<Harness allowUnassigned />);
    const { search } = await openStaffCombobox(user);

    await user.type(search, "unassigned");

    expect(screen.getByText(/No eligible team members found/)).toBeVisible();
    expect(screen.getByRole("option", { name: "Unassigned" })).toBeVisible();
    expect(screen.queryByRole("option", { name: /Amina Dlamini/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /Themba Nkosi/ })).toBeNull();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const { search, trigger } = await openStaffCombobox(user);
    await waitFor(() => expect(search).toHaveFocus());

    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(trigger).toHaveAttribute("aria-expanded", "false"),
    );
    expect(trigger).toHaveFocus();
  });

  it("exposes disabled, loading, and error states accessibly", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness disabled />);
    const disabledTrigger = screen.getByRole("combobox", { name: "Assignee" });
    expect(disabledTrigger).toBeDisabled();

    rerender(<Harness loading />);
    const { trigger: loadingTrigger } = await openStaffCombobox(user);
    expect(loadingTrigger).toHaveAttribute("aria-busy", "true");
    expect(screen.getByText(/Loading eligible team members/)).toBeVisible();

    rerender(<Harness error="Candidate search failed" />);
    const errorTrigger = screen.getByRole("combobox", { name: "Assignee" });
    expect(errorTrigger).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Candidate search failed",
    );
  });
});
