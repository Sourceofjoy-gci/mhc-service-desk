import { NavLink, Link, Outlet, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  ListChecks,
  KanbanSquare,
  Phone,
  User,
  HeartPulse,
  LogOut,
  Scale,
  AlertCircle,
  SearchCheck,
} from "lucide-react";
import { useAuth, type AuthUser } from "@/features/auth/AuthProvider";
import { useAuthAction } from "@/features/auth/useAuthAction";
import { cn } from "@/lib/utils";
import { BrandLockup, BrandMark } from "./brand";
import {
  MAIN_CONTENT_ID,
  RouteAnnouncer,
  SkipLink,
} from "./navigation-a11y";
import { RouteSuspense } from "./route-suspense";
import { ThemeToggle } from "./theme-toggle";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Avatar, AvatarFallback } from "./ui/avatar";
import { Badge } from "./ui/badge";
import { Separator } from "./ui/separator";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";
import { Spinner } from "./ui/spinner";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
}

const PRIMARY_NAV: NavItem[] = [
  { to: "/tickets", end: true, label: "Queue", icon: ListChecks },
  { to: "/ticket-tracking", label: "Track ticket", icon: SearchCheck },
  { to: "/kanban", label: "Kanban", icon: KanbanSquare },
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
];

const INTAKE_NAV: NavItem[] = [
  { to: "/intake/call", label: "Call", icon: Phone },
  { to: "/intake/walk-in", label: "Walk-in", icon: User },
];

const UTILITY_NAV: NavItem[] = [
  { to: "/health", label: "Health", icon: HeartPulse },
];

function navLinkClass(active: boolean, touchSafe = false) {
  return cn(
    "inline-flex min-h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-sm transition-colors",
    "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
    touchSafe && "min-h-11 w-full justify-center px-2",
    active
      ? "bg-accent font-medium text-accent-foreground"
      : "text-muted-foreground hover:bg-accent/70 hover:text-foreground",
  );
}

function NavGroup({ label, items }: { label: string; items: NavItem[] }) {
  return (
    <nav aria-label={label} className="flex flex-wrap items-center gap-1">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) => navLinkClass(isActive)}
        >
          <item.icon className="size-4" />
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  const location = useLocation();
  const { user, isDevAuth, logout } = useAuth();
  const identity = normalizeIdentity(user);
  const logoutAction = useAuthAction();

  return (
    <div className="flex min-h-full flex-col bg-background">
      <SkipLink />
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex w-full max-w-7xl items-center gap-2 px-4 py-2 sm:gap-4 sm:px-6">
          <Link
            to="/"
            aria-label="MHC Service Desk home"
            className="flex shrink-0 items-center gap-2 text-foreground no-underline"
          >
            <BrandMark className="sm:hidden" size={24} />
            <BrandLockup className="hidden sm:flex" size="sm" />
          </Link>

          <Separator
            orientation="vertical"
            className="mx-1 hidden h-6 md:block"
          />

          <div className="hidden flex-1 items-center gap-4 md:flex">
            <NavGroup label="Ticket workspace" items={PRIMARY_NAV} />
            <Separator orientation="vertical" className="h-5" />
            <NavGroup label="Intake channels" items={INTAKE_NAV} />
          </div>

          <div className="ml-auto flex items-center gap-2">
            {isDevAuth ? (
              <Badge variant="secondary">
                <span className="sm:hidden">Dev</span>
                <span className="hidden sm:inline">Development access</span>
              </Badge>
            ) : null}
            <ThemeToggle />
            <Separator orientation="vertical" className="mx-1 h-6" />
            <UserMenu
              identity={identity}
              canLogout={!isDevAuth}
              logoutPending={logoutAction.pending}
              onLogout={() => void logoutAction.run(logout)}
            />
          </div>
        </div>

        <nav
          aria-label="Mobile navigation"
          className="grid grid-cols-2 gap-1 border-t border-border/40 px-4 py-2 sm:grid-cols-4 md:hidden"
        >
          {[...PRIMARY_NAV, ...INTAKE_NAV, ...UTILITY_NAV].map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => navLinkClass(isActive, true)}
            >
              <item.icon className="size-4" />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </header>

      {logoutAction.error ? (
        <div className="mx-auto w-full max-w-7xl px-4 pt-4 sm:px-6">
          <Alert variant="destructive">
            <AlertCircle aria-hidden />
            <AlertTitle>Could not sign out</AlertTitle>
            <AlertDescription>{logoutAction.error}</AlertDescription>
          </Alert>
        </div>
      ) : null}

      <main
        key={location.pathname}
        id={MAIN_CONTENT_ID}
        tabIndex={-1}
        // --app-chrome is the vertical space this shell occupies above a
        // full-height route (header, main padding, page heading). It lives
        // here, next to the chrome it measures, so a board sizing itself
        // against it cannot drift when the header changes. Mobile is taller:
        // it carries a second nav row.
        className="mx-auto w-full max-w-7xl flex-1 animate-fade-in px-4 py-6 outline-none [--app-chrome:17.5rem] sm:px-6 md:[--app-chrome:13.75rem]"
      >
        <RouteSuspense>
          <Outlet />
        </RouteSuspense>
      </main>
      <RouteAnnouncer />

      <footer className="border-t border-border/60 bg-muted/30 py-4 text-center text-xs text-muted-foreground">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-3 gap-y-1 px-4">
          <span className="inline-flex items-center gap-2">
            <Scale className="size-4" />
            Judiciary of Eswatini — Master of the High Court
          </span>
          <span aria-hidden>·</span>
          <span>v0.1.0</span>
          <span aria-hidden>·</span>
          <span>build {__BUILD_ID__}</span>
        </div>
      </footer>
    </div>
  );
}

function UserMenu({
  identity,
  canLogout,
  logoutPending,
  onLogout,
}: {
  identity: StaffIdentity;
  canLogout: boolean;
  logoutPending: boolean;
  onLogout: () => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label={`User menu for ${identity.label}`}
          >
            <Avatar className="size-7">
              <AvatarFallback className="bg-primary/15 text-xs font-semibold text-primary">
                {identity.initials}
              </AvatarFallback>
            </Avatar>
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal">
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">{identity.label}</span>
              <span className="text-xs text-muted-foreground">
                {identity.username}
              </span>
            </div>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          {canLogout ? (
            <DropdownMenuItem
              onClick={onLogout}
              closeOnClick={false}
              disabled={logoutPending}
            >
              {logoutPending ? (
                <Spinner aria-hidden data-icon="inline-start" />
              ) : (
                <LogOut data-icon="inline-start" />
              )}
              {logoutPending ? "Signing out…" : "Sign out"}
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuItem render={<Link to="/health" />}>
            <HeartPulse data-icon="inline-start" />
            System health
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

interface StaffIdentity {
  label: string;
  username: string;
  initials: string;
}

function normalizeIdentity(user: AuthUser | null): StaffIdentity {
  const displayName = user?.displayName?.trim() ?? "";
  const username = user?.username?.trim() ?? "";
  const label = displayName || username || "Signed-in user";
  const parts = label.split(/\s+/).filter(Boolean);
  const first = Array.from(parts[0] ?? "");
  const last = Array.from(parts.at(-1) ?? "");
  const initials =
    parts.length === 1
      ? first.slice(0, 2).join("").toLocaleUpperCase()
      : `${first[0] ?? ""}${last[0] ?? ""}`.toLocaleUpperCase();

  return {
    label,
    username: username || "Authenticated account",
    initials,
  };
}
