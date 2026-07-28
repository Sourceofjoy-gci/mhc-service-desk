import type { ReactNode } from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type KanbanData, type TicketSummary } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import KanbanPage from "./KanbanPage";

const harness = vi.hoisted(() => ({
  groups: ["ops-agents"] as string[],
  kanban: vi.fn(),
  transition: vi.fn(),
  dragPointerDown: vi.fn(),
  useSensor: vi.fn(),
}));

vi.mock("@/features/auth/AuthProvider", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/features/auth/AuthProvider")>();
  return {
    ...original,
    useAuth: () => ({ user: { groups: harness.groups } }),
  };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    ticketsApi: {
      ...original.ticketsApi,
      kanban: harness.kanban,
      transition: harness.transition,
    },
  };
});

vi.mock("@dnd-kit/core", () => ({
  DndContext: ({
    children,
    onDragEnd,
  }: {
    children: ReactNode;
    onDragEnd: (event: {
      active: { id: string };
      over: { id: string };
    }) => void;
  }) => (
    <>
      <button
        type="button"
        onClick={() =>
          onDragEnd({
            active: { id: "ticket-1" },
            over: { id: "in_progress" },
          })
        }
      >
        Drag to allowed
      </button>
      <button
        type="button"
        onClick={() =>
          onDragEnd({
            active: { id: "ticket-1" },
            over: { id: "resolved" },
          })
        }
      >
        Drag to disallowed
      </button>
      <button
        type="button"
        onClick={() => {
          const event = {
            active: { id: "ticket-1" },
            over: { id: "in_progress" },
          };
          onDragEnd(event);
          onDragEnd(event);
        }}
      >
        Drag twice synchronously
      </button>
      {children}
    </>
  ),
  KeyboardSensor: function KeyboardSensor() {},
  PointerSensor: function PointerSensor() {},
  useDraggable: () => ({
    attributes: { "aria-roledescription": "draggable" },
    listeners: { onPointerDown: harness.dragPointerDown },
    setNodeRef: vi.fn(),
    isDragging: false,
  }),
  useDroppable: () => ({ setNodeRef: vi.fn(), isOver: false }),
  useSensor: harness.useSensor,
  useSensors: vi.fn().mockReturnValue([]),
}));

const TICKET: TicketSummary = {
  id: "ticket-1",
  number: "MHC-2026-000001",
  domain: "operational",
  title: "Estate follow-up",
  channel: "web",
  priority: "P2",
  confidentiality: "normal",
  status_code: "assigned",
  status_name: "Assigned",
  status_public: "In progress",
  requester_name: "Naledi Dube",
  office_code: "JHB",
  service_code: "ESTATES",
  assignee: "agent-1",
  waiting_reason: "",
  created_at: "2026-07-27T08:00:00Z",
  updated_at: "2026-07-27T09:15:00Z",
  age_hours: 1.25,
  sla_health: "on_track",
  available_transition_codes: ["in_progress"],
};

const KANBAN: KanbanData = {
  columns: { assigned: [TICKET] },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

beforeEach(() => {
  harness.groups = ["ops-agents"];
  harness.kanban.mockReset().mockResolvedValue(KANBAN);
  harness.transition.mockReset().mockResolvedValue({});
  harness.dragPointerDown.mockReset();
  harness.useSensor.mockReset();
});

describe("Kanban domain scope and workflows", () => {
  it("defaults an IT-only identity to IT and renders every active IT workflow column", async () => {
    harness.groups = ["it-agents"];
    renderWithProviders(<KanbanPage />);

    await screen.findByRole("heading", { name: "Diagnosing" });
    expect(harness.kanban).toHaveBeenCalledWith("it");
    expect(screen.queryByLabelText("Domain")).not.toBeInTheDocument();
    for (const heading of [
      "Diagnosing",
      "Waiting for User",
      "Waiting for Vendor",
      "Waiting for Change",
      "Validation",
      "Resolved",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeVisible();
    }
    expect(
      screen.queryByRole("heading", { name: "Waiting for Requester" }),
    ).not.toBeInTheDocument();
  });

  it("renders the operational workflow without IT-only columns", async () => {
    renderWithProviders(<KanbanPage />);

    await screen.findByRole("heading", { name: "Waiting for Requester" });
    expect(
      screen.getByRole("heading", { name: "Waiting for Internal Unit" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Waiting for IT" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Quality Review" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "Resolved" })).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "Diagnosing" }),
    ).not.toBeInTheDocument();
  });

  it("does not load or offer a board when identity scope admits no domain", async () => {
    harness.groups = ["unknown-role"];
    renderWithProviders(<KanbanPage />);

    expect(
      await screen.findByRole("heading", { name: "Access not permitted" }),
    ).toBeVisible();
    expect(harness.kanban).not.toHaveBeenCalled();
  });
});

describe("Kanban drag affordance", () => {
  it("keeps the ticket link separate from a dedicated accessible drag handle", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KanbanPage />);

    const link = await screen.findByRole("link", { name: /Estate follow-up/i });
    const handle = screen.getByRole("button", {
      name: `Move ticket ${TICKET.number}`,
    });
    expect(link).toHaveAttribute("href", `/tickets/${TICKET.number}`);

    await user.pointer({ keys: "[MouseLeft>]", target: handle });
    expect(harness.dragPointerDown).toHaveBeenCalled();
  });

  it("requires deliberate pointer movement before starting a drag", () => {
    renderWithProviders(<KanbanPage />);

    expect(harness.useSensor).toHaveBeenCalledWith(expect.any(Function), {
      activationConstraint: { distance: 8 },
    });
  });
});

describe("Kanban server-approved transitions", () => {
  it("submits an allowed server code with the ticket timestamp", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KanbanPage />);

    await user.click(
      await screen.findByRole("button", { name: "Drag to allowed" }),
    );

    await waitFor(() =>
      expect(harness.transition).toHaveBeenCalledWith(TICKET.number, {
        to_status: "in_progress",
        updated_at: TICKET.updated_at,
      }),
    );
  });

  it("rejects a destination absent from the server-approved codes", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KanbanPage />);

    await user.click(
      await screen.findByRole("button", { name: "Drag to disallowed" }),
    );

    expect(harness.transition).not.toHaveBeenCalled();
    expect(screen.getByText("That transition is not available.")).toBeVisible();
  });

  it("prevents two same-ticket submissions before pending state rerenders", async () => {
    const pending = deferred<undefined>();
    harness.transition.mockReturnValue(pending.promise);
    const user = userEvent.setup();
    renderWithProviders(<KanbanPage />);

    await user.click(
      await screen.findByRole("button", { name: "Drag twice synchronously" }),
    );

    expect(harness.transition).toHaveBeenCalledTimes(1);
    pending.resolve(undefined);
  });

  it("distinguishes denied board access and shows its safe reference", async () => {
    harness.kanban.mockRejectedValue(
      new ApiError(403, {
        code: "permission_denied",
        detail: "This board is outside your assigned scope.",
        fields: {},
        correlation_id: "corr-kanban-403",
      }),
    );
    renderWithProviders(<KanbanPage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Kanban access denied");
    expect(alert).toHaveTextContent(
      "This board is outside your assigned scope.",
    );
    expect(alert).toHaveTextContent("corr-kanban-403");
  });

  it("offers a board refresh after a stale transition conflict", async () => {
    harness.transition.mockRejectedValue(
      new ApiError(409, {
        code: "stale_ticket",
        detail: "The ticket changed.",
        fields: {},
        correlation_id: "corr-kanban-stale",
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<KanbanPage />);

    await user.click(
      await screen.findByRole("button", { name: "Drag to allowed" }),
    );
    expect(await screen.findByText("This board is out of date")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Refresh board" }));

    await waitFor(() => expect(harness.kanban).toHaveBeenCalledTimes(2));
  });
});
