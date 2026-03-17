import { useCallback, useEffect, useRef, useState } from "react";

export default function useInfiniteScrollCount(
  totalCount: number,
  pageSize = 20,
  resetKey = "",
) {
  const initialCount = totalCount > 0 ? Math.min(pageSize, totalCount) : 0;
  const [visibleCount, setVisibleCount] = useState(initialCount);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setVisibleCount(initialCount);
  }, [initialCount, resetKey]);

  const loadMore = useCallback(() => {
    setVisibleCount((current) => Math.min(current + pageSize, totalCount));
  }, [pageSize, totalCount]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || visibleCount >= totalCount) {
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          loadMore();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [loadMore, totalCount, visibleCount]);

  return {
    hasMore: visibleCount < totalCount,
    sentinelRef,
    visibleCount,
  };
}
