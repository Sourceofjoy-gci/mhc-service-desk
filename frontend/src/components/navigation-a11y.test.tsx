import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, lazy, type ComponentType } from "react";
import { Link, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
import { MAIN_CONTENT_ID, RouteAnnouncer } from "./navigation-a11y";

/** A lazy import whose resolution the test controls, mirroring a cold chunk. */
function gatedRoute(heading: string) {
  let release!: () => void;
  const module = new Promise<{ default: ComponentType }>((resolve) => {
    release = () => resolve({ default: () => <h1>{heading}</h1> });
  });
  return { Component: lazy(() => module), release };
}

function Shell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  return (
    <div>
      <Link to="/kanban">Go to Kanban</Link>
      <Link to="/dashboard">Go to Dashboard</Link>
      <main key={location.pathname} id={MAIN_CONTENT_ID} tabIndex={-1}>
        {/* A plain element, not role="status", so the only status node in the
            tree is the announcer itself. */}
        <Suspense fallback={<p>Loading page…</p>}>{children}</Suspense>
      </main>
      <RouteAnnouncer />
    </div>
  );
}

function renderShell(kanban: ComponentType) {
  return renderWithProviders(
    <Routes>
      <Route
        element={
          <Shell>
            <Outlet />
          </Shell>
        }
      >
        <Route path="/" element={<h1>Queue</h1>} />
        <Route path="/kanban" element={<KanbanSlot Component={kanban} />} />
        <Route path="/dashboard" element={<h1>Dashboard</h1>} />
      </Route>
    </Routes>,
    { route: "/" },
  );
}

function KanbanSlot({ Component }: { Component: ComponentType }) {
  return <Component />;
}

describe("route announcements", () => {
  it("stays silent on first render so it does not duplicate the document announcement", () => {
    const { Component } = gatedRoute("Kanban");
    renderShell(Component);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Queue");
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("announces a code-split route's own heading, not the Suspense fallback", async () => {
    const user = userEvent.setup();
    const { Component, release } = gatedRoute("Kanban");
    renderShell(Component);

    await user.click(screen.getByRole("link", { name: "Go to Kanban" }));

    // The chunk has not arrived: the fallback is showing and there is no
    // heading to read. Announcing here is what the earlier single-frame
    // implementation did, and it produced a generic string.
    expect(screen.getByText("Loading page…")).toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent("Page loaded.");

    release();

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Kanban. Page loaded.",
      );
    });
  });

  it("announces a route whose heading is available immediately", async () => {
    const user = userEvent.setup();
    const { Component } = gatedRoute("Kanban");
    renderShell(Component);

    await user.click(screen.getByRole("link", { name: "Go to Dashboard" }));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Dashboard. Page loaded.",
      );
    });
  });
});
