import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import DashboardPage from "./pages/DashboardPage";
import TicketsPage from "./pages/TicketsPage";
import ManagePage from "./pages/ManagePage";
import SLAPage from "./pages/SLAPage";
import VisualizationsPage from "./pages/VisualizationsPage";
import ReportsPage from "./pages/ReportsPage";
import TriagePage from "./pages/TriagePage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="tickets" element={<TicketsPage />} />
          <Route path="manage" element={<ManagePage />} />
          <Route path="sla" element={<SLAPage />} />
          <Route path="visualizations" element={<VisualizationsPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="triage" element={<TriagePage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
