import { NavLink, Link, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  ListChecks,
  KanbanSquare,
  Phone,
  User,
  Globe,
  HeartPulse,
  LogIn,
  Search,
  Scale,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { BrandLockup } from "./brand";
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
import { Separator } from "./ui/separator";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
}

const PRIMARY_NAV: NavItem[] = [
  { to: "/tickets", end: true, label: "Queue", icon: ListChecks },
  { to: "/kanban", label: "Kanban", icon: KanbanSquare },
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
];

const INTAKE_NAV: NavItem[] = [
  { to: "/intake/call", label: "Call", icon: Phone },
  { to: "/intake/walk-in", label: "Walk-in", icon: User },
  { to: "/public", label: "Public form", icon: Globe },
];

const UTILITY_NAV: NavItem[] = [
  { to: "/health", label: "Health", icon: HeartPulse },
];

function navLinkClass(active: boolean, touchSafe = false) {
  return cn(
    "inline-flex min-h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-sm transition-colors",
    "focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
    touchSafe && "min-h-11",
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

export function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  return (
    <div className="flex min-h-full flex-col bg-background">
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex w-full max-w-7xl items-center gap-4 px-4 py-2 sm:px-6">
          <Link
            to="/"
            className="flex items-center gap-2 text-foreground no-underline"
          >
            <BrandLockup size="sm" />
          </Link>

          <Separator orientation="vertical" className="mx-1 h-6" />

          <div className="hidden flex-1 items-center gap-4 md:flex">
            <NavGroup label="Ticket workspace" items={PRIMARY_NAV} />
            <Separator orientation="vertical" className="h-5" />
            <NavGroup label="Intake channels" items={INTAKE_NAV} />
          </div>

          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              className="hidden text-muted-foreground lg:inline-flex"
              aria-label="Search"
            >
              <Search data-icon="inline-start" />
              <span className="text-xs">Search</span>
              <kbd className="ml-2 hidden rounded border border-border/60 bg-muted px-2 font-mono text-[10px] text-muted-foreground lg:inline">
                ⌘K
              </kbd>
            </Button>
            <ThemeToggle />
            <Separator orientation="vertical" className="mx-1 h-6" />
            <UserMenu />
          </div>
        </div>

        <nav
          aria-label="Mobile navigation"
          className="flex gap-1 overflow-x-auto border-t border-border/40 px-4 py-2 md:hidden"
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

      <main
        key={location.pathname}
        className="mx-auto w-full max-w-7xl flex-1 animate-fade-in px-4 py-6 sm:px-6"
      >
        {children}
      </main>

      <footer className="border-t border-border/60 bg-muted/30 py-4 text-center text-xs text-muted-foreground">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-center gap-x-3 gap-y-1 px-4">
          <span className="inline-flex items-center gap-2">
            <Scale className="size-4" />
            Judiciary of Eswatini — Master of the High Court
          </span>
          <span aria-hidden>·</span>
          <span>v0.1.0</span>
          <span aria-hidden>·</span>
          <span>build {new Date().getFullYear()}</span>
        </div>
      </footer>
    </div>
  );
}

function UserMenu() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" aria-label="User menu">
            <Avatar className="size-7">
              <AvatarFallback className="bg-primary/15 text-xs font-semibold text-primary">
                OP
              </AvatarFallback>
            </Avatar>
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal">
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">Signed in (dev)</span>
              <span className="text-xs text-muted-foreground">
                Bearer dev:demo:ops-agents
              </span>
            </div>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem render={<Link to="/login" />}>
            <LogIn data-icon="inline-start" />
            Sign in with Keycloak
          </DropdownMenuItem>
          <DropdownMenuItem render={<Link to="/health" />}>
            <HeartPulse data-icon="inline-start" />
            System health
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
