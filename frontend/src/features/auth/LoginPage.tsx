import { useEffect, useState } from "react";
import {
  Shield,
  KeyRound,
  LogOut,
  CheckCircle2,
  AlertCircle,
  ArrowRight,
} from "lucide-react";
import { getKeycloak, initKeycloak, type AuthState } from "./keycloak";
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
import { BrandLockup } from "@/components/brand";

export default function LoginPage() {
  const [auth, setAuth] = useState<AuthState>({ status: "idle" });

  useEffect(() => {
    if (auth.status === "idle") {
      setAuth({ status: "loading" });
      initKeycloak()
        .then((state) => setAuth(state))
        .catch((e) => setAuth({ status: "error", error: String(e) }));
    }
  }, [auth.status]);

  return (
    <div className="grid min-h-[calc(100vh-12rem)] items-center gap-8 lg:grid-cols-2">
      <BrandPanel />
      <div className="mx-auto w-full max-w-md">
        <Card>
          <CardHeader className="text-center">
            <div className="mx-auto grid size-12 place-items-center rounded-lg bg-muted text-primary">
              <KeyRound />
            </div>
            <CardTitle className="text-xl">Agent sign-in</CardTitle>
            <CardDescription>
              Sign in with your MHC Keycloak realm account to access the agent
              console.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {auth.status === "loading" || auth.status === "idle" ? (
              <SignInSkeleton />
            ) : auth.status === "error" ? (
              <ErrorPanel error={auth.error} />
            ) : auth.status === "unauthenticated" ? (
              <SignInPanel />
            ) : (
              <SignedInPanel
                username={auth.profile?.username ?? "—"}
                expiresAt={auth.expiresAt ?? 0}
              />
            )}
          </CardContent>
          <CardFooter className="flex-col">
            <AuthAction
              auth={auth}
              onRetry={() => setAuth({ status: "idle" })}
            />
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
    <div className="flex flex-col gap-3">
      <Skeleton className="h-9 w-full" />
      <Skeleton className="h-4 w-2/3" />
      <Separator />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
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

function SignedInPanel({
  username,
  expiresAt,
}: {
  username: string;
  expiresAt: number;
}) {
  return (
    <Alert>
      <CheckCircle2 className="text-success-foreground" />
      <AlertTitle>Signed in as {username}</AlertTitle>
      <AlertDescription>
        Token expires {new Date(expiresAt * 1000).toLocaleString()}
      </AlertDescription>
    </Alert>
  );
}

function AuthAction({
  auth,
  onRetry,
}: {
  auth: AuthState;
  onRetry: () => void;
}) {
  if (auth.status === "loading" || auth.status === "idle") {
    return <Skeleton className="h-10 w-full" />;
  }

  if (auth.status === "error") {
    return (
      <Button className="w-full" onClick={onRetry} variant="outline">
        Try again
        <ArrowRight data-icon="inline-end" />
      </Button>
    );
  }

  if (auth.status === "unauthenticated") {
    return (
      <Button
        className="w-full"
        onClick={() =>
          getKeycloak().login({
            redirectUri: window.location.origin + "/login",
          })
        }
        size="lg"
      >
        <KeyRound data-icon="inline-start" />
        Sign in with Keycloak
        <ArrowRight data-icon="inline-end" />
      </Button>
    );
  }

  return (
    <Button
      className="w-full"
      variant="outline"
      onClick={() =>
        getKeycloak().logout({ redirectUri: window.location.origin + "/login" })
      }
    >
      <LogOut data-icon="inline-start" />
      Sign out
    </Button>
  );
}
