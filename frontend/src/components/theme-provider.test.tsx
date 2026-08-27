/**
 * The theme is decided in two places: `main.tsx` paints one before React
 * mounts (to avoid a flash), and `ThemeProvider` applies one on mount. If the
 * two disagree about what "no stored preference" means, the second overrides
 * the first and the page visibly flips — which is exactly the dark-to-light
 * flash seen on every full page load.
 *
 * These tests pin the agreement rather than either value on its own.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider, useTheme } from "./theme-provider";

function setSystemPrefersDark(dark: boolean) {
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({
        matches: dark,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn().mockReturnValue(false),
      }) as MediaQueryList,
  );
}

function Probe() {
  const { resolvedTheme } = useTheme();
  return <span data-testid="resolved">{resolvedTheme}</span>;
}

describe("ThemeProvider with no stored preference", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "";
  });

  it("follows a dark system preference, keeping the class main.tsx pre-painted", () => {
    setSystemPrefersDark(true);
    // What main.tsx does at load time when nothing is stored and the OS is dark.
    document.documentElement.classList.add("dark");

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("resolved")).toHaveTextContent("dark");
    // Stripping this class is the flash. It must survive the mount.
    expect(document.documentElement).toHaveClass("dark");
  });

  it("resolves light when the system preference is light", () => {
    setSystemPrefersDark(false);

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("resolved")).toHaveTextContent("light");
    expect(document.documentElement).not.toHaveClass("dark");
  });
});

describe("ThemeProvider with a stored preference", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  it("honours an explicit light choice over a dark system preference", () => {
    setSystemPrefersDark(true);
    localStorage.setItem("mhc.theme", "light");

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("resolved")).toHaveTextContent("light");
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("honours an explicit dark choice over a light system preference", () => {
    setSystemPrefersDark(false);
    localStorage.setItem("mhc.theme", "dark");

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("resolved")).toHaveTextContent("dark");
    expect(document.documentElement).toHaveClass("dark");
  });
});
