import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/app-shell";
import { PublicShell } from "@/components/public-shell";
import { TooltipProvider } from "@/components/ui/tooltip";
import HealthPage from "@/features/health/HealthPage";
import LoginPage from "@/features/auth/LoginPage";
import PermissionPage from "@/features/auth/PermissionPage";
import { ProtectedRoute } from "@/features/auth/ProtectedRoute";
import QueuePage from "@/features/tickets/QueuePage";
import KanbanPage from "@/features/tickets/KanbanPage";
import TicketDetailPage from "@/features/tickets/TicketDetailPage";
import DashboardPage from "@/features/reports/DashboardPage";
import PublicFormPage from "@/features/public/PublicFormPage";
import ChannelIntakePage from "@/features/tickets/ChannelIntakePage";
import HomePage from "@/features/home/HomePage";

export default function App() {
  return (
    <TooltipProvider>
      <Routes>
        <Route element={<PublicShell />}>
          <Route path="/public" element={<PublicFormPage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forbidden" element={<PermissionPage />} />
        </Route>
        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/tickets" element={<QueuePage />} />
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
