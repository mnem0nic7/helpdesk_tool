import { useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  api,
  type AzureVirtualMachineCostExportJobStatus,
  type AzureVirtualMachineCostExportLookbackDays,
  type AzureVirtualMachineCostExportScope,
  type AzureVirtualMachineDetailResponse,
  type AzureVirtualMachineRow,
} from "../lib/api.ts";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";

const DEFAULT_VM_DRAWER_WIDTH = 960;
const VM_DRAWER_MIN_WIDTH = 720;
const VM_DRAWER_VIEWPORT_MARGIN = 32;
const VM_COST_EXPORT_LOOKBACK_OPTIONS: AzureVirtualMachineCostExportLookbackDays[] = [7, 30, 90];

function clampVMDrawerWidth(width: number): number {
  if (typeof window === "undefined") return DEFAULT_VM_DRAWER_WIDTH;
  const maxWidth = Math.max(360, window.innerWidth - VM_DRAWER_VIEWPORT_MARGIN);
  const minWidth = Math.min(VM_DRAWER_MIN_WIDTH, maxWidth);
  return Math.min(Math.max(width, minWidth), maxWidth);
}

function getExpandedVMDrawerWidth(): number {
  if (typeof window === "undefined") return DEFAULT_VM_DRAWER_WIDTH;
  return clampVMDrawerWidth(window.innerWidth - VM_DRAWER_VIEWPORT_MARGIN);
}

function buildAzurePortalUrl(resourceId: string): string {
  return `https://portal.azure.com/#resource${resourceId}`;
}

function StatCard({ label, value, tone = "text-slate-900" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function coverageTone(status: "needed" | "excess" | "balanced" | "unavailable"): string {
  switch (status) {
    case "needed":
      return "text-amber-700";
    case "excess":
      return "text-sky-700";
    case "balanced":
      return "text-emerald-700";
    default:
      return "text-slate-400";
  }
}

function coverageLabel(delta: number | null): string {
  if (delta === null) return "Unavailable";
  if (delta > 0) return `${delta.toLocaleString()} needed`;
  if (delta < 0) return `${Math.abs(delta).toLocaleString()} excess`;
  return "Balanced";
}

function formatCurrency(value: number | null, currency = "USD"): string {
  if (value === null) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

function VMDetailStatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function VMDetailDrawer({
  detail,
  error,
  initialVm,
  isLoading,
  onClose,
}: {
  detail?: AzureVirtualMachineDetailResponse;
  error?: Error | null;
  initialVm: AzureVirtualMachineRow;
  isLoading: boolean;
  onClose: () => void;
}) {
  const vm = detail?.vm ?? initialVm;
  const associatedResources = detail?.associated_resources ?? [];
  const resourceScroll = useInfiniteScrollCount(associatedResources.length, 20, vm.id);
  const visibleResources = associatedResources.slice(0, resourceScroll.visibleCount);
  const [drawerWidth, setDrawerWidth] = useState(() => clampVMDrawerWidth(DEFAULT_VM_DRAWER_WIDTH));
  const [isResizing, setIsResizing] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleResize = () => {
      setDrawerWidth((current) => (isExpanded ? getExpandedVMDrawerWidth() : clampVMDrawerWidth(current)));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [isExpanded]);

  useEffect(() => {
    if (!isResizing) return undefined;

    const previousUserSelect = document.body.style.userSelect;
    const previousCursor = document.body.style.cursor;
    const updateWidth = (clientX: number) => {
      setDrawerWidth(clampVMDrawerWidth(window.innerWidth - clientX));
    };

    const handlePointerMove = (event: PointerEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const handleMouseMove = (event: MouseEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const stopResizing = () => {
      setIsResizing(false);
    };

    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("pointerup", stopResizing);
    window.addEventListener("mouseup", stopResizing);

    return () => {
      document.body.style.userSelect = previousUserSelect;
      document.body.style.cursor = previousCursor;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("pointerup", stopResizing);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [isResizing]);

  function handleResizeStart(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setIsExpanded(false);
    setIsResizing(true);
  }

  function toggleExpanded() {
    setIsExpanded((current) => {
      const next = !current;
      setDrawerWidth(next ? getExpandedVMDrawerWidth() : clampVMDrawerWidth(DEFAULT_VM_DRAWER_WIDTH));
      return next;
    });
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside
        data-testid="azure-vm-detail-drawer"
        className="relative flex h-full max-w-full flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        style={{ width: `${drawerWidth}px` }}
      >
        <div
          role="separator"
          aria-label="Resize VM detail drawer"
          aria-orientation="vertical"
          data-testid="azure-vm-detail-resizer"
          className={[
            "absolute inset-y-0 left-0 z-10 w-3 -translate-x-1/2 cursor-col-resize touch-none",
            isResizing ? "bg-blue-200/70" : "bg-transparent hover:bg-slate-200/60",
          ].join(" ")}
          onPointerDown={handleResizeStart}
          onDoubleClick={() => {
            setIsExpanded(false);
            setDrawerWidth(clampVMDrawerWidth(DEFAULT_VM_DRAWER_WIDTH));
          }}
        >
          <div className="absolute left-1/2 top-1/2 h-14 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-300" />
        </div>
        <div className="border-b border-slate-200 px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">VM Detail</p>
              <h2 className="mt-1 truncate text-2xl font-bold text-slate-900">{vm.name}</h2>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
                <span>{vm.size || "Unknown size"}</span>
                <span>{vm.power_state || "Unknown state"}</span>
                <span>{vm.subscription_name || vm.subscription_id}</span>
                <span>{vm.resource_group || "No resource group"}</span>
                <span>{vm.location || "Unknown region"}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <a
                href={buildAzurePortalUrl(vm.id)}
                target="_blank"
                rel="noreferrer"
                className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 transition hover:bg-sky-100"
              >
                Open in Azure
              </a>
              <button
                type="button"
                onClick={toggleExpanded}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
              >
                {isExpanded ? "Restore" : "Expand"}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {isLoading ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
              Loading VM resources and cost details...
            </div>
          ) : null}

          {error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              Failed to load VM detail: {error.message}
            </div>
          ) : null}

          {!isLoading && !error ? (
            <div className="space-y-6">
              <section className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-slate-900">Cost Rollup</h3>
                  <span className="text-xs font-medium text-slate-500">
                    Last {detail?.cost.lookback_days ?? 0} days · amortized cost
                  </span>
                </div>
                <div className="grid gap-3 md:grid-cols-3">
                  <VMDetailStatCard
                    label="VM + Attached Resources"
                    value={formatCurrency(detail?.cost.total_cost ?? null, detail?.cost.currency)}
                  />
                  <VMDetailStatCard
                    label="VM Only"
                    value={formatCurrency(detail?.cost.vm_cost ?? null, detail?.cost.currency)}
                  />
                  <VMDetailStatCard
                    label="Attached Resources Only"
                    value={formatCurrency(detail?.cost.related_resource_cost ?? null, detail?.cost.currency)}
                  />
                </div>
                {!detail?.cost.cost_data_available ? (
                  <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                    Resource-level Azure cost data is not available yet.
                    {detail?.cost.cost_error ? ` ${detail.cost.cost_error}` : ""}
                  </div>
                ) : null}
              </section>

              <section>
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-semibold text-slate-900">Associated Resources</h3>
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                    {associatedResources.length.toLocaleString()} resources
                  </span>
                </div>
                <div className="mt-3 max-h-[32rem] overflow-auto rounded-xl border border-slate-200">
                  <table className="min-w-full text-left text-sm">
                    <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <tr>
                        <th className="px-4 py-3">Resource</th>
                        <th className="px-4 py-3">Relationship</th>
                        <th className="px-4 py-3">Type</th>
                        <th className="px-4 py-3">Group</th>
                        <th className="px-4 py-3 text-right">Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleResources.map((resource, index) => (
                        <tr key={resource.id} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                          <td className="px-4 py-3">
                            <div className="font-medium text-slate-900">{resource.name}</div>
                            <div className="mt-1 max-w-md truncate text-xs text-slate-500">{resource.id}</div>
                          </td>
                          <td className="px-4 py-3 text-slate-700">{resource.relationship}</td>
                          <td className="px-4 py-3 text-slate-700">{resource.resource_type || "—"}</td>
                          <td className="px-4 py-3 text-slate-700">{resource.resource_group || "—"}</td>
                          <td className="whitespace-nowrap px-4 py-3 text-right font-semibold text-slate-900">
                            {formatCurrency(resource.cost, resource.currency)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {resourceScroll.hasMore ? (
                    <div ref={resourceScroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
                      Showing {visibleResources.length.toLocaleString()} of {associatedResources.length.toLocaleString()} resources — scroll for more
                    </div>
                  ) : null}
                </div>
              </section>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function VMCostExportDialog({
  matchedVmCount,
  onClose,
  onSubmit,
  recipientEmail,
  scope,
  lookbackDays,
  onScopeChange,
  onLookbackDaysChange,
  isSubmitting,
  submitError,
}: {
  matchedVmCount: number;
  onClose: () => void;
  onSubmit: () => void;
  recipientEmail: string;
  scope: AzureVirtualMachineCostExportScope;
  lookbackDays: AzureVirtualMachineCostExportLookbackDays;
  onScopeChange: (scope: AzureVirtualMachineCostExportScope) => void;
  onLookbackDaysChange: (days: AzureVirtualMachineCostExportLookbackDays) => void;
  isSubmitting: boolean;
  submitError?: string | null;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 px-4" onClick={onClose}>
      <div
        className="w-full max-w-xl rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-slate-900">Export VM Costs</h2>
            <p className="mt-1 text-sm text-slate-500">
              Build a live Azure workbook and email the download link to {recipientEmail}.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
          >
            Close
          </button>
        </div>

        <div className="mt-6 space-y-5">
          <section>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Scope</h3>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label className="rounded-2xl border border-slate-200 p-4 text-sm text-slate-700">
                <input
                  type="radio"
                  name="vm-export-scope"
                  checked={scope === "all"}
                  onChange={() => onScopeChange("all")}
                  className="mr-3"
                />
                <span className="font-semibold text-slate-900">All cached VMs</span>
                <div className="mt-1 text-xs text-slate-500">Export the full tenant-wide VM inventory from cache.</div>
              </label>
              <label className="rounded-2xl border border-slate-200 p-4 text-sm text-slate-700">
                <input
                  type="radio"
                  name="vm-export-scope"
                  checked={scope === "filtered"}
                  onChange={() => onScopeChange("filtered")}
                  className="mr-3"
                />
                <span className="font-semibold text-slate-900">Current filters</span>
                <div className="mt-1 text-xs text-slate-500">
                  Export the {matchedVmCount.toLocaleString()} VM{matchedVmCount === 1 ? "" : "s"} currently matching the page filters.
                </div>
              </label>
            </div>
          </section>

          <section>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Date Range</h3>
            <div className="mt-3 flex flex-wrap gap-2">
              {VM_COST_EXPORT_LOOKBACK_OPTIONS.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => onLookbackDaysChange(option)}
                  className={[
                    "rounded-full border px-4 py-2 text-sm font-medium transition",
                    lookbackDays === option
                      ? "border-sky-500 bg-sky-50 text-sky-700"
                      : "border-slate-300 bg-white text-slate-600 hover:border-slate-400 hover:bg-slate-50",
                  ].join(" ")}
                >
                  Last {option} days
                </button>
              ))}
            </div>
          </section>

          {submitError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              Failed to start the export: {submitError}
            </div>
          ) : null}
        </div>

        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={isSubmitting}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? "Starting export..." : "Start export"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AzureVMsPage() {
  const [search, setSearch] = useState("");
  const [subscriptionId, setSubscriptionId] = useState("");
  const [size, setSize] = useState("");
  const [location, setLocation] = useState("");
  const [state, setState] = useState("");
  const [isCoverageOpen, setIsCoverageOpen] = useState(true);
  const [selectedVm, setSelectedVm] = useState<AzureVirtualMachineRow | null>(null);
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);
  const [exportScope, setExportScope] = useState<AzureVirtualMachineCostExportScope>("all");
  const [exportLookbackDays, setExportLookbackDays] = useState<AzureVirtualMachineCostExportLookbackDays>(30);
  const [activeExportJobId, setActiveExportJobId] = useState<string | null>(null);

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.getMe(),
    staleTime: 5 * 60_000,
  });

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["azure", "vms", { search, subscriptionId, size, location, state }],
    queryFn: () =>
      api.getAzureVMs({
        search,
        subscription_id: subscriptionId,
        size,
        location,
        state,
      }),
    refetchInterval: 30_000,
  });
  const vmDetailQuery = useQuery({
    queryKey: ["azure", "vms", "detail", selectedVm?.id],
    queryFn: () => api.getAzureVMDetail(selectedVm!.id),
    enabled: !!selectedVm?.id,
    refetchInterval: selectedVm ? 60_000 : false,
  });
  const createExportJobMutation = useMutation({
    mutationFn: () =>
      api.createAzureVMCostExportJob({
        scope: exportScope,
        lookback_days: exportLookbackDays,
        filters: {
          search,
          subscription_id: subscriptionId,
          location,
          state,
          size,
        },
      }),
    onSuccess: (job) => {
      setActiveExportJobId(job.job_id);
      setIsExportDialogOpen(false);
    },
  });
  const exportJobQuery = useQuery({
    queryKey: ["azure", "vms", "cost-export-job", activeExportJobId],
    queryFn: () => api.getAzureVMCostExportJob(activeExportJobId!),
    enabled: !!activeExportJobId,
    refetchInterval: (query) => {
      const status = (query.state.data as AzureVirtualMachineCostExportJobStatus | undefined)?.status;
      return status === "completed" || status === "failed" ? false : 5_000;
    },
  });
  const vmRows = data?.vms ?? [];
  const coverageRows = data?.by_size ?? [];
  const filterKey = [search, subscriptionId, size, location, state].join("|");
  const coverageScroll = useInfiniteScrollCount(coverageRows.length, 20, filterKey);
  const visibleCoverage = coverageRows.slice(0, coverageScroll.visibleCount);
  const vmScroll = useInfiniteScrollCount(vmRows.length, 20, filterKey);
  const visibleVMs = vmRows.slice(0, vmScroll.visibleCount);
  const exportJob = activeExportJobId
    ? exportJobQuery.data ?? createExportJobMutation.data ?? null
    : null;

  if (isLoading) {
    return <div className="text-sm text-slate-500">Loading Azure virtual machines...</div>;
  }

  if (isError || !data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure VMs: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }

  const subscriptionOptions = Array.from(
    new Map(
      vmRows.map((item) => [
        item.subscription_id || item.subscription_name || item.name,
        {
          value: item.subscription_id || item.subscription_name || item.name,
          label: item.subscription_name || item.subscription_id || item.name,
        },
      ]),
    ).values(),
  ).sort((left, right) => left.label.localeCompare(right.label));
  const sizes = Array.from(new Set(vmRows.map((item) => item.size).filter(Boolean))).sort();
  const locations = Array.from(new Set(vmRows.map((item) => item.location).filter(Boolean))).sort();
  const states = Array.from(new Set(vmRows.map((item) => item.power_state).filter(Boolean))).sort();
  const exportProgressLabel = exportJob?.progress_total
    ? `${Math.min(exportJob.progress_current, exportJob.progress_total).toLocaleString()} / ${exportJob.progress_total.toLocaleString()}`
    : null;
  const exportRecipient = meQuery.data?.email || "your signed-in email";

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">VMs</h1>
          <p className="mt-1 text-sm text-slate-500">
            Review VM inventory here, then jump straight into Azure Portal for hands-on management.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            createExportJobMutation.reset();
            setIsExportDialogOpen(true);
          }}
          className="inline-flex items-center justify-center rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-slate-400 hover:bg-slate-50"
        >
          Export VM Costs
        </button>
      </div>

      {exportJob ? (
        <div
          className={[
            "rounded-2xl border px-4 py-3 text-sm",
            exportJob.status === "failed"
              ? "border-red-200 bg-red-50 text-red-800"
              : exportJob.status === "completed"
                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                : "border-sky-200 bg-sky-50 text-sky-800",
          ].join(" ")}
        >
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="font-semibold">
                VM cost export {exportJob.status === "queued" ? "queued" : exportJob.status === "running" ? "running" : exportJob.status === "completed" ? "ready" : "failed"}
              </div>
              <div className="mt-1 text-xs opacity-80">
                {exportJob.scope === "filtered" ? "Current filters" : "All cached VMs"} | last {exportJob.lookback_days} days
                {exportProgressLabel ? ` | ${exportProgressLabel}` : ""}
                {exportJob.progress_message ? ` | ${exportJob.progress_message}` : ""}
              </div>
              {exportJob.status === "completed" ? (
                <div className="mt-1 text-xs opacity-80">Completion email sent to {exportJob.recipient_email}.</div>
              ) : null}
              {exportJob.status === "failed" && exportJob.error ? (
                <div className="mt-1 text-xs opacity-80">{exportJob.error}</div>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              {exportJob.file_ready ? (
                <a
                  href={api.downloadAzureVMCostExportJob(exportJob.job_id)}
                  className="rounded-lg border border-emerald-300 bg-white px-3 py-1.5 text-sm font-semibold text-emerald-700 transition hover:bg-emerald-50"
                >
                  Download workbook
                </a>
              ) : null}
              {exportJob.status === "completed" || exportJob.status === "failed" ? (
                <button
                  type="button"
                  onClick={() => {
                    setActiveExportJobId(null);
                    createExportJobMutation.reset();
                  }}
                  className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
                >
                  Dismiss
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total VMs" value={data.summary.total_vms.toLocaleString()} />
        <StatCard label="Running" value={data.summary.running_vms.toLocaleString()} tone="text-emerald-700" />
        <StatCard label="Deallocated" value={data.summary.deallocated_vms.toLocaleString()} tone="text-amber-700" />
        <StatCard label="Distinct Sizes" value={data.summary.distinct_sizes.toLocaleString()} tone="text-sky-700" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.4fr,1fr]">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <button
              type="button"
              onClick={() => setIsCoverageOpen((value) => !value)}
              className="min-w-0 flex-1 text-left"
            >
              <h2 className="text-lg font-semibold text-slate-900">Size Footprint vs Reserved Instances</h2>
              <p className="mt-1 text-xs text-slate-500">Tenant-wide exact SKU and region comparison.</p>
            </button>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <a
                href={api.exportAzureVMCoverageExcel()}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
              >
                Export Excel
              </a>
              <a
                href={api.exportAzureVMExcessExcel()}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
              >
                Excess Excel
              </a>
              <div
                className={[
                  "rounded-full px-3 py-1 text-xs font-semibold",
                  data.reservation_data_available
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-amber-50 text-amber-700",
                ].join(" ")}
              >
                {data.reservation_data_available ? "RI data connected" : "RI data unavailable"}
              </div>
              <button
                type="button"
                onClick={() => setIsCoverageOpen((value) => !value)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-lg leading-none text-slate-500 transition hover:border-slate-400 hover:bg-slate-50"
                aria-label={isCoverageOpen ? "Collapse size footprint" : "Expand size footprint"}
              >
                {isCoverageOpen ? "−" : "+"}
              </button>
            </div>
          </div>
          {isCoverageOpen ? (
            <div className="mt-4">
              {!data.reservation_data_available ? (
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  Reserved-instance counts are unavailable with the current Azure permissions. VM counts are still shown.
                </div>
              ) : null}
              <div className="mt-4 max-h-[32rem] overflow-auto rounded-xl border border-slate-200">
                <table className="min-w-full table-auto text-sm">
                  <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-3 text-left">SKU / Region</th>
                      <th className="whitespace-nowrap px-4 py-3 text-right">VMs</th>
                      <th className="whitespace-nowrap px-4 py-3 text-right">Reserved Instances (RI)</th>
                      <th className="whitespace-nowrap px-4 py-3 text-right">Needed / Excess</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {data.by_size.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="px-4 py-8 text-center text-sm text-slate-500">
                          No VM size footprint data is available yet.
                        </td>
                      </tr>
                    ) : null}
                    {visibleCoverage.map((item) => (
                      <tr key={`${item.label}-${item.region}`} className="bg-white">
                        <td className="px-4 py-3">
                          <div className="font-medium text-slate-800">{item.label}</div>
                          <div className="text-xs uppercase tracking-wide text-slate-500">{item.region}</div>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-right font-semibold text-slate-900">
                          {item.vm_count.toLocaleString()}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-right font-semibold text-slate-900">
                          {item.reserved_instance_count === null ? "—" : item.reserved_instance_count.toLocaleString()}
                        </td>
                        <td className={`whitespace-nowrap px-4 py-3 text-right font-semibold ${coverageTone(item.coverage_status)}`}>
                          {coverageLabel(item.delta)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {coverageScroll.hasMore ? (
                  <div ref={coverageScroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
                    Showing {visibleCoverage.length.toLocaleString()} of {data.by_size.length.toLocaleString()} SKU rows — scroll for more
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Power States</h2>
          <div className="mt-4 space-y-3">
            {data.by_state.map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-800">{item.label}</span>
                <span className="text-sm font-semibold text-slate-900">{item.count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-2 xl:grid-cols-5">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search VM name, size, tag..."
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
        />
        <select value={subscriptionId} onChange={(event) => setSubscriptionId(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All subscriptions</option>
          {subscriptionOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        <select value={size} onChange={(event) => setSize(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All sizes</option>
          {sizes.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select value={location} onChange={(event) => setLocation(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All locations</option>
          {locations.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select value={state} onChange={(event) => setState(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All states</option>
          {states.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3 text-sm text-slate-500">
          Showing <span className="font-semibold text-slate-900">{visibleVMs.length.toLocaleString()}</span> of {data.matched_count.toLocaleString()} matched VMs
          <span className="text-slate-400"> | </span>
          {data.total_count.toLocaleString()} total VMs
        </div>
        <div className="max-h-[70vh] overflow-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">VM</th>
                <th className="px-4 py-3">Size</th>
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Subscription</th>
                <th className="px-4 py-3">Resource Group</th>
                <th className="px-4 py-3">Location</th>
                {data.cost_available ? (
                  <th className="px-4 py-3 text-right">
                    Cost
                    <span className="ml-1 font-normal text-slate-400">(VM only)</span>
                  </th>
                ) : null}
                <th className="px-4 py-3">Manage</th>
              </tr>
            </thead>
            <tbody>
              {data.vms.length === 0 ? (
                <tr>
                  <td colSpan={data.cost_available ? 8 : 7} className="px-4 py-8 text-center text-sm text-slate-500">
                    No virtual machines matched the current filters.
                  </td>
                </tr>
              ) : null}
              {visibleVMs.map((item, index) => (
                <tr
                  key={item.id}
                  onClick={() => setSelectedVm(item)}
                  className={[
                    "cursor-pointer transition hover:bg-sky-50/60",
                    selectedVm?.id === item.id ? "bg-sky-50" : index % 2 === 0 ? "bg-white" : "bg-slate-50/50",
                  ].join(" ")}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{item.name}</div>
                    <div className="mt-1 max-w-xl truncate text-xs text-slate-500">{item.id}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{item.size}</td>
                  <td className="px-4 py-3 text-slate-700">{item.power_state}</td>
                  <td className="px-4 py-3 text-slate-700">{item.subscription_name || item.subscription_id}</td>
                  <td className="px-4 py-3 text-slate-700">{item.resource_group || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{item.location || "—"}</td>
                  {data.cost_available ? (
                    <td className="px-4 py-3 text-right font-semibold text-slate-900">
                      {formatCurrency(item.cost, item.currency)}
                    </td>
                  ) : null}
                  <td className="px-4 py-3">
                    <a
                      href={buildAzurePortalUrl(item.id)}
                      target="_blank"
                      rel="noreferrer"
                      onClick={(event) => event.stopPropagation()}
                      className="inline-flex rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 transition hover:bg-sky-100"
                    >
                      Manage in Azure
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {vmScroll.hasMore ? (
            <div ref={vmScroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
              Showing {visibleVMs.length.toLocaleString()} of {data.vms.length.toLocaleString()} VMs — scroll for more
            </div>
          ) : null}
        </div>
      </section>

      {selectedVm ? (
        <VMDetailDrawer
          initialVm={selectedVm}
          detail={vmDetailQuery.data}
          isLoading={vmDetailQuery.isLoading}
          error={vmDetailQuery.error instanceof Error ? vmDetailQuery.error : null}
          onClose={() => setSelectedVm(null)}
        />
      ) : null}

      {isExportDialogOpen ? (
        <VMCostExportDialog
          matchedVmCount={data.matched_count}
          onClose={() => {
            setIsExportDialogOpen(false);
            createExportJobMutation.reset();
          }}
          onSubmit={() => createExportJobMutation.mutate()}
          recipientEmail={exportRecipient}
          scope={exportScope}
          lookbackDays={exportLookbackDays}
          onScopeChange={setExportScope}
          onLookbackDaysChange={setExportLookbackDays}
          isSubmitting={createExportJobMutation.isPending}
          submitError={createExportJobMutation.error instanceof Error ? createExportJobMutation.error.message : null}
        />
      ) : null}
    </div>
  );
}
