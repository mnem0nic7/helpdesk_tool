import { afterEach, describe, expect, it } from "vitest";
import {
  createPollingRefetchInterval,
  getPollingQueryOptions,
  resolvePollingIntervalMs,
} from "../lib/queryPolling.ts";

const originalHiddenDescriptor = Object.getOwnPropertyDescriptor(document, "hidden");

function setDocumentHidden(value: boolean) {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value,
  });
}

describe("queryPolling", () => {
  afterEach(() => {
    if (originalHiddenDescriptor) {
      Object.defineProperty(document, "hidden", originalHiddenDescriptor);
    }
  });

  it("returns slow polling defaults for review-style pages", () => {
    const options = getPollingQueryOptions("slow_5m");

    expect(options.staleTime).toBe(5 * 60_000);
    expect(options.refetchOnWindowFocus).toBe(false);
    expect(options.refetchOnReconnect).toBe(false);
    expect(options.refetchIntervalInBackground).toBe(false);
  });

  it("disables interval polling when the document is hidden", () => {
    const refetchInterval = createPollingRefetchInterval("slow_5m");

    setDocumentHidden(true);
    expect(refetchInterval({} as never)).toBe(false);

    setDocumentHidden(false);
    expect(refetchInterval({} as never)).toBe(5 * 60_000);
  });

  it("supports custom short-lived job polling intervals", () => {
    setDocumentHidden(false);
    expect(resolvePollingIntervalMs(2_000)).toBe(2_000);
    expect(resolvePollingIntervalMs(2_000, false)).toBe(false);

    setDocumentHidden(true);
    expect(resolvePollingIntervalMs(2_000)).toBe(false);
  });
});
