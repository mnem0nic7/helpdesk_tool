import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type AzureAdvisorRecommendation,
  type AzureComputeOptimizationResponse,
  type AzureVirtualMachineSizeCoverageRow,
  type AzureVirtualMachineRow,
} from "../lib/api.ts";
import AzureSourceBadge from "../components/AzureSourceBadge.tsx";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import AzureSavingsHighlightsSection from "../components/AzureSavingsHighlightsSection.tsx";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type IdleVMSortKey = "name" | "size" | "power_state" | "location" | "subscription" | "resource_group" | "cost";
type TopCostSortKey = "name" | "size" | "location" | "subscription" | "cost";

function formatCurrency(value: number | null, currency = "USD"): string {
  if (value === null) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

function formatCoverageWindow(start?: string | null, end?: string | null): string {
  if (!start || !end) return "";
  if (start === end) return start;
  return `${start} to ${end}`;
}

function StatCard({
  label,
  value,
  tone = "text-slate-900",
  hidden = false,
}: {
  label: string;
  value: string;
  tone?: string;
  hidden?: boolean;
}) {
  if (hidden) return null;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function powerStateBadge(state: string) {
  const s = state.toLowerCase();
  if (s === "stopped") {
    return (
      <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
        Stopped
      </span>
    );
  }
  if (s === "deallocated") {
    return (
      <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
        Deallocated
      </span>
    );
  }
  return (
    <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">
      {state}
    </span>
  );
}

function impactBadge(impact: string) {
  const s = impact.toLowerCase();
  if (s === "high") {
    return (
      <span className="inline-block rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">
        High
      </span>
    );
  }
  if (s === "medium") {
    return (
      <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
        Medium
      </span>
    );
  }
  return (
    <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
      {s.charAt(0).toUpperCase() + s.slice(1) || impact}
    </span>
  );
}

function coverageStatusBadge(status: AzureVirtualMachineSizeCoverageRow["coverage_status"]) {
  switch (status) {
    case "needed":
      return (
        <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">
          Gap
        </span>
      );
    case "excess":
      return (
        <span className="inline-block rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-700">
          Excess
        </span>
      );
    case "balanced":
      return (
        <span className="inline-block rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">
          Balanced
        </span>
      );
    default:
      return (
        <span className="inline-block rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-400">
          N/A
        </span>
      );
  }
}

// ─── Idle VMs Section ────────────────────────────────────────────────────────

function IdleVMsSection({
  vms,
  costAvailable,
  search,
  onSearchChange,
}: {
  vms: AzureVirtualMachineRow[];
  costAvailable: boolean;
  search: string;
  onSearchChange: (value: string) => void;
}) {
  const { sortKey, sortDir, toggleSort } = useTableSort<IdleVMSortKey>("name");
  const sorted = sortRows(vms, sortKey, sortDir, (v, key) => {
    if (key === "subscription") return v.subscription_name || v.subscription_id;
    if (key === "cost") return v.cost;
    return (v as unknown as Record<string, unknown>)[key] as string;
  });
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(sorted.length, 100, `${search}|${sortKey}|${sortDir}`);
  const visible = sorted.slice(0, visibleCount);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-slate-900">Idle Virtual Machines</h2>
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700">
              {vms.length.toLocaleString()}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            VMs in Deallocated or Stopped state — compute charges stopped but associated disk/NIC costs may still apply.
          </p>
        </div>
      </div>
      <input
        className="mt-3 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm placeholder-slate-400 focus:border-blue-500 focus:outline-none"
        placeholder="Search by name, subscription, resource group…"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
      />
      {visible.length === 0 ? (
        <p className="mt-6 text-center text-sm text-slate-400">No idle VMs found — all VMs are running.</p>
      ) : (
        <div className="mt-4 max-h-[60vh] overflow-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <SortHeader col="name" label="VM Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="size" label="Size" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3">State</th>
                <SortHeader col="location" label="Location" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="subscription" label="Subscription" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="resource_group" label="Resource Group" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                {costAvailable && <SortHeader col="cost" label="Cost" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />}
              </tr>
            </thead>
            <tbody>
              {visible.map((vm) => (
                <tr key={vm.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2 font-medium text-slate-900">{vm.name || vm.id}</td>
                  <td className="px-4 py-2 text-slate-600">{vm.size || "—"}</td>
                  <td className="px-4 py-2">{powerStateBadge(vm.power_state)}</td>
                  <td className="px-4 py-2 text-slate-600">{vm.location || "—"}</td>
                  <td className="px-4 py-2 text-slate-600">{vm.subscription_name || vm.subscription_id || "—"}</td>
                  <td className="px-4 py-2 text-slate-600">{vm.resource_group || "—"}</td>
                  {costAvailable && (
                    <td className="px-4 py-2 text-right text-slate-700">{formatCurrency(vm.cost, vm.currency)}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {hasMore && <div ref={sentinelRef} className="h-1" />}
        </div>
      )}
    </section>
  );
}

// ─── Top Cost VMs Section ─────────────────────────────────────────────────────

function TopCostVMsSection({ vms }: { vms: AzureVirtualMachineRow[] }) {
  const { sortKey, sortDir, toggleSort } = useTableSort<TopCostSortKey>("cost", "desc");
  const sorted = sortRows(vms, sortKey, sortDir, (v, key) => {
    if (key === "subscription") return v.subscription_name || v.subscription_id;
    if (key === "cost") return v.cost;
    return (v as unknown as Record<string, unknown>)[key] as string;
  });
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">Top 20 VMs by Cost</h2>
        <p className="mt-1 text-sm text-slate-500">Running VMs ranked by cached monthly cost.</p>
      </div>
      <div className="mt-4 overflow-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <SortHeader col="name" label="VM Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="size" label="Size" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="location" label="Location" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="subscription" label="Subscription" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="cost" label="Monthly Cost" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
            </tr>
          </thead>
          <tbody>
            {sorted.map((vm) => (
              <tr key={vm.id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-2 font-medium text-slate-900">{vm.name || vm.id}</td>
                <td className="px-4 py-2 text-slate-600">{vm.size || "—"}</td>
                <td className="px-4 py-2 text-slate-600">{vm.location || "—"}</td>
                <td className="px-4 py-2 text-slate-600">{vm.subscription_name || vm.subscription_id || "—"}</td>
                <td className="px-4 py-2 text-right font-semibold text-slate-900">
                  {formatCurrency(vm.cost, vm.currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ─── RI Coverage Gaps Section ─────────────────────────────────────────────────

function RICoverageGapsSection({ gaps }: { gaps: AzureVirtualMachineSizeCoverageRow[] }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-slate-900">Reserved Instance Coverage Gaps</h2>
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-700">
              {gaps.length.toLocaleString()}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            SKU/region combos where running VM count exceeds reserved instance count. Each gap represents a potential RI
            savings opportunity.
          </p>
        </div>
      </div>
      {gaps.length === 0 ? (
        <p className="mt-6 text-center text-sm text-slate-400">
          No RI gaps — all running VM SKUs are covered by reservations.
        </p>
      ) : (
        <div className="mt-4 overflow-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">SKU</th>
                <th className="px-4 py-3">Region</th>
                <th className="px-4 py-3 text-right">Running VMs</th>
                <th className="px-4 py-3 text-right">RIs Owned</th>
                <th className="px-4 py-3 text-right">Gap</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {gaps.map((row, idx) => (
                <tr key={idx} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2 font-medium text-slate-900">{row.label}</td>
                  <td className="px-4 py-2 text-slate-600">{row.region || "—"}</td>
                  <td className="px-4 py-2 text-right text-slate-700">{row.vm_count.toLocaleString()}</td>
                  <td className="px-4 py-2 text-right text-slate-700">
                    {row.reserved_instance_count !== null ? row.reserved_instance_count.toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2 text-right font-semibold text-amber-700">
                    {row.delta !== null ? `+${row.delta.toLocaleString()}` : "—"}
                  </td>
                  <td className="px-4 py-2">{coverageStatusBadge(row.coverage_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ─── Advisor Recommendations Section ─────────────────────────────────────────

function AdvisorSection({ recs }: { recs: AzureAdvisorRecommendation[] }) {
  const sorted = [...recs].sort((a, b) => (b.monthly_savings ?? 0) - (a.monthly_savings ?? 0));
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(sorted.length, 100, "");
  const visible = sorted.slice(0, visibleCount);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-semibold text-slate-900">Azure Advisor Cost Recommendations</h2>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {recs.length.toLocaleString()}
        </span>
      </div>
      {visible.length === 0 ? (
        <p className="mt-6 text-center text-sm text-slate-400">No Advisor cost recommendations available.</p>
      ) : (
        <div className="mt-4 max-h-[60vh] overflow-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Recommendation</th>
                <th className="px-4 py-3">Impact</th>
                <th className="px-4 py-3 text-right">Monthly Savings</th>
                <th className="px-4 py-3">Subscription</th>
                <th className="px-4 py-3">Resource</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((rec) => (
                <tr key={rec.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2">
                    <div className="font-medium text-slate-900">{rec.title}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {[rec.resource_id ? rec.resource_id.split("/").pop() || rec.resource_id : "", rec.subscription_name || rec.subscription_id || ""]
                        .filter(Boolean)
                        .join(" / ") || "Scoped recommendation"}
                    </div>
                    {rec.description && (
                      <div className="mt-0.5 text-xs text-slate-400 line-clamp-2">{rec.description}</div>
                    )}
                  </td>
                  <td className="px-4 py-2">{impactBadge(rec.impact)}</td>
                  <td className="px-4 py-2 text-right font-semibold text-emerald-700">
                    {formatCurrency(rec.monthly_savings, rec.currency)}
                  </td>
                  <td className="px-4 py-2 text-slate-600">
                    {rec.subscription_name || rec.subscription_id || "—"}
                  </td>
                  <td className="max-w-[200px] truncate px-4 py-2 text-xs text-slate-400" title={rec.resource_id}>
                    {rec.resource_id ? rec.resource_id.split("/").pop() || rec.resource_id : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {hasMore && <div ref={sentinelRef} className="h-1" />}
        </div>
      )}
    </section>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AzureComputeOptimizationPage() {
  const [idleVmSearch, setIdleVmSearch] = useState("");
  const deferredIdleVmSearch = useDeferredValue(idleVmSearch.trim());
  const { data, isLoading, isError } = useQuery<AzureComputeOptimizationResponse>({
    queryKey: ["azure-compute-optimization", deferredIdleVmSearch],
    queryFn: () => api.getAzureComputeOptimization({ idle_vm_search: deferredIdleVmSearch }),
    placeholderData: (prev) => prev,
  });
  const savingsQuery = useQuery({
    queryKey: ["azure", "savings", "compute-page"],
    queryFn: () => api.getAzureSavingsOpportunities({ category: "compute" }),
    refetchInterval: 60_000,
  });
  const commitmentQuery = useQuery({
    queryKey: ["azure", "savings", "compute-page", "commitment"],
    queryFn: () => api.getAzureSavingsOpportunities({ category: "commitment" }),
    refetchInterval: 60_000,
  });

  if (isLoading) {
    return <AzurePageSkeleton titleWidth="w-72" subtitleWidth="w-[34rem]" statCount={5} sectionCount={4} />;
  }

  if (isError || !data) {
    return (
      <div className="flex h-64 items-center justify-center text-red-500 text-sm">
        Failed to load compute optimization data.
      </div>
    );
  }

  const { summary, idle_vms, top_cost_vms, ri_coverage_gaps, advisor_recommendations, cost_available, reservation_data_available, cost_context } = data;
  const computeSavings = savingsQuery.data ?? [];
  const commitmentSavings = commitmentQuery.data ?? [];
  const coverageWindow = formatCoverageWindow(cost_context?.window_start, cost_context?.window_end);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Compute Optimization</h1>
        <p className="mt-1 text-sm text-slate-500">
          Idle VM detection, RI coverage gaps, top cost runners, and Advisor cost recommendations — all in one view.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <AzureSourceBadge
            label="Cache-backed compute drill-in"
            description="VM state, RI coverage, and per-resource drill-in on this page still come from cached Azure inventory and Advisor snapshots."
            tone="amber"
          />
          {cost_context && (
            <AzureSourceBadge
              label={cost_context.source_label}
              description={
                cost_context.export_backed
                  ? "Shared cost prioritization now has export-backed context, even though VM-level drill-in on this page remains cache-backed."
                  : cost_context.source_description
              }
            />
          )}
        </div>
        {coverageWindow ? (
          <div className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
            Shared cost coverage window: {coverageWindow}
          </div>
        ) : null}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
        <StatCard label="Total VMs" value={summary.total_vms.toLocaleString()} />
        <StatCard
          label="Running"
          value={summary.running_vms.toLocaleString()}
          tone={summary.running_vms > 0 ? "text-emerald-600" : "text-slate-900"}
        />
        <StatCard
          label="Idle (Deallocated / Stopped)"
          value={summary.idle_vms.toLocaleString()}
          tone={summary.idle_vms > 0 ? "text-amber-600" : "text-slate-900"}
        />
        <StatCard
          label="Running Cost"
          value={formatCurrency(summary.total_running_cost)}
          hidden={!cost_available}
        />
        <StatCard
          label="Advisor Savings Available"
          value={formatCurrency(summary.total_advisor_savings)}
          tone={summary.total_advisor_savings > 0 ? "text-emerald-600" : "text-slate-900"}
        />
      </div>

      <AzureSavingsHighlightsSection
        title="Compute Savings Actions"
        description="Synthesized idle cleanup and Advisor-backed compute actions, ranked by savings and implementation friction."
        opportunities={computeSavings}
        emptyMessage="No compute-focused savings actions are currently flagged."
        maxItems={6}
      />

      <AzureSavingsHighlightsSection
        title="Reservation Strategy"
        description="Reservation gaps and excesses are tracked here as planning items and are intentionally kept out of quantified totals."
        opportunities={commitmentSavings}
        emptyMessage="No reservation coverage gaps or excesses are currently flagged."
        maxItems={6}
      />

      {/* Idle VMs */}
      <IdleVMsSection
        vms={idle_vms}
        costAvailable={cost_available}
        search={idleVmSearch}
        onSearchChange={setIdleVmSearch}
      />

      {/* Top Cost VMs */}
      {cost_available && top_cost_vms.length > 0 && <TopCostVMsSection vms={top_cost_vms} />}

      {/* RI Coverage Gaps */}
      {reservation_data_available && (
        <RICoverageGapsSection gaps={ri_coverage_gaps} />
      )}

      {/* Advisor Recommendations */}
      <AdvisorSection recs={advisor_recommendations} />
    </div>
  );
}
