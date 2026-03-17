import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type AzureVirtualMachineDetailResponse, type AzureVirtualMachineRow } from "../lib/api.ts";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";

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

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-3xl flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
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
                    Last {detail?.cost.lookback_days ?? 0} days
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

export default function AzureVMsPage() {
  const [search, setSearch] = useState("");
  const [subscriptionId, setSubscriptionId] = useState("");
  const [size, setSize] = useState("");
  const [location, setLocation] = useState("");
  const [state, setState] = useState("");
  const [isCoverageOpen, setIsCoverageOpen] = useState(true);
  const [selectedVm, setSelectedVm] = useState<AzureVirtualMachineRow | null>(null);

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
  const vmRows = data?.vms ?? [];
  const coverageRows = data?.by_size ?? [];
  const filterKey = [search, subscriptionId, size, location, state].join("|");
  const coverageScroll = useInfiniteScrollCount(coverageRows.length, 20, filterKey);
  const visibleCoverage = coverageRows.slice(0, coverageScroll.visibleCount);
  const vmScroll = useInfiniteScrollCount(vmRows.length, 20, filterKey);
  const visibleVMs = vmRows.slice(0, vmScroll.visibleCount);

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

  const subscriptions = Array.from(new Set(vmRows.map((item) => item.subscription_name || item.subscription_id))).sort();
  const sizes = Array.from(new Set(vmRows.map((item) => item.size).filter(Boolean))).sort();
  const locations = Array.from(new Set(vmRows.map((item) => item.location).filter(Boolean))).sort();
  const states = Array.from(new Set(vmRows.map((item) => item.power_state).filter(Boolean))).sort();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">VMs</h1>
        <p className="mt-1 text-sm text-slate-500">
          Review VM inventory here, then jump straight into Azure Portal for hands-on management.
        </p>
      </div>

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
          {subscriptions.map((value) => <option key={value} value={value}>{value}</option>)}
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
                <th className="px-4 py-3">Manage</th>
              </tr>
            </thead>
            <tbody>
              {data.vms.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-slate-500">
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
    </div>
  );
}
