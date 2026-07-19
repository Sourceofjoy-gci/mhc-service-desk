import { Route, Routes, Link } from "react-router-dom";
import HealthPage from "../features/health/HealthPage";
import LoginPage from "../features/auth/LoginPage";

export default function App() {
  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-ink-100 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
          <Link to="/" className="text-lg font-semibold text-ink-900 no-underline">
            MHC e-Ticketing
          </Link>
          <nav className="flex gap-4 text-sm text-ink-700">
            <Link to="/health">Health</Link>
            <Link to="/login">Sign in</Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-8">
        <Routes>
          <Route path="/" element={<HomePage />} />
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
        This is the agent workspace. The platform separates the Operational and IT service desks
        and routes every request through a transparent, auditable workflow. See the PRD for
        full scope and P0 acceptance criteria.
      </p>
      <ul className="ml-5 list-disc text-ink-700">
        <li>Authenticate via Keycloak OIDC with MFA</li>
        <li>One vertical slice per release milestone</li>
        <li>Server-side authorisation; the UI is decoration</li>
      </ul>
    </section>
  );
}
