export interface SiteBranding {
  scope: "primary" | "oasisdev";
  appName: string;
  dashboardName: string;
  alertPrefix: string;
}

function isOasisDevHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return host === "oasisdev.movedocs.com" || host.startsWith("oasisdev.");
}

export function getSiteBranding(): SiteBranding {
  if (typeof window !== "undefined" && isOasisDevHost(window.location.hostname)) {
    return {
      scope: "oasisdev",
      appName: "OasisDev Helpdesk",
      dashboardName: "OasisDev Dashboard",
      alertPrefix: "OasisDev",
    };
  }

  return {
    scope: "primary",
    appName: "OIT Helpdesk",
    dashboardName: "OIT Dashboard",
    alertPrefix: "OIT",
  };
}
