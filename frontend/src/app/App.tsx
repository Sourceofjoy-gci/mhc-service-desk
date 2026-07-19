import { Route, Routes, NavLink, Link } from "react-router-dom";
import HealthPage from "../features/health/HealthPage";
import LoginPage from "../features/auth/LoginPage";
import QueuePage from "../features/tickets/QueuePage";
import KanbanPage from "../features/tickets/KanbanPage";
import TicketDetailPage from "../features/tickets/TicketDetailPage";
import DashboardPage from "../features/reports/DashboardPage";
import PublicFormPage from "../features/public/PublicFormPage";
import ChannelIntakePage from "../features/tickets/ChannelIntakePage";
import { clsx } from "clsx";

const navItem = ({ isActive }: { isActive: boolean }) =>
  clsx(
    "rounded-md px-3 py-1.5 text-sm",
    isActive ? "bg-brand-50 text-brand-700" : "text-ink-700 hover:bg-ink-50",
  );

export default function App() {
  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-ink-100 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-6 py-3">
          <Link to="/" className="text-lg font-semibold text-ink-900 no-underline">
            MHC e-Ticketing
          </Link>
          <nav className="flex flex-wrap items-center gap-1 text-sm">
            <NavLink to="/tickets" end className={navItem}>
              Queue
            </NavLink>
            <NavLink to="/kanban" className={navItem}>
              Kanban
            </NavLink>
            <NavLink to="/dashboard" className={navItem}>
              Dashboard
            </NavLink>
            <NavLink to="/intake/call" className={navItem}>
              Call
            </NavLink>
            <NavLink to="/intake/walk-in" className={navItem}>
              Walk-in
            </NavLink>
            <NavLink to="/public" className={navItem}>
              Public form
            </NavLink>
            <span className="mx-2 h-5 w-px bg-ink-100" />
            <NavLink to="/health" className={navItem}>
              Health
            </NavLink>
            <NavLink to="/login" className={navItem}>
              Sign in
            </NavLink>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/tickets" element={<QueuePage />} />
          <Route path="/tickets/:number" element={<TicketDetailPage />} />
          <Route path="/kanban" element={<KanbanPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/intake/call" element={<ChannelIntakePage channel="call" title="Call-centre capture" description="Capture a call-centre enquiry on behalf of a requester." />} />
          <Route path="/intake/walk-in" element={<ChannelIntakePage channel="walk_in" title="Walk-in capture" description="Capture a walk-in visit and issue a ticket number." />} />
          <Route path="/public" element={<PublicFormPage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </main>

      <footer className="border-t border-ink-100 bg-white py-4 text-center text-xs text-ink-500">
        © Judiciary of Eswatini — Master of the High Court
      </footer>
    </div>
  );
}

function HomePage() {
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">Unified e-Ticketing and Service Desk</h1>
      <p className="max-w-3xl text-ink-700">
        Operational and IT service desks with strict separation. Every request
        becomes a traceable ticket with a Kanban workflow, SLA tracking, audit
        trail, and a requester-safe public entry point.
      </p>
      <ul className="ml-5 list-disc text-ink-700">
        <li>Open the <Link to="/tickets">queue</Link> to see and triage work</li>
        <li>Use the <Link to="/kanban">Kanban</Link> for a visual board with drag-and-drop</li>
        <li>Capture a <Link to="/intake/call">call</Link> or <Link to="/intake/walk-in">walk-in</Link></li>
        <li>Try the <Link to="/public">public form</Link> as a requester would</li>
        <li>Inspect system <Link to="/health">health</Link> at any time</li>
      </ul>
    </section>
  );
}
