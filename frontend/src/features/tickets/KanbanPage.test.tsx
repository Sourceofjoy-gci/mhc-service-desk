import type { ReactNode } from "react";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { KanbanData, TicketSummary } from "@/lib/api";
import { renderWithProviders } from "@/test/render";
import KanbanPage from "./KanbanPage";

const harness = vi.hoisted(() => ({
  kanban: vi.fn(),
  transition: vi.fn(),
}));

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
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    isDragging: false,
  }),
  useDroppable: () => ({ setNodeRef: vi.fn(), isOver: false }),
  useSensor: vi.fn(),
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
  harness.kanban.mockReset().mockResolvedValue(KANBAN);
  harness.transition.mockReset().mockResolvedValue({});
});

describe("Kanban server-approved transitions", () => {
  it("submits an allowed server code with the ticket timestamp", async () => {
    const user = userEvent.setup();
    renderWithProviders(<KanbanPage />);

    await user.click(await screen.findByRole("button", { name: "Drag to allowed" }));

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
});
