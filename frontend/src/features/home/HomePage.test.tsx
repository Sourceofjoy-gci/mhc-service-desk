import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import HomePage from "./HomePage";

const harness = vi.hoisted(() => ({
  api: vi.fn(),
  groups: ["system-admins"] as string[],
}));

vi.mock("@/lib/api", () => ({
  api: harness.api,
}));

vi.mock("@/features/auth/AuthProvider", () => ({
  useAuth: () => ({
    user: {
      groups: harness.groups,
    },
  }),
}));

beforeEach(() => {
  harness.groups = ["system-admins"];
  harness.api.mockReset().mockResolvedValue({
    status: "ok",
    environment: "pilot",
    version: "0.1.0",
    checks: {
      database: { ok: true, latency_ms: 4.2 },
      redis: { ok: true, latency_ms: 1.4 },
      minio: { ok: true, latency_ms: 8.1 },
      keycloak: { ok: true, latency_ms: 12.7 },
    },
  });
});

describe("task-first home page", () => {
  it("puts the four staff workflows before secondary operational context", async () => {
    renderWithProviders(<HomePage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Staff workspace" }),
    ).toHaveClass("text-2xl", "font-semibold", "tracking-tight");

    const startWork = screen.getByRole("region", { name: "Start work" });
    expect(
      within(startWork).getByRole("link", { name: "Open queue" }),
    ).toHaveAttribute("href", "/tickets");
    expect(
      within(startWork).getByRole("link", { name: "View Kanban" }),
    ).toHaveAttribute("href", "/kanban");
    expect(
      within(startWork).getByRole("link", { name: "Capture a call" }),
    ).toHaveAttribute("href", "/intake/call");
    expect(
      within(startWork).getByRole("link", { name: "Capture a walk-in" }),
    ).toHaveAttribute("href", "/intake/walk-in");

    expect(
      await screen.findByRole("heading", { name: "Platform status" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Operational and IT work stay separate",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Capture every request." }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Multi-channel intake")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "View dashboard" }),
    ).toHaveAttribute("data-slot", "button");
    expect(
      screen.getByRole("button", { name: "View dashboard" }),
    ).toHaveAttribute("href", "/dashboard");
    expect(
      screen.getByRole("button", { name: "Service health" }),
    ).toHaveAttribute("data-slot", "button");
    expect(
      screen.getByRole("button", { name: "Service health" }),
    ).toHaveAttribute("href", "/health");
  });

  it("does not expose or request platform status for other end users", () => {
    harness.groups = ["ops-agents"];

    renderWithProviders(<HomePage />);

    expect(
      screen.queryByRole("heading", { name: "Platform status" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Service health" }),
    ).not.toBeInTheDocument();
    expect(harness.api).not.toHaveBeenCalled();
  });

  it("recognizes the System Administrator realm-role alias", async () => {
    harness.groups = ["admin"];

    renderWithProviders(<HomePage />);

    expect(
      await screen.findByRole("heading", { name: "Platform status" }),
    ).toBeInTheDocument();
    expect(harness.api).toHaveBeenCalledWith("/health");
  });

  it("uses settled error copy when the platform status request fails", async () => {
    harness.api.mockRejectedValue(new Error("Offline"));
    renderWithProviders(<HomePage />);

    expect(await screen.findByText("Unreachable")).toBeVisible();
    expect(screen.getByText("Platform status unavailable")).toBeVisible();
    expect(screen.queryByText("Checking API…")).not.toBeInTheDocument();
  });

  it("shows a text status for every platform dependency", async () => {
    harness.api.mockResolvedValue({
      status: "degraded",
      environment: "pilot",
      version: "0.1.0",
      checks: {
        database: { ok: true, latency_ms: 4.2 },
        redis: { ok: false, latency_ms: 1.4 },
      },
    });

    renderWithProviders(<HomePage />);

    expect(await screen.findByText("Healthy")).toBeVisible();
    expect(screen.getByText("Failed")).toBeVisible();
    expect(screen.getAllByText("Unknown")).toHaveLength(2);
  });
});
