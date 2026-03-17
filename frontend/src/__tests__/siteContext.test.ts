import { describe, expect, it } from "vitest";
import { getSiteBranding } from "../lib/siteContext.ts";

describe("getSiteBranding", () => {
  it("detects the Azure host", () => {
    window.history.replaceState({}, "", "https://azure.movedocs.com/");
    expect(getSiteBranding().scope).toBe("azure");
    expect(getSiteBranding().appName).toBe("MoveDocs Azure Portal");
  });

  it("falls back to the primary host", () => {
    window.history.replaceState({}, "", "https://it-app.movedocs.com/");
    expect(getSiteBranding().scope).toBe("primary");
  });
});
