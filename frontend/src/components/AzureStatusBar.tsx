import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AzureCostExportStatus } from "../lib/api.ts";

function formatLastRefresh(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleTimeString();
}

function getCostExportTone(status: AzureCostExportStatus | null | undefined): string {
  if (!status) return "bg-slate-50 text-slate-700";
  if (!status.enabled) return "bg-slate-50 text-slate-700";
  if (status.refreshing || status.running) return "bg-amber-50 text-amber-700";
  const exportState = status.health?.state?.toLowerCase();
  if (exportState === "error" || status.last_error) return "bg-red-50 text-red-700";
  if (exportState === "stale") return "bg-amber-50 text-amber-700";
  if (exportState === "waiting") return "bg-slate-50 text-slate-700";
  return "bg-emerald-50 text-emerald-700";
}

function getCostExportLabel(status: AzureCostExportStatus | null | undefined): string {
  if (!status) return "";
  if (!status.enabled) return "Disabled";
  if (status.refreshing || status.running) return "Syncing";

  const exportState = status.health?.state?.toLowerCase();
  if (exportState === "stale") return "Stale";
  if (exportState === "waiting") return "Waiting";
  if (exportState === "error") return "Error";
  if (exportState === "healthy") return "Healthy";
  if (status.last_error) return "Needs attention";
  return "Healthy";
}

export default function AzureStatusBar({ isAdmin }: { isAdmin: boolean }) {
  const queryClient = useQueryClient();
  const wasRefreshing = useRef(false);

  const { data: status } = useQuery({
    queryKey: ["azure", "status"],
    queryFn: () => api.getAzureStatus(),
    refetchInterval: (query) => (query.state.data?.refreshing ? 1_500 : 30_000),
  });

  useEffect(() => {
    if (status?.refreshing) {
      wasRefreshing.current = true;
      return;
    }
    if (wasRefreshing.current && status && !status.refreshing) {
      wasRefreshing.current = false;
      queryClient.invalidateQueries({ queryKey: ["azure"] });
    }
  }, [queryClient, status]);

  const refreshMutation = useMutation({
    mutationFn: () => api.refreshAzure(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["azure", "status"] });
    },
  });

  if (!status) return null;

  const costExports = status.cost_exports;
  const costExportState = getCostExportLabel(costExports);
  const costExportReason = costExports?.health?.reason || costExports?.last_error || "";

  return (
    <div className="mb-4 rounded-md border border-sky-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm text-slate-600">
        <span
          className={`inline-block h-2 w-2 rounded-full ${
            status.configured ? "bg-sky-500" : "bg-amber-500"
          }`}
        />
        <span className="font-medium text-slate-900">
          {status.configured ? "Azure cache connected" : "Azure cache not configured"}
        </span>
        <span className="text-slate-300">|</span>
        <span>Last refresh: {formatLastRefresh(status.last_refresh)}</span>
        {status.refreshing && (
          <>
            <span className="text-slate-300">|</span>
            <span className="text-sky-700 font-medium">Refreshing Azure datasets...</span>
          </>
        )}
        <div className="flex-1" />
        <div className="flex flex-wrap items-center gap-2">
          {status.datasets.map((dataset) => (
            <span
              key={dataset.key}
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                dataset.error
                  ? "bg-red-50 text-red-700"
                  : "bg-sky-50 text-sky-700"
              }`}
              title={dataset.error || `${dataset.item_count.toLocaleString()} cached items`}
            >
              {dataset.label}: {dataset.item_count.toLocaleString()}
            </span>
          ))}
          {costExports && (
            <>
              <span className="text-slate-300">|</span>
              <span
                className={`rounded-full px-3 py-1 text-xs font-medium ${getCostExportTone(costExports)}`}
                title={
                  costExportReason ||
                  (costExports.last_success_at
                    ? `Last successful export sync at ${formatLastRefresh(costExports.last_success_at)}`
                    : "No successful export sync yet")
                }
              >
                Cost exports: {costExportState}
              </span>
              <span className="rounded-full bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
                Deliveries: {costExports.health.delivery_count.toLocaleString()}
              </span>
              <span className="rounded-full bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
                Parsed: {costExports.health.parsed_count.toLocaleString()}
              </span>
              <span className="rounded-full bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
                Quarantined: {costExports.health.quarantined_count.toLocaleString()}
              </span>
            </>
          )}
          {isAdmin && (
            <button
              type="button"
              onClick={() => refreshMutation.mutate()}
              disabled={status.refreshing || refreshMutation.isPending}
              className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {refreshMutation.isPending ? "Starting..." : "Refresh Azure"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
