import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import type { KeycloakProfile } from "keycloak-js";
import { configureApiAuth } from "@/lib/api";
import { getKeycloak, initKeycloak, isDevAuthEnabled } from "./keycloak";

const RETURN_TO_KEY = "mhc.auth.returnTo";
const DEV_TOKEN = "dev:demo:ops-agents";

export const KEYCLOAK_REALM_ROLES: ReadonlySet<string> = new Set([
  "staff",
  "agent-operational",
  "supervisor-operational",
  "agent-it",
  "lead-it",
  "admin",
  "auditor",
  "master",
  "deputy-master",
  "assistant-master",
  "assistant-accountant",
  "accountant",
  "senior-accountant",
  "principal-accountant",
  "financial-controller",
  "estate-examiner",
  "records-clerk",
  "data-clerk",
]);

const DEV_USER: AuthUser = {
  subject: "dev:demo",
  username: "demo",
  displayName: "Demo Agent",
  groups: ["ops-agents"],
};

export interface AuthUser {
  subject: string;
  username: string;
  displayName: string;
  groups: string[];
}

export interface AuthContextValue {
  state: "loading" | "authenticated" | "unauthenticated" | "error";
  user: AuthUser | null;
  error: string | null;
  expiresAt: number | null;
  isDevAuth: boolean;
  getAccessToken(forceRefresh?: boolean): Promise<string | null>;
  login(returnTo?: string): Promise<void>;
  logout(): Promise<void>;
}

interface AuthSnapshot {
  state: AuthContextValue["state"];
  user: AuthUser | null;
  error: string | null;
  expiresAt: number | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const isDevAuth = isDevAuthEnabled();
  const initializationRef = useRef<Promise<AuthSnapshot> | null>(null);
  const refreshRef = useRef<Promise<string | null> | null>(null);
  const [snapshot, setSnapshot] = useState<AuthSnapshot>({
    state: "loading",
    user: null,
    error: null,
    expiresAt: null,
  });

  const getInitialization = useCallback((): Promise<AuthSnapshot> => {
    if (!initializationRef.current) {
      initializationRef.current = initializeSession(isDevAuth);
    }
    return initializationRef.current;
  }, [isDevAuth]);

  const getAccessToken = useCallback(
    async (forceRefresh = false): Promise<string | null> => {
      if (isDevAuth) return DEV_TOKEN;
      const initialized = await getInitialization();
      if (initialized.state !== "authenticated") return null;
      const keycloak = getKeycloak();
      if (forceRefresh) {
        if (!refreshRef.current) {
          refreshRef.current = keycloak
            .updateToken(30)
            .then(() => keycloak.token ?? null)
            .finally(() => {
              refreshRef.current = null;
            });
        }
        return refreshRef.current;
      }
      return keycloak.token ?? null;
    },
    [getInitialization, isDevAuth],
  );

  const login = useCallback(
    async (returnTo?: string): Promise<void> => {
      if (returnTo !== undefined) {
        const normalized = normalizeReturnPath(returnTo);
        if (normalized) sessionStorage.setItem(RETURN_TO_KEY, normalized);
        else sessionStorage.removeItem(RETURN_TO_KEY);
      }
      if (isDevAuth) return;
      await getKeycloak().login({
        redirectUri: `${window.location.origin}/login`,
      });
    },
    [isDevAuth],
  );

  const logout = useCallback(async (): Promise<void> => {
    sessionStorage.removeItem(RETURN_TO_KEY);
    if (isDevAuth) return;
    await getKeycloak().logout({
      redirectUri: `${window.location.origin}/login`,
    });
  }, [isDevAuth]);

  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      return (await getAccessToken(true)) !== null;
    } catch {
      return false;
    }
  }, [getAccessToken]);

  useLayoutEffect(() => {
    return configureApiAuth({ getAccessToken, refresh, login });
  }, [getAccessToken, login, refresh]);

  useEffect(() => {
    let active = true;
    void getInitialization().then((nextSnapshot) => {
      if (!active) return;
      setSnapshot(nextSnapshot);
      if (nextSnapshot.state === "authenticated") {
        const returnTo = consumeReturnPath();
        if (returnTo) navigate(returnTo, { replace: true });
      }
    });

    return () => {
      active = false;
    };
  }, [getInitialization, navigate]);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...snapshot,
      isDevAuth,
      getAccessToken,
      login,
      logout,
    }),
    [getAccessToken, isDevAuth, login, logout, snapshot],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}

async function initializeSession(isDevAuth: boolean): Promise<AuthSnapshot> {
  try {
    if (isDevAuth) {
      return {
        state: "authenticated",
        user: DEV_USER,
        error: null,
        expiresAt: null,
      };
    }

    const initialized = await initKeycloak();
    if (initialized.status === "error") {
      return {
        state: "error",
        user: null,
        error: initialized.error,
        expiresAt: null,
      };
    }
    if (initialized.status !== "authenticated") {
      return {
        state: "unauthenticated",
        user: null,
        error: null,
        expiresAt: null,
      };
    }
    const keycloak = getKeycloak();
    const profile = await keycloak.loadUserProfile();
    const claims = keycloak.tokenParsed;
    const username =
      profile.username ?? stringClaim(claims?.preferred_username) ?? "";
    const displayName = profileDisplayName(profile) || username;

    return {
      state: "authenticated",
      user: {
        subject: stringClaim(claims?.sub) ?? profile.id ?? "",
        username,
        displayName,
        groups: authorizationGroups(claims),
      },
      error: null,
      expiresAt: typeof claims?.exp === "number" ? claims.exp : null,
    };
  } catch (error) {
    return {
      state: "error",
      user: null,
      error: error instanceof Error ? error.message : String(error),
      expiresAt: null,
    };
  }
}

function profileDisplayName(profile: KeycloakProfile): string {
  return [profile.firstName, profile.lastName].filter(Boolean).join(" ").trim();
}

function stringClaim(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function stringArrayClaim(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((group): group is string => typeof group === "string")
    : [];
}

function authorizationGroups(
  claims: ReturnType<typeof getKeycloak>["tokenParsed"],
): string[] {
  const groups = stringArrayClaim(claims?.groups);
  const realmRoles = stringArrayClaim(claims?.realm_access?.roles).filter(
    (role) => KEYCLOAK_REALM_ROLES.has(role),
  );
  return [...new Set([...groups, ...realmRoles])];
}

function normalizeReturnPath(path: string): string | null {
  if (!path.startsWith("/")) return null;
  try {
    const url = new URL(path, window.location.origin);
    if (url.origin !== window.location.origin || !url.pathname.startsWith("/")) {
      return null;
    }
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

function consumeReturnPath(): string | null {
  const path = sessionStorage.getItem(RETURN_TO_KEY);
  sessionStorage.removeItem(RETURN_TO_KEY);
  return path ? normalizeReturnPath(path) : null;
}
