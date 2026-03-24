import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import AzureSourceBadge from "../components/AzureSourceBadge.tsx";
import AzureExportSetupCard from "../components/AzureExportSetupCard.tsx";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import {
  api,
  type AzureAllocationDimension,
  type AzureAllocationDimensionPolicy,
  type AzureAllocationResult,
  type AzureAllocationRule,
  type AzureAllocationRun,
  type AzureAllocationRunDimensionSummary,
} from "../lib/api.ts";

const SURFACED_DIMENSIONS: AzureAllocationDimension[] = ["team", "application"];

function formatCurrency(value: number): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value || 0);
}

function formatPercent(value: number): string {
  return `${((value || 0) * 100).toFixed(1)}%`;
}

function formatDateTime(value: string): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function bucketBadgeClass(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === "fallback") return "bg-amber-100 text-amber-700";
  if (normalized === "shared") return "bg-violet-100 text-violet-700";
  return "bg-emerald-100 text-emerald-700";
}

function formatDimensionLabel(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

function describeRuleCondition(rule: AzureAllocationRule): string {
  const condition = rule.condition ?? {};
  const tagKey = typeof condition.tag_key === "string" ? condition.tag_key : "";
  const field = typeof condition.field === "string" ? condition.field : tagKey ? `tags.${tagKey}` : "";
  const exact = typeof condition.tag_value === "string"
    ? condition.tag_value
    : typeof condition.equals === "string"
      ? condition.equals
      : "";
  const pattern = typeof condition.pattern === "string" ? condition.pattern : "";
  const values = Array.isArray(condition.values)
    ? condition.values.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  if (exact) return `${field || "value"} = ${exact}`;
  if (values.length) return `${field || "value"} in ${values.join(", ")}`;
  if (pattern) return `${field || "value"} matches ${pattern}`;
  return field || "Always";
}

function describeRuleAllocation(rule: AzureAllocationRule): string {
  const allocation = rule.allocation ?? {};
  if (rule.rule_type === "shared") {
    const splits = Array.isArray(allocation.splits)
      ? allocation.splits
          .map((item) => {
            if (!item || typeof item !== "object") return "";
            const split = item as Record<string, unknown>;
            const value = typeof split.value === "string" ? split.value : "";
            const percentage = Number(split.percentage ?? 0);
            if (!value) return "";
            return `${value} ${percentage > 0 ? `${percentage}%` : ""}`.trim();
          })
          .filter(Boolean)
      : [];
    return splits.join(", ") || "Shared split";
  }
  const value = typeof allocation.value === "string" ? allocation.value : "";
  if (rule.rule_type === "percentage") {
    const percentage = Number(allocation.percentage ?? 0);
    if (percentage > 0) return `${percentage > 1 ? percentage : percentage * 100}% to ${value || "bucket"}`;
  }
  return value || "Named bucket";
}

function matchesAllocationSearch(row: AzureAllocationResult, search: string): boolean {
  if (!search) return true;
  const haystack = [
    row.allocation_value,
    row.bucket_type,
    row.allocation_method,
    row.source_record_count,
    row.allocated_actual_cost,
    row.allocated_amortized_cost,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(search);
}

function matchesRuleSearch(rule: AzureAllocationRule, search: string): boolean {
  if (!search) return true;
  const haystack = [
    rule.name,
    rule.description,
    rule.rule_type,
    rule.target_dimension,
    describeRuleCondition(rule),
    describeRuleAllocation(rule),
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(search);
}

function getDimensionPolicy(policies: AzureAllocationDimensionPolicy[], dimension: AzureAllocationDimension): AzureAllocationDimensionPolicy | null {
  return policies.find((item) => item.dimension === dimension) ?? null;
}

function getDimensionSummary(run: AzureAllocationRun | undefined, dimension: AzureAllocationDimension): AzureAllocationRunDimensionSummary | null {
  return run?.dimensions.find((item) => item.target_dimension === dimension) ?? null;
}

function sumActualCost(rows: AzureAllocationResult[]): number {
  return rows.reduce((total, row) => total + (row.allocated_actual_cost || 0), 0);
}

function StatCard({
  label,
  value,
  sub,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</div>
      {sub ? <div className="mt-1 text-xs text-slate-400">{sub}</div> : null}
    </div>
  );
}

function AllocationDimensionSection({
  title,
  policy,
  summary,
  rows,
  residuals,
  loading,
  search,
}: {
  title: string;
  policy: AzureAllocationDimensionPolicy | null;
  summary: AzureAllocationRunDimensionSummary | null;
  rows: AzureAllocationResult[];
  residuals: AzureAllocationResult[];
  loading: boolean;
  search: string;
}) {
  const filteredRows = useMemo(
    () => rows.filter((row) => matchesAllocationSearch(row, search)),
    [rows, search],
  );
  const filteredResiduals = useMemo(
    () => residuals.filter((row) => matchesAllocationSearch(row, search)),
    [residuals, search],
  );

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <p className="mt-1 text-sm text-slate-500">
            {policy?.description || "Allocation breakdown for the selected dimension."}
          </p>
        </div>
        {policy ? (
          <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
            Fallback bucket: <span className="font-semibold text-slate-900">{policy.fallback_bucket}</span>
          </div>
        ) : null}
      </div>

      {loading ? (
        <div className="mt-4 text-sm text-slate-500">Loading allocation details...</div>
      ) : summary ? (
        <>
          <div className="mt-4 grid gap-4 md:grid-cols-4">
            <StatCard
              label="Direct Cost"
              value={formatCurrency(summary.direct_allocated_actual_cost)}
              sub={`${summary.source_record_count.toLocaleString()} source records`}
              tone="text-emerald-700"
            />
            <StatCard
              label="Fallback Cost"
              value={formatCurrency(summary.residual_actual_cost)}
              sub={policy?.fallback_bucket || "Fallback bucket"}
              tone="text-amber-700"
            />
            <StatCard
              label="Total Source Cost"
              value={formatCurrency(summary.source_actual_cost)}
              sub="Actual cost before allocation"
            />
            <StatCard
              label="Coverage"
              value={formatPercent(summary.coverage_pct)}
              sub={`${formatCurrency(summary.total_allocated_actual_cost)} allocated`}
              tone="text-sky-700"
            />
          </div>

          <div className="mt-6 grid gap-4 xl:grid-cols-[1.5fr,1fr]">
            <div>
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-slate-900">Allocated Buckets</div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
                  {filteredRows.length.toLocaleString()} buckets
                </span>
              </div>
              <div className="max-h-[30rem] overflow-auto rounded-2xl border border-slate-200">
                <table className="min-w-full text-left text-sm">
                  <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Bucket</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">Method</th>
                      <th className="px-4 py-3 text-right">Source Records</th>
                      <th className="px-4 py-3 text-right">Actual Cost</th>
                      <th className="px-4 py-3 text-right">Amortized</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.length ? filteredRows.map((row, index) => (
                      <tr key={`${title}-${row.allocation_value}-${row.bucket_type}-${index}`} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/60"}>
                        <td className="px-4 py-3 font-medium text-slate-900">{row.allocation_value || "Unnamed bucket"}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${bucketBadgeClass(row.bucket_type)}`}>
                            {formatDimensionLabel(row.bucket_type)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-600">{formatDimensionLabel(row.allocation_method || "direct")}</td>
                        <td className="px-4 py-3 text-right text-slate-600">{row.source_record_count.toLocaleString()}</td>
                        <td className="px-4 py-3 text-right font-semibold text-slate-900">{formatCurrency(row.allocated_actual_cost)}</td>
                        <td className="px-4 py-3 text-right text-slate-600">{formatCurrency(row.allocated_amortized_cost)}</td>
                      </tr>
                    )) : (
                      <tr>
                        <td colSpan={6} className="px-4 py-6 text-center text-sm text-slate-500">
                          No allocation buckets match the current filter.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="space-y-4">
              <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
                <div className="text-sm font-semibold text-amber-900">Unallocated / fallback total</div>
                <div className="mt-2 text-3xl font-semibold text-amber-700">
                  {formatCurrency(sumActualCost(residuals))}
                </div>
                <div className="mt-2 text-xs text-amber-800">
                  These costs fell through to the named fallback bucket instead of a direct or shared rule.
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-900">Fallback buckets</div>
                  <span className="rounded-full bg-white px-3 py-1 text-xs font-medium text-slate-600">
                    {filteredResiduals.length.toLocaleString()} rows
                  </span>
                </div>
                <div className="mt-3 space-y-3">
                  {filteredResiduals.length ? filteredResiduals.map((row, index) => (
                    <div key={`${title}-residual-${row.allocation_value}-${index}`} className="rounded-xl bg-white px-4 py-3 shadow-sm">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-medium text-slate-900">{row.allocation_value}</div>
                          <div className="mt-1 text-xs text-slate-500">
                            {row.source_record_count.toLocaleString()} source records • {formatDimensionLabel(row.allocation_method)}
                          </div>
                        </div>
                        <div className="text-right text-sm font-semibold text-amber-700">
                          {formatCurrency(row.allocated_actual_cost)}
                        </div>
                      </div>
                    </div>
                  )) : (
                    <div className="rounded-xl border border-dashed border-slate-200 bg-white px-4 py-6 text-sm text-slate-500">
                      No fallback buckets match the current filter.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
          No allocation summary is available for this dimension yet.
        </div>
      )}
    </section>
  );
}

export default function AzureAllocationPage() {
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState("");
  const [search, setSearch] = useState("");
  const [runLabel, setRunLabel] = useState("");
  const [runNote, setRunNote] = useState("");
  const deferredSearch = useDeferredValue(search.trim().toLowerCase());

  const me = useQuery({
    queryKey: ["auth", "me", "allocation-page"],
    queryFn: () => api.getMe(),
    retry: false,
    staleTime: 5 * 60_000,
  });
  const status = useQuery({
    queryKey: ["azure", "allocations", "status"],
    queryFn: () => api.getAzureAllocationStatus(),
    refetchInterval: 60_000,
  });
  const rules = useQuery({
    queryKey: ["azure", "allocations", "rules"],
    queryFn: () => api.getAzureAllocationRules(),
    refetchInterval: 60_000,
  });
  const runs = useQuery({
    queryKey: ["azure", "allocations", "runs"],
    queryFn: () => api.getAzureAllocationRuns(20),
    refetchInterval: 60_000,
  });

  useEffect(() => {
    if (selectedRunId) return;
    const candidate = status.data?.latest_run?.run_id || runs.data?.[0]?.run_id || "";
    if (candidate) {
      setSelectedRunId(candidate);
    }
  }, [selectedRunId, status.data?.latest_run?.run_id, runs.data]);

  const runDetail = useQuery({
    queryKey: ["azure", "allocations", "run", selectedRunId],
    queryFn: () => api.getAzureAllocationRun(selectedRunId),
    enabled: !!selectedRunId,
    refetchInterval: 60_000,
  });
  const teamResults = useQuery({
    queryKey: ["azure", "allocations", "results", selectedRunId, "team"],
    queryFn: () => api.getAzureAllocationResults(selectedRunId, "team"),
    enabled: !!selectedRunId,
    refetchInterval: 60_000,
  });
  const teamResiduals = useQuery({
    queryKey: ["azure", "allocations", "residuals", selectedRunId, "team"],
    queryFn: () => api.getAzureAllocationResiduals(selectedRunId, "team"),
    enabled: !!selectedRunId,
    refetchInterval: 60_000,
  });
  const applicationResults = useQuery({
    queryKey: ["azure", "allocations", "results", selectedRunId, "application"],
    queryFn: () => api.getAzureAllocationResults(selectedRunId, "application"),
    enabled: !!selectedRunId,
    refetchInterval: 60_000,
  });
  const applicationResiduals = useQuery({
    queryKey: ["azure", "allocations", "residuals", selectedRunId, "application"],
    queryFn: () => api.getAzureAllocationResiduals(selectedRunId, "application"),
    enabled: !!selectedRunId,
    refetchInterval: 60_000,
  });

  const runAllocation = useMutation({
    mutationFn: () =>
      api.runAzureAllocation({
        target_dimensions: SURFACED_DIMENSIONS,
        run_label: runLabel.trim(),
        note: runNote.trim(),
      }),
    onSuccess: async (payload) => {
      setSelectedRunId(payload.run_id);
      setRunLabel("");
      setRunNote("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["azure", "allocations", "status"] }),
        queryClient.invalidateQueries({ queryKey: ["azure", "allocations", "runs"] }),
        queryClient.invalidateQueries({ queryKey: ["azure", "allocations", "run"] }),
        queryClient.invalidateQueries({ queryKey: ["azure", "allocations", "results"] }),
        queryClient.invalidateQueries({ queryKey: ["azure", "allocations", "residuals"] }),
      ]);
    },
  });

  const baseLoading = status.isLoading || rules.isLoading || runs.isLoading;
  const baseFailure = [status, rules, runs].find((query) => query.isError);
  const currentRun =
    runDetail.data ??
    ((selectedRunId ? selectedRunId === status.data?.latest_run?.run_id : true) ? status.data?.latest_run ?? null : null);
  const policy = status.data?.policy ?? null;
  const isAdmin = !!me.data?.is_admin;

  const surfacedRules = useMemo(
    () =>
      (rules.data ?? [])
        .filter((rule) => SURFACED_DIMENSIONS.includes(rule.target_dimension))
        .filter((rule) => matchesRuleSearch(rule, deferredSearch)),
    [rules.data, deferredSearch],
  );

  if (baseLoading) {
    return <AzurePageSkeleton titleWidth="w-48" subtitleWidth="w-[34rem]" statCount={5} sectionCount={3} />;
  }

  if (baseFailure || !status.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load allocation data: {baseFailure?.error instanceof Error ? baseFailure.error.message : "Unknown error"}
      </div>
    );
  }

  const teamPolicy = getDimensionPolicy(policy?.target_dimensions ?? [], "team");
  const applicationPolicy = getDimensionPolicy(policy?.target_dimensions ?? [], "application");
  const teamSummary = getDimensionSummary(currentRun ?? undefined, "team");
  const applicationSummary = getDimensionSummary(currentRun ?? undefined, "application");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Allocation</h1>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Local FinOps showback views for team and application cost ownership. Allocation runs are non-destructive,
            keep fallback visible, and sit on top of the export-backed DuckDB cost model.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <AzureSourceBadge
              label="Local DuckDB allocation runs"
              description="These views come from the local FinOps analytics store and versioned allocation runs, not live portal scraping."
            />
            <AzureSourceBadge
              label="Fallback stays visible"
              description="Unmatched cost remains in explicit fallback buckets so operators can see where rules are still missing."
              tone="amber"
            />
            <AzureSourceBadge
              label="Non-destructive"
              description="Allocation results are materialized per run and do not mutate the raw cost record source data."
              tone="emerald"
            />
          </div>
        </div>
      </div>

      {!status.data.available ? (
        <AzureExportSetupCard
          title="Allocation unlocks after cost exports are enabled"
          body="Step 1: enable and validate the export-backed cost lane. Step 2: allocation runs become available automatically here for team and application showback."
        />
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard
          label="Active Rules"
          value={status.data.active_rule_count.toLocaleString()}
          sub={`${status.data.rule_version_count.toLocaleString()} total versions`}
          tone="text-sky-700"
        />
        <StatCard
          label="Allocation Runs"
          value={status.data.run_count.toLocaleString()}
          sub={`Policy v${status.data.policy.version}`}
        />
        <StatCard
          label="Latest Run"
          value={status.data.last_run_at ? formatDateTime(status.data.last_run_at) : "Never"}
          sub={status.data.latest_run?.trigger_type ? `Trigger: ${status.data.latest_run.trigger_type}` : "No completed run yet"}
        />
        <StatCard
          label="Latest Source Records"
          value={(status.data.latest_run?.source_record_count ?? 0).toLocaleString()}
          sub="Records included in the latest run"
        />
        <StatCard
          label="Inactive Rules"
          value={status.data.inactive_rule_count.toLocaleString()}
          sub="Versioned rule history kept for auditability"
          tone="text-slate-700"
        />
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Run Controls</h2>
            <p className="mt-1 text-sm text-slate-500">
              Trigger a fresh allocation snapshot for the team and application views, then review fallback buckets to tighten rules.
            </p>
          </div>
          <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-600">
            Supported rule types: {(policy?.supported_rule_types ?? []).map(formatDimensionLabel).join(", ")}
          </div>
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-[1.1fr,1.1fr,auto]">
          <label className="block">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Run Label</div>
            <input
              value={runLabel}
              onChange={(event) => setRunLabel(event.target.value)}
              placeholder="Optional label for this snapshot"
              disabled={!status.data.available}
              className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
            />
          </label>
          <label className="block">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Operator Note</div>
            <input
              value={runNote}
              onChange={(event) => setRunNote(event.target.value)}
              placeholder="Optional note about why this run was triggered"
              disabled={!status.data.available}
              className="mt-2 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
            />
          </label>
          <div className="flex items-end">
            <button
              type="button"
              onClick={() => runAllocation.mutate()}
              disabled={!isAdmin || !status.data.available || runAllocation.isPending}
              className="rounded-xl bg-sky-700 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-sky-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {runAllocation.isPending ? "Running..." : "Run Team + Application"}
            </button>
          </div>
        </div>
        {!status.data.available ? (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            These run controls stay disabled until export-backed cost records are landing in the local FinOps store.
          </div>
        ) : null}
        {!isAdmin ? (
          <div className="mt-3 text-xs text-slate-500">Admin access is required to trigger new allocation runs.</div>
        ) : null}
        {runAllocation.isError ? (
          <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {runAllocation.error instanceof Error ? runAllocation.error.message : "Failed to trigger allocation run."}
          </div>
        ) : null}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Current Snapshot</h2>
            <p className="mt-1 text-sm text-slate-500">
              Review the selected allocation run, then compare direct ownership against fallback-assigned cost.
            </p>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <label className="block">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Run</div>
              <select
                value={selectedRunId}
                onChange={(event) => setSelectedRunId(event.target.value)}
                className="mt-2 rounded-xl border border-slate-300 px-3 py-2 text-sm"
              >
                {(runs.data ?? []).map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {run.run_label || formatDateTime(run.created_at)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Filter Buckets</div>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search bucket, rule type, or method"
                className="mt-2 w-72 rounded-xl border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
          </div>
        </div>

        {currentRun ? (
          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Triggered By"
              value={currentRun.triggered_by || "System"}
              sub={currentRun.run_label || currentRun.trigger_type}
            />
            <StatCard
              label="Created"
              value={formatDateTime(currentRun.created_at)}
              sub={currentRun.completed_at ? `Completed ${formatDateTime(currentRun.completed_at)}` : "Run is still open"}
            />
            <StatCard
              label="Target Dimensions"
              value={currentRun.target_dimensions.map(formatDimensionLabel).join(", ") || "Default"}
              sub={`Status: ${formatDimensionLabel(currentRun.status)}`}
            />
            <StatCard
              label="Source Records"
              value={currentRun.source_record_count.toLocaleString()}
              sub={currentRun.note || "No operator note recorded"}
            />
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
            No allocation run exists yet. Trigger a run to populate the team and application showback views.
          </div>
        )}
      </section>

      <div className="grid gap-6">
        <AllocationDimensionSection
          title="Cost by Team"
          policy={teamPolicy}
          summary={teamSummary}
          rows={teamResults.data ?? []}
          residuals={teamResiduals.data ?? []}
          loading={runDetail.isLoading || teamResults.isLoading || teamResiduals.isLoading}
          search={deferredSearch}
        />
        <AllocationDimensionSection
          title="Cost by Application"
          policy={applicationPolicy}
          summary={applicationSummary}
          rows={applicationResults.data ?? []}
          residuals={applicationResiduals.data ?? []}
          loading={runDetail.isLoading || applicationResults.isLoading || applicationResiduals.isLoading}
          search={deferredSearch}
        />
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Active Rules</h2>
            <p className="mt-1 text-sm text-slate-500">
              The latest active rule versions for the surfaced allocation dimensions.
            </p>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
            {surfacedRules.length.toLocaleString()} rules
          </span>
        </div>
        <div className="mt-4 max-h-[30rem] overflow-auto rounded-2xl border border-slate-200">
          <table className="min-w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Dimension</th>
                <th className="px-4 py-3">Rule</th>
                <th className="px-4 py-3">Match</th>
                <th className="px-4 py-3">Allocation</th>
                <th className="px-4 py-3 text-right">Priority</th>
              </tr>
            </thead>
            <tbody>
              {surfacedRules.length ? surfacedRules.map((rule, index) => (
                <tr key={`${rule.rule_id}-${rule.rule_version}`} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/60"}>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-700">
                      {formatDimensionLabel(rule.target_dimension)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{rule.name}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {formatDimensionLabel(rule.rule_type)} rule • v{rule.rule_version}
                    </div>
                    {rule.description ? <div className="mt-1 text-xs text-slate-500">{rule.description}</div> : null}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{describeRuleCondition(rule)}</td>
                  <td className="px-4 py-3 text-slate-600">{describeRuleAllocation(rule)}</td>
                  <td className="px-4 py-3 text-right font-semibold text-slate-900">{rule.priority}</td>
                </tr>
              )) : (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-sm text-slate-500">
                    No active team or application rules match the current filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
