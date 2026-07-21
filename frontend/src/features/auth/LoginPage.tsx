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
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
            <div className="mx-auto mb-2 grid size-12 place-items-center rounded-full bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
              <KeyRound className="size-5" />
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
              <ErrorPanel error={auth.error} onRetry={() => setAuth({ status: "idle" })} />
            ) : auth.status === "unauthenticated" ? (
              <SignInPanel />
            ) : (
              <SignedInPanel
                username={auth.profile?.username ?? "—"}
                expiresAt={auth.expiresAt ?? 0}
              />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function BrandPanel() {
  return (
    <div className="relative hidden overflow-hidden rounded-2xl border border-border/60 bg-gradient-to-br from-primary to-primary/80 p-10 text-primary-foreground lg:flex lg:flex-col lg:justify-between">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-30"
        style={{
          backgroundImage:
            "radial-gradient(circle at 0% 100%, var(--gold), transparent 50%)",
        }}
      />
      <div className="relative flex flex-col gap-6">
        <BrandLockup size="lg" className="[&_span]:text-primary-foreground [&_span]:!text-primary-foreground" />
        <div className="flex flex-col gap-3">
          <Badge
            variant="secondary"
            className="w-fit bg-white/15 text-primary-foreground ring-1 ring-inset ring-white/20"
          >
            <Shield className="size-3" />
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

function ErrorPanel({
  error,
  onRetry,
}: {
  error: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-2.5 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
        <AlertCircle className="mt-0.5 size-4 shrink-0" />
        <div>
          <p className="font-medium">Couldn't reach Keycloak.</p>
          <p className="mt-0.5 text-xs text-destructive/80">{error}</p>
        </div>
      </div>
      <Button onClick={onRetry} variant="outline" data-icon>
        Try again
        <ArrowRight data-icon="inline-end" />
      </Button>
    </div>
  );
}

function SignInPanel() {
  return (
    <div className="flex flex-col gap-3">
      <Button
        onClick={() =>
          getKeycloak().login({
            redirectUri: window.location.origin + "/login",
          })
        }
        size="lg"
        data-icon
      >
        <KeyRound data-icon="inline-start" />
        Sign in with Keycloak
        <ArrowRight data-icon="inline-end" />
      </Button>
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
    <div className="flex flex-col gap-3">
      <div className="flex items-start gap-2.5 rounded-lg border border-success/30 bg-success/10 p-3 text-sm text-success-foreground">
        <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
        <div className="flex-1">
          <p className="font-medium">Signed in as {username}</p>
          <p className="mt-0.5 text-xs opacity-80">
            Token expires {new Date(expiresAt * 1000).toLocaleString()}
          </p>
        </div>
      </div>
      <Button
        variant="outline"
        onClick={() =>
          getKeycloak().logout({ redirectUri: window.location.origin + "/login" })
        }
        data-icon
      >
        <LogOut data-icon="inline-start" />
        Sign out
      </Button>
    </div>
  );
}
