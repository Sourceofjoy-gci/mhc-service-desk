import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./app/App";
import { ThemeProvider } from "./components/theme-provider";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("Root element missing");

// Avoid theme flash on first paint
const saved = (() => {
  try {
    return localStorage.getItem("mhc.theme");
  } catch {
    return null;
  }
})();
const initial: "light" | "dark" =
  saved === "dark" ||
  (saved === "system" &&
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches) ||
  (saved === null &&
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches)
    ? "dark"
    : "light";
if (initial === "dark") document.documentElement.classList.add("dark");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </React.StrictMode>,
);
