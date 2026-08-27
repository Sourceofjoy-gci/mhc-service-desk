import { HeartPulse, LogIn } from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { BrandLockup } from "./brand";
import {
  MAIN_CONTENT_ID,
  RouteAnnouncer,
  SkipLink,
} from "./navigation-a11y";
import { RouteSuspense } from "./route-suspense";
import { ThemeToggle } from "./theme-toggle";
import { cn } from "@/lib/utils";

const PUBLIC_LINKS = [
  { to: "/health", label: "Service health", icon: HeartPulse },
  { to: "/login", label: "Staff sign-in", icon: LogIn },
];

export function PublicShell() {
  const location = useLocation();

  return (
    <div className="flex min-h-full flex-col bg-background">
      <SkipLink />
      <header className="border-b border-border/60">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-4 px-4 py-3 sm:px-6">
          <Link
            to="/login"
            className="text-foreground no-underline focus-visible:rounded-lg focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <BrandLockup size="sm" />
          </Link>
          <nav
            aria-label="Public services"
            className="ml-auto flex items-center gap-1"
          >
            {PUBLIC_LINKS.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  cn(
                    "inline-flex min-h-9 items-center gap-2 rounded-lg px-3 text-sm transition-colors",
                    "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    isActive
                      ? "bg-accent font-medium text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/70 hover:text-foreground",
                  )
                }
              >
                {Icon ? (
                  <Icon className="hidden size-4 sm:block" aria-hidden />
                ) : null}
                <span>{label}</span>
              </NavLink>
            ))}
            <ThemeToggle />
          </nav>
        </div>
      </header>

      <main
        key={location.pathname}
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        className="mx-auto w-full max-w-7xl flex-1 animate-fade-in px-4 py-6 outline-none sm:px-6"
      >
        <RouteSuspense>
          <Outlet />
        </RouteSuspense>
      </main>
      <RouteAnnouncer />

      <footer className="border-t border-border/60 py-4 text-center text-xs text-muted-foreground">
        Master of the High Court · Staff access
      </footer>
    </div>
  );
}
