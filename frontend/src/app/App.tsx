import { lazy } from "react";
import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/app-shell";
import { PublicShell } from "@/components/public-shell";
import { TooltipProvider } from "@/components/ui/tooltip";
import HealthPage from "@/features/health/HealthPage";
import LoginPage from "@/features/auth/LoginPage";
import PermissionPage from "@/features/auth/PermissionPage";
import { ProtectedRoute } from "@/features/auth/ProtectedRoute";
import NotFoundPage from "@/features/public/NotFoundPage";

// Entry, permission and diagnostic surfaces stay eager: they are small, and
// they are what a user reaches when something is already wrong. Everything
// behind the auth gate is split, so opening the queue no longer downloads the
// Kanban drag engine and the dashboard tables first.
const HomePage = lazy(() => import("@/features/home/HomePage"));
const QueuePage = lazy(() => import("@/features/tickets/QueuePage"));
const KanbanPage = lazy(() => import("@/features/tickets/KanbanPage"));
const TicketDetailPage = lazy(
  () => import("@/features/tickets/TicketDetailPage"),
);
const TicketTrackingPage = lazy(
  () => import("@/features/tickets/TicketTrackingPage"),
);
const DashboardPage = lazy(() => import("@/features/reports/DashboardPage"));
const ChannelIntakePage = lazy(
  () => import("@/features/tickets/ChannelIntakePage"),
);

export default function App() {
  return (
    <TooltipProvider>
      <Routes>
        <Route element={<PublicShell />}>
          <Route path="/health" element={<HealthPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forbidden" element={<PermissionPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/tickets" element={<QueuePage />} />
            <Route path="/ticket-tracking" element={<TicketTrackingPage />} />
            <Route path="/tickets/:number" element={<TicketDetailPage />} />
            <Route path="/kanban" element={<KanbanPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route
              path="/intake/call"
              element={
                <ChannelIntakePage
                  channel="call"
                  title="Call-centre capture"
                  description="Capture a call-centre enquiry on behalf of a requester."
                />
              }
            />
            <Route
              path="/intake/walk-in"
              element={
                <ChannelIntakePage
                  channel="walk_in"
                  title="Walk-in capture"
                  description="Capture a walk-in visit and issue a ticket number."
                />
              }
            />
          </Route>
        </Route>
      </Routes>
    </TooltipProvider>
  );
}
