export interface SiteBranding {
  scope: "primary" | "oasisdev" | "azure";
  appName: string;
  dashboardName: string;
  alertPrefix: string;
}

function isOasisDevHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return host === "oasisdev.movedocs.com" || host.startsWith("oasisdev.");
}

function isAzureHost(hostname: string): boolean {
  const host = hostname.trim().toLowerCase();
  return host === "azure.movedocs.com" || host.startsWith("azure.");
}

function getCurrentHostname(): string {
  if (typeof document !== "undefined") {
    const testHost = document.documentElement.dataset.siteHostname;
    if (testHost) return testHost;
  }
  if (typeof window !== "undefined") {
    return window.location.hostname;
  }
  return "";
}

export function getSiteBranding(): SiteBranding {
  const hostname = getCurrentHostname();

  if (isAzureHost(hostname)) {
    return {
      scope: "azure",
      appName: "MoveDocs Azure Portal",
      dashboardName: "Azure Control Center",
      alertPrefix: "Azure",
    };
  }

  if (isOasisDevHost(hostname)) {
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
