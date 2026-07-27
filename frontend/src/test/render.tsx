import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement, ReactNode } from "react";

interface RenderWithProvidersOptions extends Omit<RenderOptions, "wrapper"> {
  route?: string;
}

export function renderWithProviders(
  ui: ReactElement,
  { route = "/", ...options }: RenderWithProvidersOptions = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  window.history.pushState({}, "", route);

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[route]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          {children}
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  return { ...render(ui, { wrapper: Wrapper, ...options }), queryClient };
}
