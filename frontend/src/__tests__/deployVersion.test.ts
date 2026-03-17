import { describe, expect, it } from "vitest";
import { extractEntrypointScriptPath, getCurrentEntrypointScriptPath } from "../lib/deployVersion.ts";

describe("deployVersion helpers", () => {
  it("extracts the latest module entry script path from html", () => {
    const html = `
      <!doctype html>
      <html>
        <head>
          <script type="module" crossorigin src="/assets/index-abc123.js"></script>
        </head>
      </html>
    `;

    expect(extractEntrypointScriptPath(html, "https://oasisdev.movedocs.com")).toBe("/assets/index-abc123.js");
  });

  it("reads the current module entry script path from the document", () => {
    document.head.innerHTML = '<script type="module" src="/assets/index-old456.js"></script>';

    expect(getCurrentEntrypointScriptPath(document, "https://oasisdev.movedocs.com")).toBe("/assets/index-old456.js");
  });
});
