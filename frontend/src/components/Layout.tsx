import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import CacheStatusBar from "./CacheStatusBar.tsx";
import { api } from "../lib/api.ts";
import { getSiteBranding } from "../lib/siteContext.ts";

const navItems = [
  { to: "/", label: "Dashboard", icon: "\u25A3" },
  { to: "/tickets", label: "Tickets", icon: "\u25C9" },
  { to: "/manage", label: "Manage", icon: "\u2699" },
  { to: "/sla", label: "SLA Tracker", icon: "\u25C8" },
  { to: "/visualizations", label: "Visualizations", icon: "\u25E7" },
  { to: "/reports", label: "Reports", icon: "\u25A4" },
  { to: "/triage", label: "AI Triage", icon: "\u25C6" },
  { to: "/ai-log", label: "AI Log", icon: "\u25CB" },
  { to: "/alerts", label: "Alerts", icon: "\u25B3" },
  { to: "/knowledge-base", label: "Knowledge Base", icon: "\u25A9", primaryOnly: true },
];

export default function Layout() {
  const branding = getSiteBranding();
  const { data: user, isLoading } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.getMe(),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    document.title = branding.appName;
  }, [branding.appName]);

  // While checking auth, show nothing to avoid layout flash
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  // Not authenticated — redirect to login
  if (!user) {
    window.location.href = "/api/auth/login";
    return null;
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="flex w-64 flex-col bg-slate-900 text-slate-200">
        {/* Brand */}
        <div className="flex h-16 items-center gap-2 border-b border-slate-700 px-6">
          <span className="text-lg font-semibold tracking-wide text-white">
            {branding.appName}
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems
            .filter((item) => !item.primaryOnly || branding.scope === "primary")
            .map(({ to, label, icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-slate-700 text-white"
                    : "text-slate-300 hover:bg-slate-800 hover:text-white",
                ].join(" ")
              }
            >
              <span className="text-base leading-none">{icon}</span>
              {label}
            </NavLink>
            ))}
        </nav>

        {/* Footer — user info or version */}
        <div className="border-t border-slate-700 px-4 py-3">
          {user ? (
            <div className="space-y-1">
              <div className="truncate text-sm font-medium text-slate-200">
                {user.name}
              </div>
              <div className="truncate text-xs text-slate-400">
                {user.email}
              </div>
              <button
                onClick={() => api.logout()}
                className="mt-1 text-xs text-slate-500 hover:text-slate-300 transition-colors"
              >
                Sign out
              </button>
            </div>
          ) : (
            <div className="text-xs text-slate-500">{branding.dashboardName} v0.1</div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto bg-gray-50 p-6">
        <CacheStatusBar />
        <Outlet />
      </main>
    </div>
  );
}
