import { describe, expect, it, afterEach } from "vitest";
import { getSiteBranding } from "../lib/siteContext.ts";

describe("getSiteBranding", () => {
  it("detects the Azure host", () => {
    document.documentElement.dataset.siteHostname = "azure.movedocs.com";
    window.history.replaceState({}, "", "/");
    expect(getSiteBranding().scope).toBe("azure");
    expect(getSiteBranding().appName).toBe("MoveDocs Azure Portal");
  });

  it("falls back to the primary host", () => {
    document.documentElement.dataset.siteHostname = "it-app.movedocs.com";
    window.history.replaceState({}, "", "/");
    expect(getSiteBranding().scope).toBe("primary");
  });

  it("detects the hrapp host", () => {
    document.documentElement.dataset.siteHostname = "hrapp.movedocs.com";
    window.history.replaceState({}, "", "/");
    expect(getSiteBranding().scope).toBe("hrapp");
    expect(getSiteBranding().appName).toBe("AskHR Portal");
  });
});

describe("retention host branding", () => {
  afterEach(() => {
    delete document.documentElement.dataset.siteHostname;
  });

  it("returns the retention scope for retention.movedocs.com", () => {
    document.documentElement.dataset.siteHostname = "retention.movedocs.com";
    const branding = getSiteBranding();
    expect(branding.scope).toBe("retention");
    expect(branding.appName).toBe("Teams Retention");
  });
});
