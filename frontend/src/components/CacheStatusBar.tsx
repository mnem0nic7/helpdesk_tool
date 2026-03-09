import { useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";

function progressLabel(progress: { phase: string; current: number; total: number }): string {
  const { phase, current, total } = progress;
  if (phase === "starting") return "Starting…";
  if (phase === "saving") return "Saving to cache…";
  if (phase === "fetching" && total > 0)
    return `Fetching issues… ${current.toLocaleString()} / ${total.toLocaleString()}`;
  if (phase === "fetching") return `Fetching issues… ${current.toLocaleString()}`;
  if (phase === "backfilling" && total > 0)
    return `Backfilling comments… ${current} / ${total}`;
  return phase;
}

function progressPercent(progress: { phase: string; current: number; total: number }): number | null {
  const { total, current } = progress;
  if (total <= 0) return null;
  return Math.min(100, Math.round((current / total) * 100));
}

export default function CacheStatusBar() {
  const queryClient = useQueryClient();
  const wasRefreshing = useRef(false);

  const { data: status } = useQuery({
    queryKey: ["cache-status"],
    queryFn: () => api.getCacheStatus(),
    refetchInterval: (query) => {
      const d = query.state.data;
      // Poll fast during refresh for progress updates
      return d?.refreshing ? 1_500 : 30_000;
    },
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["cache-status"] });
    queryClient.invalidateQueries({ queryKey: ["metrics"] });
    queryClient.invalidateQueries({ queryKey: ["sla-summary"] });
    queryClient.invalidateQueries({ queryKey: ["sla-breaches"] });
    queryClient.invalidateQueries({ queryKey: ["manage-tickets"] });
    queryClient.invalidateQueries({ queryKey: ["tickets"] });
    queryClient.invalidateQueries({ queryKey: ["ticket-detail"] });
    queryClient.invalidateQueries({ queryKey: ["filter-options"] });
  };

  // Invalidate queries when refresh completes
  useEffect(() => {
    if (status?.refreshing) {
      wasRefreshing.current = true;
    } else if (wasRefreshing.current && status && !status.refreshing) {
      wasRefreshing.current = false;
      invalidateAll();
    }
  }, [status?.refreshing]);

  const incremental = useMutation({
    mutationFn: () => api.refreshCacheIncremental(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cache-status"] });
    },
  });

  const full = useMutation({
    mutationFn: () => api.refreshCache(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cache-status"] });
    },
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelRefresh(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cache-status"] });
    },
  });

  if (!status) return null;

  const isWorking = !status.initialized || status.refreshing || incremental.isPending || full.isPending;
  const progress = status.refresh_progress;
  const pct = progress ? progressPercent(progress) : null;

  const lastRefresh = status.last_refresh
    ? new Date(status.last_refresh).toLocaleTimeString()
    : "—";

  return (
    <div className="mb-4 rounded-md border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center gap-3 px-4 py-2 text-sm text-slate-600">
        {/* Status dot */}
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            status.initialized ? "bg-green-500" : "bg-amber-500 animate-pulse"
          }`}
        />

        {/* Issue count */}
        {status.initialized ? (
          <span>
            <span className="font-medium text-slate-900">
              {status.issue_count.toLocaleString()}
            </span>{" "}
            issues cached
          </span>
        ) : (
          <span className="text-amber-600">Loading issues from Jira…</span>
        )}

        {/* Separator */}
        <span className="text-slate-300">|</span>

        {/* Last refresh */}
        <span>Last refresh: {lastRefresh}</span>

        {/* Progress label */}
        {isWorking && progress && (
          <>
            <span className="text-slate-300">|</span>
            <span className="text-blue-600 font-medium text-xs">
              {progressLabel(progress)}
              {pct !== null && ` (${pct}%)`}
            </span>
          </>
        )}

        {/* Refreshing spinner */}
        {isWorking && (
          <svg
            className="h-4 w-4 animate-spin text-blue-500"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Refresh buttons */}
        {status.refreshing ? (
          <button
            type="button"
            onClick={() => cancel.mutate()}
            disabled={cancel.isPending}
            className="rounded border border-red-300 bg-red-50 px-3 py-1 text-xs font-medium text-red-600 transition-colors hover:bg-red-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Stop
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={() => incremental.mutate()}
              disabled={isWorking}
              className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={() => full.mutate()}
              disabled={isWorking}
              className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed"
              title="Re-fetch all issues from Jira (slow)"
            >
              Full Refresh
            </button>
          </>
        )}
      </div>

      {/* Progress bar */}
      {isWorking && pct !== null && (
        <div className="h-1 w-full bg-slate-100">
          <div
            className="h-full bg-blue-500 transition-all duration-500 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  );
}
