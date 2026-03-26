import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import { getSiteBranding } from "./lib/siteContext";

const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const TicketsPage = lazy(() => import("./pages/TicketsPage"));
const ManagePage = lazy(() => import("./pages/ManagePage"));
const SLAPage = lazy(() => import("./pages/SLAPage"));
const VisualizationsPage = lazy(() => import("./pages/VisualizationsPage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));
const TriagePage = lazy(() => import("./pages/TriagePage"));
const AILogPage = lazy(() => import("./pages/AILogPage"));
const AlertsPage = lazy(() => import("./pages/AlertsPage"));
const KnowledgeBasePage = lazy(() => import("./pages/KnowledgeBasePage"));
const UsersPage = lazy(() => import("./pages/UsersPage"));
const ToolsPage = lazy(() => import("./pages/ToolsPage"));
const AzureOverviewPage = lazy(() => import("./pages/AzureOverviewPage"));
const AzureVMsPage = lazy(() => import("./pages/AzureVMsPage"));
const AzureResourcesPage = lazy(() => import("./pages/AzureResourcesPage"));
const AzureIdentityPage = lazy(() => import("./pages/AzureIdentityPage"));
const AzureCostPage = lazy(() => import("./pages/AzureCostPage"));
const AzureAllocationPage = lazy(() => import("./pages/AzureAllocationPage"));
const AzureAICostPage = lazy(() => import("./pages/AzureAICostPage"));
const AzureSavingsPage = lazy(() => import("./pages/AzureSavingsPage"));
const AzureCopilotPage = lazy(() => import("./pages/AzureCopilotPage"));
const AzureStoragePage = lazy(() => import("./pages/AzureStoragePage"));
const AzureComputeOptimizationPage = lazy(() => import("./pages/AzureComputeOptimizationPage.tsx"));
const AzureUsersPage = lazy(() => import("./pages/AzureUsersPage"));
const AzureAlertsPage = lazy(() => import("./pages/AzureAlertsPage"));
const AzureAccountHealthPage = lazy(() => import("./pages/AzureAccountHealthPage"));
const AzureVirtualDesktopsPage = lazy(() => import("./pages/AzureVirtualDesktopsPage"));

function PageFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        <span>Loading page...</span>
      </div>
    </div>
  );
}

export default function App() {
  const branding = getSiteBranding();
  const isAzureSite = branding.scope === "azure";

  return (
    <BrowserRouter>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route element={<Layout />}>
            {isAzureSite ? (
              <>
                <Route index element={<AzureOverviewPage />} />
                <Route path="vms" element={<AzureVMsPage />} />
                <Route path="virtual-desktops" element={<AzureVirtualDesktopsPage />} />
                <Route path="resources" element={<AzureResourcesPage />} />
                <Route path="identity" element={<AzureIdentityPage />} />
                <Route path="users" element={<AzureUsersPage />} />
                <Route path="tools" element={<ToolsPage />} />
                <Route path="cost" element={<AzureCostPage />} />
                <Route path="allocations" element={<AzureAllocationPage />} />
                <Route path="ai-costs" element={<AzureAICostPage />} />
                <Route path="savings" element={<AzureSavingsPage />} />
                <Route path="storage" element={<AzureStoragePage />} />
                <Route path="compute" element={<AzureComputeOptimizationPage />} />
                <Route path="copilot" element={<AzureCopilotPage />} />
                <Route path="alerts" element={<AzureAlertsPage />} />
                <Route path="account-health" element={<AzureAccountHealthPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </>
            ) : (
              <>
                <Route index element={<DashboardPage />} />
                <Route path="tickets" element={<TicketsPage />} />
                <Route path="manage" element={<ManagePage />} />
                <Route path="sla" element={<SLAPage />} />
                <Route path="visualizations" element={<VisualizationsPage />} />
                <Route path="reports" element={<ReportsPage />} />
                <Route path="triage" element={<TriagePage />} />
                <Route path="ai-log" element={<AILogPage />} />
                <Route path="alerts" element={<AlertsPage />} />
                {branding.scope === "primary" ? <Route path="tools" element={<ToolsPage />} /> : null}
                <Route path="knowledge-base" element={<KnowledgeBasePage />} />
                {branding.scope === "primary" ? <Route path="users" element={<UsersPage />} /> : null}
                <Route path="*" element={<Navigate to="/" replace />} />
              </>
            )}
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
