import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import AzureSourceBadge from "../components/AzureSourceBadge.tsx";
import AzureExportSetupCard from "../components/AzureExportSetupCard.tsx";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { api, type AzureCostExportStatus, type AzureReportingTarget } from "../lib/api.ts";

function MetricCard({ label, value, accent = "text-sky-700" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${accent}`}>{value}</div>
    </div>
  );
}

function ReportingCard({ target, exportsEnabled }: { target: AzureReportingTarget; exportsEnabled: boolean }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Governed Reporting</div>
      <h3 className="mt-2 text-lg font-semibold text-slate-900">{target.label}</h3>
      <p className="mt-2 text-sm text-slate-600">{target.description}</p>
      {target.configured && target.url ? (
        <a
          href={target.url}
          target="_blank"
          rel="noreferrer"
          className="mt-4 inline-flex rounded-xl bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800"
        >
          Open {target.label}
        </a>
      ) : exportsEnabled ? (
        <div className="mt-4 rounded-xl border border-dashed border-slate-300 px-4 py-3 text-sm text-slate-500">
          Reporting target is not configured yet.
        </div>
      ) : (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <div className="font-semibold">Set up cost exports first</div>
          <div className="mt-1 text-amber-800">
            This reporting handoff stays locked until export-backed cost deliveries are enabled and parsing cleanly.
          </div>
          <Link to="/cost" className="mt-3 inline-flex rounded-lg bg-amber-700 px-3 py-2 text-sm font-medium text-white hover:bg-amber-800">
            View setup steps
          </Link>
        </div>
      )}
    </div>
  );
}

function formatCoverageWindow(start?: string | null, end?: string | null): string {
  if (!start || !end) return "";
  if (start === end) return start;
  return `${start} to ${end}`;
}

function getExportHealthView(costExports: AzureCostExportStatus | undefined) {
  if (!costExports) {
    return {
      label: "",
      accent: "text-slate-700",
      reason: "",
    };
  }
  if (!costExports.enabled) {
    return { label: "Disabled", accent: "text-slate-700", reason: "Export ingestion is disabled." };
  }
  if (costExports.refreshing || costExports.running) {
    return {
      label: "Syncing",
      accent: "text-amber-700",
      reason: costExports.health.reason || "Export ingestion is currently syncing.",
    };
  }

  const state = costExports.health.state?.toLowerCase();
  const reason = costExports.health.reason || costExports.last_error || "";
  if (state === "stale") {
    return { label: "Stale", accent: "text-amber-700", reason };
  }
  if (state === "waiting") {
    return { label: "Waiting", accent: "text-slate-700", reason };
  }
  if (state === "error") {
    return { label: "Error", accent: "text-red-700", reason };
  }
  if (state === "healthy") {
    return { label: "Healthy", accent: "text-emerald-700", reason };
  }
  if (costExports.last_error) {
    return { label: "Needs attention", accent: "text-red-700", reason };
  }
  return { label: "Healthy", accent: "text-emerald-700", reason };
}

export default function AzureOverviewPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["azure", "overview"],
    queryFn: () => api.getAzureOverview(),
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return <AzurePageSkeleton titleWidth="w-64" subtitleWidth="w-[34rem]" statCount={6} sectionCount={3} />;
  }

  if (isError || !data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure overview: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }

  const exportHealth = getExportHealthView(data.cost_exports);
  const coverageWindow = formatCoverageWindow(data.cost.window_start, data.cost.window_end);
  const showAmortized = Boolean(data.cost.export_backed);
  const costExportsEnabled = Boolean(data.cost_exports?.enabled);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Azure Overview</h1>
        <p className="mt-1 text-sm text-slate-500">
          Tenant-wide inventory and identity posture from cached Azure snapshots, with export-backed cost context when local FinOps analytics are available.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <AzureSourceBadge
            label={data.reporting?.sources.overview.label || data.cost.source_label || "Cached inventory + cost context"}
            description={
              data.reporting?.sources.overview.description ||
              (data.cost.export_backed
                ? "Overview inventory is cached, but cost posture now prefers local export-backed analytics."
                : "Overview metrics come from cached Azure snapshots and operational cost queries.")
            }
          />
          <AzureSourceBadge
            label={data.cost.source_label || "Operational app cost context"}
            description={
              data.cost.export_backed
                ? "Spend totals on this page are coming from the local DuckDB FinOps lane built from parsed Azure Cost Management exports."
                : "Spend totals on this page are still using cached app data because export-backed analytics are unavailable."
            }
            tone={data.cost.export_backed ? "sky" : "amber"}
          />
          <AzureSourceBadge
            label={costExportsEnabled ? (data.reporting?.sources.exports.label || "Governed reporting ready") : "Governed reporting setup required"}
            description={
              costExportsEnabled
                ? (data.reporting?.sources.exports.description ||
                    "Shared reporting should come from Cost Management exports and governed BI assets.")
                : "Shared finance, validation signoff, and allocation stay blocked until cost exports are enabled."
            }
            tone={costExportsEnabled ? "emerald" : "amber"}
          />
        </div>
        {coverageWindow ? (
          <div className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
            Cost coverage window: {coverageWindow}
          </div>
        ) : null}
      </div>

      {data.reporting && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Reporting Handoff</h2>
              <p className="mt-1 max-w-3xl text-sm text-slate-500">
                Use this app for operational triage and governed reporting tools for shared finance, showback, and deep cost analysis.
              </p>
            </div>
            <AzureSourceBadge
              label={data.reporting.sources.exports.label}
              description={data.reporting.sources.exports.description}
              tone="emerald"
            />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <ReportingCard target={data.reporting.power_bi} exportsEnabled={costExportsEnabled} />
            <ReportingCard target={data.reporting.cost_analysis} exportsEnabled={costExportsEnabled} />
          </div>
        </section>
      )}

      {!costExportsEnabled ? (
        <AzureExportSetupCard title="Enable Cost Exports to Unlock Governed Reporting" />
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Subscriptions" value={data.subscriptions.toLocaleString()} />
        <MetricCard label="Resources" value={data.resources.toLocaleString()} />
        <MetricCard label="Users" value={data.users.toLocaleString()} />
        <MetricCard label="Enterprise Apps" value={data.enterprise_apps.toLocaleString()} />
        <MetricCard
          label={showAmortized ? `Actual Spend (${data.cost.lookback_days}d)` : `Spend (${data.cost.lookback_days}d)`}
          value={`$${(data.cost.total_actual_cost ?? data.cost.total_cost).toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
          accent="text-emerald-700"
        />
        {showAmortized && (
          <MetricCard
            label={`Amortized Spend (${data.cost.lookback_days}d)`}
            value={`$${(data.cost.total_amortized_cost ?? data.cost.total_cost).toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
            accent="text-indigo-700"
          />
        )}
        <MetricCard
          label="Potential Monthly Savings"
          value={`$${data.cost.potential_monthly_savings.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
          accent="text-amber-700"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.5fr,1fr]">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Environment Signals</h2>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="rounded-xl bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Service</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{data.cost.top_service || "—"}</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Subscription</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{data.cost.top_subscription || "—"}</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Top Resource Group</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{data.cost.top_resource_group || "—"}</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Advisor Cost Recommendations</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{data.cost.recommendation_count.toLocaleString()}</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Management Groups</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{data.management_groups.toLocaleString()}</div>
            </div>
            <div className="rounded-xl bg-slate-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Role Assignments</div>
              <div className="mt-1 text-lg font-semibold text-slate-900">{data.role_assignments.toLocaleString()}</div>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Dataset Health</h2>
          <div className="mt-4 space-y-3">
            {data.datasets.map((dataset) => (
              <div key={dataset.key} className="rounded-xl border border-slate-200 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-sm font-semibold text-slate-900">{dataset.label}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      Refresh every {dataset.interval_minutes} minutes
                    </div>
                  </div>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                      dataset.error ? "bg-red-50 text-red-700" : "bg-sky-50 text-sky-700"
                    }`}
                  >
                    {dataset.item_count.toLocaleString()} items
                  </span>
                </div>
                <div className="mt-2 text-xs text-slate-500">
                  Last refresh: {dataset.last_refresh ? new Date(dataset.last_refresh).toLocaleString() : "—"}
                </div>
                {dataset.error && (
                  <div className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
                    {dataset.error}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>

      {data.cost_exports && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Cost Export Health</h2>
              <p className="mt-1 text-sm text-slate-500">
                Freshness for the export-backed governed reporting lane, separate from the app cache refresh.
              </p>
            </div>
            <AzureSourceBadge
              label={data.reporting?.sources.exports.label || "Export-backed governed reporting"}
              description={
                data.reporting?.sources.exports.description ||
                "Shared reporting should come from Cost Management exports and governed BI assets."
              }
              tone="emerald"
            />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <MetricCard
              label="Export Service"
              value={exportHealth.label}
              accent={exportHealth.accent}
            />
            <MetricCard
              label="Deliveries"
              value={data.cost_exports.health.delivery_count.toLocaleString()}
              accent="text-sky-700"
            />
            <MetricCard
              label="Parsed"
              value={data.cost_exports.health.parsed_count.toLocaleString()}
              accent="text-emerald-700"
            />
            <MetricCard
              label="Quarantined"
              value={data.cost_exports.health.quarantined_count.toLocaleString()}
              accent="text-amber-700"
            />
            <MetricCard
              label="Staged Snapshots"
              value={data.cost_exports.health.staged_snapshot_count.toLocaleString()}
            />
            <MetricCard
              label="Quarantine Artifacts"
              value={data.cost_exports.health.quarantine_artifact_count.toLocaleString()}
            />
          </div>
          {exportHealth.reason && exportHealth.label && exportHealth.label !== "Healthy" && (
            <div className="mt-4 rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
              {exportHealth.reason}
            </div>
          )}
          {data.cost_exports.last_error && (
            <div className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
              Last export sync error: {data.cost_exports.last_error}
            </div>
          )}
          <div className="mt-4 text-sm text-slate-500">
            Last successful export sync:{" "}
            {data.cost_exports.last_success_at ? new Date(data.cost_exports.last_success_at).toLocaleString() : "—"}
          </div>
        </section>
      )}
    </div>
  );
}
