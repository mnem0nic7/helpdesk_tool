import { act, screen } from "@testing-library/react";
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { render } from "../test-utils.tsx";

type IntersectionObserverCallbackRecord = {
  callback: IntersectionObserverCallback;
};

let observerRecords: IntersectionObserverCallbackRecord[] = [];
let originalIntersectionObserver: typeof IntersectionObserver | undefined;

function Harness({ totalCount, resetKey = "" }: { totalCount: number; resetKey?: string }) {
  const { hasMore, sentinelRef, visibleCount } = useInfiniteScrollCount(totalCount, 20, resetKey);

  return (
    <div>
      <div data-testid="visible-count">{visibleCount}</div>
      {hasMore ? <div ref={sentinelRef}>sentinel</div> : <div>done</div>}
    </div>
  );
}

describe("useInfiniteScrollCount", () => {
  beforeEach(() => {
    observerRecords = [];
    originalIntersectionObserver = globalThis.IntersectionObserver;
    globalThis.IntersectionObserver = vi.fn().mockImplementation((callback: IntersectionObserverCallback) => {
      observerRecords.push({ callback });
      return {
        observe: vi.fn(),
        disconnect: vi.fn(),
        unobserve: vi.fn(),
        takeRecords: vi.fn(),
        root: null,
        rootMargin: "",
        thresholds: [],
      };
    }) as unknown as typeof IntersectionObserver;
  });

  afterEach(() => {
    globalThis.IntersectionObserver = originalIntersectionObserver as typeof IntersectionObserver;
  });

  it("starts at 20 items and loads 20 more when the sentinel intersects", () => {
    render(<Harness totalCount={55} />);

    expect(screen.getByTestId("visible-count").textContent).toBe("20");
    expect(observerRecords).toHaveLength(1);

    act(() => {
      observerRecords[0].callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    });

    expect(screen.getByTestId("visible-count").textContent).toBe("40");
  });

  it("resets back to the first page when the reset key changes", () => {
    const { rerender } = render(<Harness totalCount={55} resetKey="eastus" />);

    act(() => {
      observerRecords[0].callback(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    });

    expect(screen.getByTestId("visible-count").textContent).toBe("40");

    rerender(<Harness totalCount={55} resetKey="westus" />);

    expect(screen.getByTestId("visible-count").textContent).toBe("20");
  });
});
