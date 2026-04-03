import { useEffect, useState } from "react";
import { useQueryClient, type Query } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import {
  isPollingDebugEnabled,
  resolvePollingIntervalMs,
} from "../lib/queryPolling.ts";

function formatQueryKey(queryKey: readonly unknown[]): string {
  try {
    return JSON.stringify(queryKey);
  } catch {
    return String(queryKey);
  }
}

function isActivelyPolling(query: Query<unknown, Error, unknown, readonly unknown[]>) {
  const option = (query.options as { refetchInterval?: unknown }).refetchInterval;
  if (!option || option === false) return false;
  if (typeof option === "number") {
    return resolvePollingIntervalMs(option) !== false;
  }
  if (typeof option === "function") {
    try {
      return option(query) !== false;
    } catch {
      return true;
    }
  }
  return false;
}

export default function QueryPollingDebugOverlay() {
  const enabled = isPollingDebugEnabled();
  const queryClient = useQueryClient();
  const location = useLocation();
  const [activeQueries, setActiveQueries] = useState<Query<unknown, Error, unknown, readonly unknown[]>[]>([]);

  useEffect(() => {
    if (!enabled) {
      setActiveQueries([]);
      return undefined;
    }
    const update = () => {
      setActiveQueries(queryClient.getQueryCache().getAll().filter((query) => isActivelyPolling(query)));
    };
    update();
    return queryClient.getQueryCache().subscribe(update);
  }, [enabled, location.pathname, queryClient]);

  if (!enabled) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[80] max-w-md rounded-2xl border border-amber-200 bg-amber-50/95 px-4 py-3 text-xs text-amber-950 shadow-lg backdrop-blur">
      <div className="font-semibold">Polling Debug</div>
      <div className="mt-1">
        {location.pathname} • {activeQueries.length} active polling quer
        {activeQueries.length === 1 ? "y" : "ies"}
      </div>
      <div className="mt-2 max-h-40 space-y-1 overflow-y-auto pr-1 text-[11px]">
        {activeQueries.length === 0 ? (
          <div>No active polling queries.</div>
        ) : (
          activeQueries.slice(0, 8).map((query) => (
            <div key={formatQueryKey(query.queryKey)} className="truncate">
              {formatQueryKey(query.queryKey)}
            </div>
          ))
        )}
      </div>
      <div className="mt-2 text-[10px] text-amber-800">
        Set <code>localStorage.debugQueryPolling = "1"</code> to keep this
        overlay visible in development.
      </div>
    </div>
  );
}
