import Keycloak, { type KeycloakProfile } from "keycloak-js";

export type AuthState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "unauthenticated" }
  | { status: "authenticated"; token: string; profile?: KeycloakProfile; expiresAt?: number }
  | { status: "error"; error: string };

let keycloak: Keycloak | null = null;

export function isDevAuthEnabled(): boolean {
  return (
    import.meta.env.VITE_DEV_AUTH === "1" &&
    import.meta.env.MODE === "development"
  );
}

export function getKeycloak(): Keycloak {
  if (!keycloak) {
    keycloak = new Keycloak({
      url: import.meta.env.VITE_KEYCLOAK_URL,
      realm: import.meta.env.VITE_KEYCLOAK_REALM,
      clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID,
    });
  }
  return keycloak;
}

export async function initKeycloak(): Promise<AuthState> {
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
    return { status: "error", error: err instanceof Error ? err.message : String(err) };
  }
}
