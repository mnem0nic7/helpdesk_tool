export interface SiteBranding {
  scope: "primary" | "oasisdev";
  appName: string;
  dashboardName: string;
  alertPrefix: string;
}

export function getSiteBranding(): SiteBranding {
  if (typeof window !== "undefined" && window.location.hostname === "oasisdev.movedocs.com") {
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
