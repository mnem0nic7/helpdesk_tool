import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import CacheStatusBar from "./CacheStatusBar.tsx";
import AzureStatusBar from "./AzureStatusBar.tsx";
import AzureQuickJump from "./AzureQuickJump.tsx";
import { api } from "../lib/api.ts";
import { hasNewFrontendBuild } from "../lib/deployVersion.ts";
import { logClientError } from "../lib/errorLogging.ts";
import { getSiteBranding } from "../lib/siteContext.ts";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  primaryOnly?: boolean;
  end?: boolean;
}

const helpdeskNavItems: NavItem[] = [
  { to: "/", label: "Dashboard", icon: "\u25A3" },
  { to: "/tickets", label: "Tickets", icon: "\u25C9" },
  { to: "/manage", label: "Manage", icon: "\u2699" },
  { to: "/sla", label: "SLA Tracker", icon: "\u25C8" },
  { to: "/visualizations", label: "Visualizations", icon: "\u25E7" },
  { to: "/reports", label: "Reports", icon: "\u25A4" },
  { to: "/triage", label: "AI Triage", icon: "\u25C6" },
  { to: "/ai-log", label: "AI Log", icon: "\u25CB" },
  { to: "/alerts", label: "Alerts", icon: "\u25B3" },
  { to: "/tools", label: "Tools", icon: "\u2692", primaryOnly: true },
  { to: "/users", label: "Users", icon: "\u25C7", primaryOnly: true },
  { to: "/active-directory", label: "Active Directory", icon: "\u25A6", primaryOnly: true },
  { to: "/knowledge-base", label: "Knowledge Base", icon: "\u25A9", primaryOnly: true },
];

const azureNavItems: NavItem[] = [
  { to: "/", label: "Overview", icon: "overview" },
  { to: "/vms", label: "VMs", icon: "vms" },
  { to: "/virtual-desktops", label: "Desktops", icon: "desktops" },
  { to: "/compute", label: "Compute", icon: "compute" },
  { to: "/resources", label: "Resources", icon: "resources" },
  { to: "/storage", label: "Storage", icon: "storage" },
  { to: "/tools", label: "Tools", icon: "tools" },
  { to: "/cost", label: "Cost", icon: "cost" },
  { to: "/allocations", label: "Allocation", icon: "allocation" },
  { to: "/ai-costs", label: "AI Cost", icon: "ai-costs" },
  { to: "/savings", label: "Savings", icon: "savings" },
  { to: "/copilot", label: "Copilot", icon: "copilot" },
  { to: "/alerts", label: "Alerts", icon: "alerts" },
];

interface NavGroup {
  label: string;
  items: NavItem[];
}

const securityNavGroups: NavGroup[] = [
  {
    label: "Agent",
    items: [
      { to: "/security/agent", label: "Defender", icon: "defender" },
      { to: "/security/playbooks", label: "Playbooks", icon: "playbooks" },
    ],
  },
  {
    label: "Workspace",
    items: [
      { to: "/security", label: "Overview", icon: "security", end: true },
      { to: "/security/copilot", label: "Copilot", icon: "copilot" },
      { to: "/tools", label: "Tools", icon: "tools" },
    ],
  },
  {
    label: "Review Lanes",
    items: [
      { to: "/security/access-review", label: "Access", icon: "account-health" },
      { to: "/security/identity-review", label: "Identity", icon: "identity" },
      { to: "/security/user-review", label: "Users", icon: "users" },
      { to: "/security/guest-access-review", label: "Guests", icon: "users" },
      { to: "/security/app-hygiene", label: "Apps", icon: "resources" },
      { to: "/security/device-compliance", label: "Devices", icon: "vms" },
      { to: "/security/account-health", label: "Account Health", icon: "account-health" },
      { to: "/security/dlp-review", label: "DLP", icon: "alerts" },
      { to: "/security/conditional-access-tracker", label: "Policies", icon: "alerts" },
      { to: "/security/break-glass-validation", label: "Break-glass", icon: "account-health" },
      { to: "/security/directory-role-review", label: "Roles", icon: "identity" },
    ],
  },
];

const _NAV_GROUP_STORAGE_KEY = "security_nav_collapsed";

function SecurityGroupedNav({ pathname }: { pathname: string }) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem(_NAV_GROUP_STORAGE_KEY) || "{}");
    } catch {
      return {};
    }
  });

  function toggle(label: string) {
    setCollapsed(prev => {
      const next = { ...prev, [label]: !prev[label] };
      try { localStorage.setItem(_NAV_GROUP_STORAGE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  }

  return (
    <nav className="flex-1 space-y-3 px-3 py-4 overflow-y-auto">
      {securityNavGroups.map(group => {
        const isActiveGroup = group.items.some(item =>
          item.end ? pathname === item.to : pathname.startsWith(item.to)
        );
        const isCollapsed = collapsed[group.label] && !isActiveGroup;

        return (
          <div key={group.label}>
            <button
              onClick={() => toggle(group.label)}
              className="flex w-full items-center justify-between px-2 py-1 text-xs font-semibold uppercase tracking-wider text-slate-400 hover:text-slate-200 transition-colors"
            >
              <span>{group.label}</span>
              <svg
                aria-hidden="true"
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                className={`transition-transform ${isCollapsed ? "-rotate-90" : ""}`}
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {!isCollapsed && (
              <div className="mt-1 space-y-1">
                {group.items.map(({ to, label, icon, end }) => (
                  <NavLink
                    key={to}
                    to={to}
                    end={end ?? to === "/"}
                    className={({ isActive }) =>
                      [
                        "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                        isActive
                          ? "bg-slate-700 text-white"
                          : "text-slate-300 hover:bg-slate-800 hover:text-white",
                      ].join(" ")
                    }
                  >
                    <span className="flex h-5 w-5 items-center justify-center text-current">
                      <AzureSidebarIcon icon={icon} />
                    </span>
                    {label}
                  </NavLink>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}

const azureBreadcrumbLabels: Record<string, string> = {
  "": "Overview",
  vms: "VMs",
  "virtual-desktops": "Desktops",
  compute: "Compute",
  resources: "Resources",
  storage: "Storage",
  identity: "Identity",
  security: "Security",
  users: "Users",
  tools: "Tools",
  cost: "Cost",
  allocations: "Allocation",
  "ai-costs": "AI Cost",
  savings: "Savings",
  copilot: "Copilot",
  alerts: "Alerts",
  "account-health": "Account Health",
};

function AzureSidebarIcon({ icon }: { icon: string }) {
  const common = {
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  switch (icon) {
    case "overview":
      return <svg aria-hidden="true" {...common}><rect x="3" y="4" width="7" height="7" rx="1.5" /><rect x="14" y="4" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="8" rx="1.5" /><rect x="3" y="14" width="7" height="6" rx="1.5" /></svg>;
    case "vms":
      return <svg aria-hidden="true" {...common}><rect x="3" y="5" width="18" height="11" rx="2" /><path d="M7 19h10" /><path d="M9 16v3" /><path d="M15 16v3" /></svg>;
    case "desktops":
      return <svg aria-hidden="true" {...common}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8" /><path d="M12 16v4" /><path d="M7 9h10" /></svg>;
    case "compute":
      return <svg aria-hidden="true" {...common}><path d="M12 3l7 4v10l-7 4-7-4V7l7-4z" /><path d="M12 7v10" /><path d="M5 9l7 4 7-4" /></svg>;
    case "resources":
      return <svg aria-hidden="true" {...common}><path d="M12 4l8 4-8 4-8-4 8-4z" /><path d="M4 12l8 4 8-4" /><path d="M4 16l8 4 8-4" /></svg>;
    case "storage":
      return <svg aria-hidden="true" {...common}><ellipse cx="12" cy="6" rx="7.5" ry="3" /><path d="M4.5 6v8c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6" /><path d="M4.5 10c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3" /></svg>;
    case "identity":
      return <svg aria-hidden="true" {...common}><circle cx="9" cy="9" r="3" /><path d="M4 19c.9-2.7 3.2-4 5-4s4.1 1.3 5 4" /><path d="M17 8h4" /><path d="M19 6v4" /></svg>;
    case "security":
      return <svg aria-hidden="true" {...common}><path d="M12 3 5.5 5.8v5c0 5.4 6.5 9.2 6.5 9.2s6.5-3.8 6.5-9.2v-5L12 3Z" /><path d="m9.5 11.8 1.7 1.7 3.8-4" /></svg>;
    case "users":
      return <svg aria-hidden="true" {...common}><circle cx="8" cy="8" r="3" /><circle cx="17" cy="9" r="2.5" /><path d="M3.5 19c.8-2.8 3.1-4.2 4.5-4.2 1.5 0 3.8 1.4 4.6 4.2" /><path d="M14 19c.5-1.8 1.9-3.1 3.5-3.1 1 0 2.2.5 3 1.7" /></svg>;
    case "tools":
      return <svg aria-hidden="true" {...common}><path d="m14.5 6.5 3 3" /><path d="m11 10 7-7" /><path d="m9 12-6 6v3h3l6-6" /><path d="m15 12 3 3" /></svg>;
    case "cost":
      return <svg aria-hidden="true" {...common}><path d="M12 3v18" /><path d="M17 7.5c0-1.7-2.2-3-5-3s-5 1.3-5 3 1.4 2.5 5 3 5 1.3 5 3-2.2 3-5 3-5-1.3-5-3" /></svg>;
    case "allocation":
      return <svg aria-hidden="true" {...common}><path d="M12 4v16" /><path d="M5 9h14" /><path d="M5 15h8" /><circle cx="17" cy="15" r="2" /></svg>;
    case "ai-costs":
      return <svg aria-hidden="true" {...common}><path d="M8 8a4 4 0 1 1 8 0c0 1.6-.8 2.8-2 3.6V14a2 2 0 0 1-4 0v-2.4A4.4 4.4 0 0 1 8 8Z" /><path d="M9 20h6" /><path d="M10 17h4" /></svg>;
    case "savings":
      return <svg aria-hidden="true" {...common}><path d="M6 12l4 4 8-8" /><path d="M5 5h4v4" /><path d="M19 19h-4v-4" /></svg>;
    case "copilot":
      return <svg aria-hidden="true" {...common}><path d="M12 3 6.5 6.2v6.6L12 16l5.5-3.2V6.2L12 3Z" /><path d="M12 8.2 9.2 9.8v3.4L12 14.8l2.8-1.6V9.8L12 8.2Z" /></svg>;
    case "alerts":
      return <svg aria-hidden="true" {...common}><path d="M10 4h4l6 13H4L10 4Z" /><path d="M12 9v3" /><path d="M12 15h.01" /></svg>;
    case "account-health":
      return <svg aria-hidden="true" {...common}><path d="M12 20s-6.5-3.8-6.5-9.2V5.8L12 3l6.5 2.8v5c0 5.4-6.5 9.2-6.5 9.2Z" /><path d="m9.5 11.5 1.7 1.7 3.6-3.6" /></svg>;
    case "defender":
      return <svg aria-hidden="true" {...common}><path d="M12 3 5.5 5.8v5c0 5.4 6.5 9.2 6.5 9.2s6.5-3.8 6.5-9.2v-5L12 3Z" /><path d="M9 12l2 2 4-4" /></svg>;
    case "playbooks":
      return <svg aria-hidden="true" {...common}><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M8 9h8" /><path d="M8 13h5" /><circle cx="16" cy="14" r="2" /></svg>;
    default:
      return <span className="text-base leading-none">{icon}</span>;
  }
}

export default function Layout() {
  const branding = getSiteBranding();
  const navItems = branding.scope === "azure" ? azureNavItems : helpdeskNavItems;
  const location = useLocation();
  const versionCheckInFlight = useRef(false);
  const lastVersionCheckAt = useRef(0);
  const { data: user, isLoading } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.getMe(),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    document.title = branding.appName;
  }, [branding.appName]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof document === "undefined") return undefined;

    async function checkForNewBuild(force = false) {
      if (versionCheckInFlight.current) return;
      const now = Date.now();
      if (!force && now - lastVersionCheckAt.current < 15_000) return;

      versionCheckInFlight.current = true;
      lastVersionCheckAt.current = now;
      try {
        if (await hasNewFrontendBuild(document, window)) {
          window.location.reload();
        }
      } catch (err) {
        logClientError("Frontend build version check failed", err);
      } finally {
        versionCheckInFlight.current = false;
      }
    }

    void checkForNewBuild(true);

    const handleFocus = () => {
      void checkForNewBuild();
    };

    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [location.key]);

  const azureBreadcrumbs = useMemo(() => {
    if (branding.scope !== "azure" && branding.scope !== "security") return [];
    const path = location.pathname.replace(/^\/+/, "");
    const [segment, subsegment] = path.split("/");
    const currentLabel = azureBreadcrumbLabels[segment || ""] || "Azure";
    const params = new URLSearchParams(location.search);
    let detailLabel = "";
    if (segment === "security" && subsegment === "access-review") detailLabel = "Privileged Access Review";
    if (segment === "security" && subsegment === "break-glass-validation") detailLabel = "Break-glass Account Validation";
    if (segment === "security" && subsegment === "conditional-access-tracker") detailLabel = "Conditional Access Change Tracker";
    if (segment === "security" && subsegment === "device-compliance") detailLabel = "Device Compliance Review";
    if (segment === "security" && subsegment === "directory-role-review") detailLabel = "Directory Role Membership Review";
    if (segment === "security" && subsegment === "identity-review") detailLabel = "Identity Review";
    if (segment === "security" && subsegment === "guest-access-review") detailLabel = "Guest Access Review";
    if (segment === "security" && subsegment === "dlp-review") detailLabel = "DLP Findings Review";
    if (segment === "security" && subsegment === "app-hygiene") detailLabel = "Application Hygiene";
    if (segment === "security" && subsegment === "user-review") detailLabel = "User Review";
    if (segment === "security" && subsegment === "copilot") detailLabel = "Security Copilot";
    if (segment === "security" && subsegment === "account-health") detailLabel = "Account Health";
    if (segment === "security" && subsegment === "agent") detailLabel = "Defender Agent";
    if (segment === "security" && subsegment === "playbooks") detailLabel = "Defender Playbooks";
    if (segment === "vms" && params.get("vmId")) detailLabel = "VM Detail";
    if (segment === "virtual-desktops" && params.get("desktopId")) detailLabel = "Desktop Detail";
    if (segment === "resources" && params.get("resourceId")) detailLabel = "Resource Detail";
    if (segment === "users" && params.get("userId")) detailLabel = "User Detail";
    if (segment === "identity" && params.get("objectId")) detailLabel = "Directory Detail";
    return [
      { label: "Azure", current: false },
      { label: currentLabel, current: !detailLabel },
      ...(detailLabel ? [{ label: detailLabel, current: true }] : []),
    ];
  }, [branding.scope, location.pathname, location.search]);

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
        {branding.scope === "security" ? (
          <SecurityGroupedNav pathname={location.pathname} />
        ) : (
          <nav className="flex-1 space-y-1 px-3 py-4">
            {navItems
              .filter((item) => (!item.primaryOnly || branding.scope === "primary"))
              .map(({ to, label, icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end ?? to === "/"}
                  className={({ isActive }) =>
                    [
                      "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-slate-700 text-white"
                        : "text-slate-300 hover:bg-slate-800 hover:text-white",
                    ].join(" ")
                  }
                >
                  {branding.scope === "azure" ? (
                    <span className="flex h-5 w-5 items-center justify-center text-current">
                      <AzureSidebarIcon icon={icon} />
                    </span>
                  ) : (
                    <span className="text-base leading-none">{icon}</span>
                  )}
                  {label}
                </NavLink>
              ))}
          </nav>
        )}

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
        {(branding.scope === "azure" || branding.scope === "security") ? (
          <>
            <AzureStatusBar isAdmin={!!user?.is_admin} />
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2 text-sm text-slate-500">
                {azureBreadcrumbs.map((item, index) => (
                  <div key={`${item.label}-${index}`} className="flex items-center gap-2">
                    {index > 0 ? <span className="text-slate-300">/</span> : null}
                    <span className={item.current ? "font-semibold text-slate-900" : ""}>{item.label}</span>
                  </div>
                ))}
              </div>
              {branding.scope === "azure" && <AzureQuickJump />}
            </div>
          </>
        ) : (
          <CacheStatusBar />
        )}
        <Outlet />
      </main>
    </div>
  );
}
