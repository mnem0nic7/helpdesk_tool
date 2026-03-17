function normalizeAssetPath(value: string, origin: string): string {
  try {
    return new URL(value, origin).pathname;
  } catch {
    return value;
  }
}

export function extractEntrypointScriptPath(html: string, origin: string): string | null {
  if (!html) return null;
  if (typeof DOMParser !== "undefined") {
    const doc = new DOMParser().parseFromString(html, "text/html");
    return getCurrentEntrypointScriptPath(doc, origin);
  }
  const match = html.match(/<script[^>]+src=["']([^"']+)["'][^>]*>/i);
  if (!match?.[1] || !/type=["']module["']/i.test(match[0])) return null;
  return normalizeAssetPath(match[1], origin);
}

export function getCurrentEntrypointScriptPath(doc: Document, origin: string): string | null {
  const script = doc.querySelector('script[type="module"][src]');
  const src = script?.getAttribute("src");
  if (!src) return null;
  return normalizeAssetPath(src, origin);
}

export async function hasNewFrontendBuild(doc: Document, win: Window): Promise<boolean> {
  const currentPath = getCurrentEntrypointScriptPath(doc, win.location.origin);
  if (!currentPath) return false;

  const response = await win.fetch("/", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) {
    throw new Error(`Version check failed (${response.status})`);
  }

  const html = await response.text();
  const latestPath = extractEntrypointScriptPath(html, win.location.origin);
  return !!latestPath && latestPath !== currentPath;
}
