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

export function isDevAuthEnabled(): boolean {
  return (
    import.meta.env.VITE_DEV_AUTH === "1" &&
    import.meta.env.MODE === "development"
  );
}

export function getKeycloak(): Keycloak {
  if (!lifecycle.keycloak) {
    lifecycle.keycloak = new Keycloak({
      url: import.meta.env.VITE_KEYCLOAK_URL,
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
  const kc = getKeycloak();
  try {
    const authenticated = await kc.init({
      onLoad: "check-sso",
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
    return { status: "error", error: err instanceof Error ? err.message : String(err) };
  }
}
