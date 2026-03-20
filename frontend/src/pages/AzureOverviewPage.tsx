import { useQuery } from "@tanstack/react-query";
import { api, type AzureCostExportStatus } from "../lib/api.ts";

function MetricCard({ label, value, accent = "text-sky-700" }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${accent}`}>{value}</div>
    </div>
  );
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
    return <div className="text-sm text-slate-500">Loading Azure overview...</div>;
  }

  if (isError || !data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure overview: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }

  const exportHealth = getExportHealthView(data.cost_exports);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Azure Overview</h1>
        <p className="mt-1 text-sm text-slate-500">
          Tenant-wide inventory, identity, and cost posture from the Azure cache.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <MetricCard label="Subscriptions" value={data.subscriptions.toLocaleString()} />
        <MetricCard label="Resources" value={data.resources.toLocaleString()} />
        <MetricCard label="Users" value={data.users.toLocaleString()} />
        <MetricCard label="Enterprise Apps" value={data.enterprise_apps.toLocaleString()} />
        <MetricCard
          label={`Spend (${data.cost.lookback_days}d)`}
          value={`$${data.cost.total_cost.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
          accent="text-emerald-700"
        />
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
          <h2 className="text-lg font-semibold text-slate-900">Cost Export Health</h2>
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
