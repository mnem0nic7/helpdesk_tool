import type { Query } from "@tanstack/react-query";

export type QueryPollingTier = "live_30s" | "live_60s" | "slow_5m" | "manual_only";

// Review and inventory pages should use the slower tiers by default.
// Faster tiers are reserved for actively changing operational views.
export const QUERY_POLLING_INTERVAL_MS: Record<QueryPollingTier, number | false> = {
  live_30s: 30_000,
  live_60s: 60_000,
  slow_5m: 5 * 60_000,
  manual_only: false,
};

// React Query's `refetchInterval` callback is intentionally tolerant across many
// page-specific query shapes. Using `any` here keeps the shared helper assignable
// without forcing every call site to annotate its full query generic stack.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PollingQuery = Query<any, any, any, any>;
type PollingRefetchInterval =
  | false
  | ((query: PollingQuery) => number | false | undefined);

type SharedPollingQueryOptions = {
  staleTime: number;
  refetchInterval: PollingRefetchInterval;
  refetchIntervalInBackground: false;
  refetchOnWindowFocus: false;
  refetchOnReconnect: false;
};

export function isDocumentVisibleForPolling(): boolean {
  if (typeof document === "undefined") {
    return true;
  }
  return !document.hidden;
}

export function getQueryPollingIntervalMs(tier: QueryPollingTier): number | false {
  return QUERY_POLLING_INTERVAL_MS[tier];
}

export function resolvePollingIntervalMs(
  intervalMs: number | false,
  shouldPoll = true,
): number | false {
  if (!shouldPoll || intervalMs === false) {
    return false;
  }
  return isDocumentVisibleForPolling() ? intervalMs : false;
}

export function resolveQueryPollingInterval(
  tier: QueryPollingTier,
  shouldPoll = true,
): number | false {
  return resolvePollingIntervalMs(getQueryPollingIntervalMs(tier), shouldPoll);
}

export function createPollingRefetchInterval(
  tier: QueryPollingTier,
  shouldPoll: boolean | ((query: PollingQuery) => boolean) = true,
): (query: PollingQuery) => number | false | undefined {
  return (query: PollingQuery): number | false => {
    const enabled = typeof shouldPoll === "function" ? shouldPoll(query) : shouldPoll;
    return resolveQueryPollingInterval(tier, enabled);
  };
}

export function getPollingQueryOptions(
  tier: QueryPollingTier,
  options: { staleTime?: number } = {},
): SharedPollingQueryOptions {
  const intervalMs = getQueryPollingIntervalMs(tier);
  return {
    staleTime:
      options.staleTime ?? (typeof intervalMs === "number" ? intervalMs : 60_000),
    refetchInterval:
      intervalMs === false
        ? false
        : createPollingRefetchInterval(tier),
    refetchIntervalInBackground: false as const,
    refetchOnWindowFocus: false as const,
    refetchOnReconnect: false as const,
  };
}

export function isPollingDebugEnabled(): boolean {
  if (!import.meta.env.DEV || typeof window === "undefined") {
    return false;
  }
  try {
    return window.localStorage.getItem("debugQueryPolling") === "1";
  } catch {
    return false;
  }
}
