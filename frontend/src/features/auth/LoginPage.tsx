import { useEffect, useState } from "react";
import { getKeycloak, initKeycloak, type AuthState } from "./keycloak";

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
        <p className="mb-3">
          You are not signed in. Sign in with your MHC realm account to access
          the agent console.
        </p>
        <button
          type="button"
          onClick={() =>
            getKeycloak().login({ redirectUri: window.location.origin + "/login" })
          }
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          Sign in with Keycloak
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-green-200 bg-green-50 p-6 text-sm text-green-800">
      <p className="mb-3">
        Signed in as <strong>{auth.profile?.username}</strong> — token expires at{" "}
        {new Date((auth.expiresAt ?? 0) * 1000).toLocaleString()}.
      </p>
      <button
        type="button"
        onClick={() =>
          getKeycloak().logout({ redirectUri: window.location.origin + "/login" })
        }
        className="rounded-md border border-green-300 bg-white px-3 py-1.5 text-sm text-green-800 hover:bg-green-50"
      >
        Sign out
      </button>
    </div>
  );
}
