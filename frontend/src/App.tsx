import { Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";

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
  return (
    <BrowserRouter>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="tickets" element={<TicketsPage />} />
            <Route path="manage" element={<ManagePage />} />
            <Route path="sla" element={<SLAPage />} />
            <Route path="visualizations" element={<VisualizationsPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="triage" element={<TriagePage />} />
            <Route path="ai-log" element={<AILogPage />} />
            <Route path="alerts" element={<AlertsPage />} />
            <Route path="knowledge-base" element={<KnowledgeBasePage />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
