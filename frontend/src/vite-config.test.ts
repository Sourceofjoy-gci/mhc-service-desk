// @vitest-environment node

import { afterEach, describe, expect, it, vi } from "vitest";

describe("development reverse proxies", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.resetModules();
  });

  it("keeps API and Keycloak requests on the active frontend origin", async () => {
    vi.stubEnv("API_PROXY_TARGET", "http://backend:8000");
    vi.stubEnv("KEYCLOAK_PROXY_TARGET", "http://keycloak:8080");
    const { default: config } = await import("../vite.config");

    expect(config.server?.proxy).toMatchObject({
      "/api": { target: "http://backend:8000" },
      "/realms": { target: "http://keycloak:8080" },
      "/resources": { target: "http://keycloak:8080" },
    });
  });
});
