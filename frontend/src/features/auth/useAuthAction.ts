import { useCallback, useEffect, useRef, useState } from "react";

export function authActionError(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "The authentication request could not be completed.";
}

export function useAuthAction() {
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async (action: () => Promise<void>) => {
    if (inFlight.current) return;

    inFlight.current = true;
    if (mounted.current) {
      setPending(true);
      setError(null);
    }

    try {
      await action();
    } catch (actionError) {
      if (mounted.current) setError(authActionError(actionError));
    } finally {
      inFlight.current = false;
      if (mounted.current) setPending(false);
    }
  }, []);

  return { pending, error, run };
}
