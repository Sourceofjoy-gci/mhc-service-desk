import { useEffect, useState } from "react";
import { initKeycloak, type AuthState } from "./keycloak";

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

  if (auth.status === "loading" || auth.status === "idle") {
    return <p className="text-ink-500">Contacting Keycloak…</p>;
  }

  if (auth.status === "error") {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        Authentication error: {auth.error}
      </div>
    );
  }

  if (auth.status === "unauthenticated") {
    return (
      <div className="rounded-md border border-ink-100 bg-white p-6 text-sm text-ink-700">
        You are not signed in. The interactive login flow is wired in Milestone 2
        (Operational Vertical Slice). For now, this page verifies the Keycloak
        realm is reachable.
      </div>
    );
  }

  return (
    <div className="rounded-md border border-green-200 bg-green-50 p-6 text-sm text-green-800">
      Signed in as <strong>{auth.profile?.username}</strong> — token expires at{" "}
      {new Date((auth.expiresAt ?? 0) * 1000).toLocaleString()}.
    </div>
  );
}
