import { screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/render";
import HealthPage from "./HealthPage";

const harness = vi.hoisted(() => ({
  api: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, api: harness.api };
});

beforeEach(() => {
  harness.api.mockReset().mockResolvedValue({
    status: "ok",
    environment: "test",
    version: "test",
    checks: {},
    total_ms: 1,
  });
});

it("loads the public health endpoint without requiring an access token", async () => {
  renderWithProviders(<HealthPage />, { route: "/health" });

  expect(await screen.findByText("Operational")).toBeInTheDocument();
  expect(harness.api).toHaveBeenCalledWith("/health", { auth: false });
});
