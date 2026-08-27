import {
  Shield,
  KeyRound,
  LogOut,
  CheckCircle2,
  AlertCircle,
  ArrowRight,
} from "lucide-react";
import { useAuth, type AuthContextValue } from "./AuthProvider";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { BrandLockup } from "@/components/brand";
import { useAuthAction } from "./useAuthAction";

export default function LoginPage() {
  const auth = useAuth();
  const authAction = useAuthAction();
  const isDevelopmentSession = auth.state === "authenticated" && auth.isDevAuth;

  return (
    <div className="grid min-h-[calc(100dvh-12rem)] items-center gap-8 lg:grid-cols-2">
      <BrandPanel />
      <div className="mx-auto w-full max-w-md">
        <Card aria-busy={authAction.pending || auth.state === "loading"}>
          <CardHeader className="text-center">
            <div className="mx-auto grid size-12 place-items-center rounded-lg bg-muted text-primary">
              <KeyRound />
            </div>
            <CardTitle>
              <h1 className="text-xl">Agent sign-in</h1>
            </CardTitle>
            <CardDescription>
              Sign in with your MHC Keycloak realm account to access the agent
              console.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {auth.state === "loading" ? (
              <SignInSkeleton />
            ) : auth.state === "error" ? (
              <ErrorPanel
                error={auth.error ?? "The identity service is unavailable."}
              />
            ) : auth.state === "unauthenticated" ? (
              <SignInPanel />
            ) : isDevelopmentSession ? (
              <DevelopmentAuthPanel
                username={
                  auth.user?.displayName?.trim() ||
                  auth.user?.username?.trim() ||
                  "Signed-in user"
                }
              />
            ) : (
              <SignedInPanel
                username={
                  auth.user?.displayName?.trim() ||
                  auth.user?.username?.trim() ||
                  "Signed-in user"
                }
                expiresAt={auth.expiresAt}
                isDevAuth={auth.isDevAuth}
              />
            )}
          </CardContent>
          <CardFooter className="flex-col gap-3">
            {authAction.error ? (
              <Alert variant="destructive" className="w-full">
                <AlertCircle aria-hidden />
                <AlertTitle>
                  {auth.state === "authenticated"
                    ? "Could not sign out"
                    : "Could not sign in"}
                </AlertTitle>
                <AlertDescription>{authAction.error}</AlertDescription>
              </Alert>
            ) : null}
            {isDevelopmentSession ? null : (
              <AuthAction
                auth={auth}
                pending={authAction.pending}
                run={authAction.run}
              />
            )}
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}

function BrandPanel() {
  return (
    <div className="relative hidden overflow-hidden rounded-lg border border-border/60 bg-gradient-to-br from-primary to-primary/80 p-10 text-primary-foreground lg:flex lg:flex-col lg:justify-between">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-30"
        style={{
          backgroundImage:
            "radial-gradient(circle at 0% 100%, var(--gold), transparent 50%)",
        }}
      />
      <div className="relative flex flex-col gap-6">
        <BrandLockup
          size="lg"
          className="[&_span]:text-primary-foreground [&_span]:!text-primary-foreground"
        />
        <div className="flex flex-col gap-3">
          <Badge variant="secondary">
            <Shield />
            OIDC + MFA enforced
          </Badge>
          <h2 className="text-balance text-3xl font-semibold leading-tight tracking-tight">
            Service desk, signed and sealed.
          </h2>
          <p className="max-w-md text-pretty text-sm text-primary-foreground/80">
            Every action is bound to your Keycloak subject. Tokens are short-
            lived and refreshed silently. Audit logging captures every state
            transition and permission decision.
          </p>
        </div>
      </div>
      <ul className="relative mt-10 grid gap-3 text-sm text-primary-foreground/90">
        <li className="flex items-center gap-2">
          <CheckCircle2 className="size-4 text-gold" />
          Strict OP/IT domain separation
        </li>
        <li className="flex items-center gap-2">
          <CheckCircle2 className="size-4 text-gold" />
          Sanitised IT-child handoff
        </li>
        <li className="flex items-center gap-2">
          <CheckCircle2 className="size-4 text-gold" />
          Append-only audit trail
        </li>
        <li className="flex items-center gap-2">
          <CheckCircle2 className="size-4 text-gold" />
          SLA-aware queue and Kanban
        </li>
      </ul>
    </div>
  );
}

function SignInSkeleton() {
  return (
    <div
      role="status"
      aria-label="Checking authentication status"
      aria-live="polite"
      aria-busy="true"
      className="flex flex-col gap-3"
    >
      <span className="text-center text-sm text-muted-foreground">
        Checking authentication status…
      </span>
      <div aria-hidden className="flex flex-col gap-3">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-4 w-2/3" />
        <Separator />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
    </div>
  );
}

function ErrorPanel({ error }: { error: string }) {
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>Couldn&apos;t reach Keycloak.</AlertTitle>
      <AlertDescription>{error}</AlertDescription>
    </Alert>
  );
}

function SignInPanel() {
  return (
    <div>
      <p className="text-center text-xs text-muted-foreground">
        You will be redirected to the Keycloak realm to authenticate.
      </p>
    </div>
  );
}

function DevelopmentAuthPanel({ username }: { username: string }) {
  return (
    <Alert>
      <CheckCircle2 className="text-success-foreground" />
      <AlertTitle>Development access for {username}</AlertTitle>
      <AlertDescription>
        Local development access is active. Sign-out is unavailable in this
        mode.
      </AlertDescription>
    </Alert>
  );
}

function SignedInPanel({
  username,
  expiresAt,
  isDevAuth,
}: {
  username: string;
  expiresAt: number | null;
  isDevAuth: boolean;
}) {
  return (
    <Alert>
      <CheckCircle2 className="text-success-foreground" />
      <AlertTitle>Signed in as {username}</AlertTitle>
      <AlertDescription>
        {isDevAuth
          ? "Local development authentication is active."
          : expiresAt
            ? `Token expires ${new Date(expiresAt * 1000).toLocaleString()}`
            : "Session expiry is managed by the identity provider."}
      </AlertDescription>
    </Alert>
  );
}

function AuthAction({
  auth,
  pending,
  run,
}: {
  auth: AuthContextValue;
  pending: boolean;
  run: (action: () => Promise<void>) => Promise<void>;
}) {
  if (auth.isDevAuth) {
    return <Badge variant="secondary">Development access active</Badge>;
  }

  if (auth.state === "loading") {
    return <Skeleton className="h-10 w-full" />;
  }

  if (auth.state === "error") {
    return null;
  }

  if (auth.state === "unauthenticated") {
    return (
      <Button
        className="w-full"
        disabled={pending}
        onClick={() => void run(() => auth.login("/"))}
        size="lg"
      >
        {pending ? (
          <Spinner aria-hidden data-icon="inline-start" />
        ) : (
          <KeyRound data-icon="inline-start" />
        )}
        {pending ? "Signing in…" : "Sign in with Keycloak"}
        <ArrowRight data-icon="inline-end" />
      </Button>
    );
  }

  return (
    <Button
      className="w-full"
      disabled={pending}
      variant="outline"
      onClick={() => void run(auth.logout)}
    >
      {pending ? (
        <Spinner aria-hidden data-icon="inline-start" />
      ) : (
        <LogOut data-icon="inline-start" />
      )}
      {pending ? "Signing out…" : "Sign out"}
    </Button>
  );
}
