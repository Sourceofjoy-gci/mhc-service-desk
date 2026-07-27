import { useEffect, useRef } from "react";
import { AlertCircle } from "lucide-react";
import { Outlet, useLocation } from "react-router-dom";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "./AuthProvider";

export function ProtectedRoute() {
  const { state, error, login } = useAuth();
  const location = useLocation();

  if (state === "loading") return <AuthLoadingState />;
  if (state === "error") return <AuthErrorState error={error} />;
  if (state === "unauthenticated") {
    return (
      <LoginRedirect
        login={login}
        returnTo={`${location.pathname}${location.search}`}
      />
    );
  }

  return <Outlet />;
}

function AuthLoadingState() {
  return (
    <main className="grid min-h-svh place-items-center px-6 py-12">
      <div
        role="status"
        aria-label="Checking your session"
        className="flex items-center gap-3 text-sm text-muted-foreground"
      >
        <Spinner aria-hidden />
        <span>Checking your session…</span>
      </div>
    </main>
  );
}

function AuthErrorState({ error }: { error: string | null }) {
  return (
    <main className="grid min-h-svh place-items-center px-6 py-12">
      <Alert variant="destructive" className="max-w-lg">
        <AlertCircle aria-hidden />
        <AlertTitle>Authentication is unavailable</AlertTitle>
        <AlertDescription>
          {error ?? "The identity service could not verify your session."}
        </AlertDescription>
      </Alert>
    </main>
  );
}

function LoginRedirect({
  login,
  returnTo,
}: {
  login: (returnTo?: string) => Promise<void>;
  returnTo: string;
}) {
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void login(returnTo);
  }, [login, returnTo]);

  return (
    <main className="grid min-h-svh place-items-center px-6 py-12">
      <div
        role="status"
        aria-label="Redirecting to sign in"
        className="flex items-center gap-3 text-sm text-muted-foreground"
      >
        <Spinner aria-hidden />
        <span>Redirecting to sign in…</span>
      </div>
    </main>
  );
}
