import { describe, expect, it } from "vitest";
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
});
