import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/app-shell";
import { TooltipProvider } from "@/components/ui/tooltip";
import HealthPage from "@/features/health/HealthPage";
import LoginPage from "@/features/auth/LoginPage";
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
      <AppShell>
        <Routes>
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
          <Route path="/public" element={<PublicFormPage />} />
          <Route path="/health" element={<HealthPage />} />
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </AppShell>
    </TooltipProvider>
  );
}
