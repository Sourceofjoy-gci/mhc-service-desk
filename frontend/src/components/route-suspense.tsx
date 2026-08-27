/**
 * Boundary for lazily-loaded routes.
 *
 * It sits inside each shell rather than around `<Routes>` so the header, nav
 * and footer stay mounted while a route chunk is fetched — the chrome does not
 * blink, and a keyboard user does not lose their place.
 */

import { Suspense, type ReactNode } from "react";
import { Spinner } from "./ui/spinner";

export function RouteSuspense({ children }: { children: ReactNode }) {
  return <Suspense fallback={<RouteFallback />}>{children}</Suspense>;
}

function RouteFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-64 items-center justify-center gap-2 text-sm text-muted-foreground"
    >
      <Spinner aria-hidden />
      Loading page…
    </div>
  );
}
