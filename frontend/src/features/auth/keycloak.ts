import Keycloak, { type KeycloakProfile } from "keycloak-js";

export type AuthState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "unauthenticated" }
  | { status: "authenticated"; token: string; profile?: KeycloakProfile; expiresAt?: number }
  | { status: "error"; error: string };

interface KeycloakLifecycle {
  keycloak: Keycloak | null;
  initialization: Promise<AuthState> | null;
}

const LIFECYCLE_KEY = Symbol.for("mhc-ticketing.keycloak-lifecycle");
const globalLifecycle = globalThis as typeof globalThis & {
  [key: symbol]: KeycloakLifecycle | undefined;
};
const lifecycle =
  globalLifecycle[LIFECYCLE_KEY] ??
  (globalLifecycle[LIFECYCLE_KEY] = {
    keycloak: null,
    initialization: null,
  });

export const DEV_AUTH_ENABLED =
  import.meta.env.VITE_DEV_AUTH === "1" && import.meta.env.MODE === "development";

export function isDevAuthEnabled(): boolean {
  return (
    import.meta.env.VITE_DEV_AUTH === "1" &&
    import.meta.env.MODE === "development"
  );
}

export function getKeycloak(): Keycloak {
  if (!lifecycle.keycloak) {
    const configuredUrl = import.meta.env.VITE_KEYCLOAK_URL?.trim();
    const keycloakUrl =
      !configuredUrl || configuredUrl === "same-origin"
        ? window.location.origin
        : configuredUrl;
    lifecycle.keycloak = new Keycloak({
      url: keycloakUrl,
      realm: import.meta.env.VITE_KEYCLOAK_REALM,
      clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID,
    });
  }
  return lifecycle.keycloak;
}

export function initKeycloak(): Promise<AuthState> {
  if (!lifecycle.initialization) {
    lifecycle.initialization = initializeKeycloak().then(
      (state) => {
        if (state.status === "error") lifecycle.initialization = null;
        return state;
      },
      (error: unknown) => {
        lifecycle.initialization = null;
        throw error;
      },
    );
  }
  return lifecycle.initialization;
}

async function initializeKeycloak(): Promise<AuthState> {
  if (DEV_AUTH_ENABLED) {
    return {
      status: "authenticated",
      token: "dev",
      profile: { username: "demo" },
    };
  }

  const kc = getKeycloak();
  try {
    const authenticated = await kc.init({
      onLoad: "check-sso",
      // Resolve an existing realm session inside a hidden iframe. Without a
      // silent redirect URI keycloak-js answers `check-sso` by navigating the
      // whole document to the realm and back, so every cold load — including
      // one that only wants the sign-in page — flashes through Keycloak.
      // `silentCheckSsoRedirectUri` must stay inside the client's registered
      // redirect URIs; `public/silent-check-sso.html` is served from the app
      // origin for exactly that reason.
      silentCheckSsoRedirectUri: `${window.location.origin}/silent-check-sso.html`,
      // A browser that cannot run the probe reports "no session" rather than
      // falling back to the full-page redirect this option exists to avoid.
      silentCheckSsoFallback: false,
      checkLoginIframe: false,
    });
    if (!authenticated) {
      return { status: "unauthenticated" };
    }
    return {
      status: "authenticated",
      token: kc.token ?? "",
      profile: kc.profile,
      expiresAt: kc.tokenParsed?.exp,
    };
  } catch (err) {
    lifecycle.keycloak = null;
    return { status: "error", error: authErrorMessage(err) };
  }
}

function authErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  if (typeof error === "string" && error.trim()) return error;
  return "Keycloak authentication failed. Please try again.";
}
