import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";

export default function CacheStatusBar() {
  const queryClient = useQueryClient();

  const { data: status } = useQuery({
    queryKey: ["cache-status"],
    queryFn: () => api.getCacheStatus(),
    refetchInterval: 30_000, // poll every 30s
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["cache-status"] });
    queryClient.invalidateQueries({ queryKey: ["metrics"] });
    queryClient.invalidateQueries({ queryKey: ["sla-summary"] });
    queryClient.invalidateQueries({ queryKey: ["sla-breaches"] });
    queryClient.invalidateQueries({ queryKey: ["manage-tickets"] });
  };

  const incremental = useMutation({
    mutationFn: () => api.refreshCacheIncremental(),
    onSuccess: invalidateAll,
  });

  const full = useMutation({
    mutationFn: () => api.refreshCache(),
    onSuccess: invalidateAll,
  });

  if (!status) return null;

  const isWorking = !status.initialized || status.refreshing || incremental.isPending || full.isPending;

  const lastRefresh = status.last_refresh
    ? new Date(status.last_refresh).toLocaleTimeString()
    : "—";

  return (
    <div className="mb-4 flex items-center gap-3 rounded-md border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 shadow-sm">
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
    </div>
  );
}
