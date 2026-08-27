import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { execSync } from "node:child_process";

// A real build identifier. The footer previously printed the current year,
// which is not a build: it changes on 1 January with no rebuild behind it.
// CI can override via BUILD_ID; a plain checkout falls back to the short SHA.
function buildId(): string {
  if (process.env.BUILD_ID) return process.env.BUILD_ID;
  try {
    return execSync("git rev-parse --short HEAD", {
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
  } catch {
    return "dev";
  }
}

const apiProxyTarget =
  process.env.API_PROXY_TARGET ||
  process.env.VITE_API_BASE_URL ||
  "http://localhost:8000";
const keycloakProxyTarget =
  process.env.KEYCLOAK_PROXY_TARGET || "http://localhost:8080";

export default defineConfig({
  define: {
    __BUILD_ID__: JSON.stringify(buildId()),
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      "/realms": {
        target: keycloakProxyTarget,
        changeOrigin: false,
      },
      "/resources": {
        target: keycloakProxyTarget,
        changeOrigin: false,
      },
    },
  },
  build: {
    // Public source maps expose implementation details and are not required
    // by the production runtime. Upload private maps to an error tracker when
    // one is configured instead of serving them with the application.
    sourcemap: false,
    outDir: "dist",
    rollupOptions: {
      output: {
        // Dependencies that change on their own release cadence, not ours.
        // Splitting them keeps the year-long asset cache useful: a change to
        // application code no longer invalidates ~150 kB of vendor bundle.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query"],
          auth: ["keycloak-js"],
          dnd: ["@dnd-kit/core", "@dnd-kit/sortable", "@dnd-kit/utilities"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    clearMocks: true,
  },
});
