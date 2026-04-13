import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { DefenderAgentConfig, DefenderAgentDecision } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function severityColor(sev: string): string {
  switch (sev.toLowerCase()) {
    case "critical": return "bg-rose-100 text-rose-800";
    case "high":     return "bg-amber-100 text-amber-800";
    case "medium":   return "bg-yellow-100 text-yellow-800";
    case "low":      return "bg-slate-100 text-slate-700";
    default:         return "bg-gray-100 text-gray-600";
  }
}

function tierLabel(d: DefenderAgentDecision): { label: string; color: string } {
  if (d.decision === "skip")      return { label: "Skipped",       color: "bg-gray-100 text-gray-500" };
  if (d.decision === "recommend") return { label: "T3 Recommend",  color: "bg-blue-100 text-blue-800" };
  if (d.decision === "queue")     return { label: "T2 Queued",     color: "bg-amber-100 text-amber-800" };
  if (d.decision === "execute")   return { label: "T1 Immediate",  color: "bg-green-100 text-green-800" };
  return { label: d.decision,    color: "bg-gray-100 text-gray-600" };
}

function decisionStatus(d: DefenderAgentDecision): { label: string; color: string } {
  if (d.cancelled)         return { label: "Cancelled",          color: "text-gray-400" };
  if (d.human_approved)    return { label: "Approved",           color: "text-emerald-600 font-medium" };
  if (d.decision === "skip") return { label: "—",                color: "text-gray-400" };
  if (d.decision === "recommend" && !d.human_approved)
    return { label: "Awaiting approval",                         color: "text-blue-600 font-medium" };
  if (d.decision === "queue") {
    if (d.job_ids.length) return { label: "Dispatched",          color: "text-emerald-600" };
    return { label: "Pending (cancellable)",                     color: "text-amber-600 font-medium" };
  }
  if (d.job_ids.length)    return { label: "Executed",           color: "text-emerald-600" };
  return { label: "Logged",                                      color: "text-gray-500" };
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function fmtAction(d: DefenderAgentDecision): string {
  if (!d.action_type) return "—";
  return d.action_type.replace(/_/g, " ");
}

// ---------------------------------------------------------------------------
// Config drawer
// ---------------------------------------------------------------------------

function ConfigDrawer({
  config,
  onSave,
  saving,
}: {
  config: DefenderAgentConfig;
  onSave: (c: Partial<DefenderAgentConfig>) => void;
  saving: boolean;
}) {
  const [local, setLocal] = useState<Partial<DefenderAgentConfig>>({
    enabled: config.enabled,
    min_severity: config.min_severity,
    tier2_delay_minutes: config.tier2_delay_minutes,
    dry_run: config.dry_run,
  });

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 mt-3 space-y-3 text-sm">
      <div className="flex items-center gap-4 flex-wrap">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={!!local.enabled}
            onChange={(e) => setLocal((p) => ({ ...p, enabled: e.target.checked }))}
            className="h-4 w-4 rounded border-gray-300 text-blue-600"
          />
          <span className="font-medium text-gray-700">Enabled</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={!!local.dry_run}
            onChange={(e) => setLocal((p) => ({ ...p, dry_run: e.target.checked }))}
            className="h-4 w-4 rounded border-gray-300 text-amber-600"
          />
          <span className="font-medium text-amber-700">Dry Run (log only, no actions)</span>
        </label>
      </div>
      <div className="flex items-end gap-4 flex-wrap">
        <label className="block">
          <span className="text-xs text-gray-500">Min Severity</span>
          <select
            value={local.min_severity}
            onChange={(e) => setLocal((p) => ({ ...p, min_severity: e.target.value as DefenderAgentConfig["min_severity"] }))}
            className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          >
            <option value="informational">Informational</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-gray-500">T2 Delay (minutes)</span>
          <input
            type="number"
            min={0}
            max={1440}
            value={local.tier2_delay_minutes ?? 15}
            onChange={(e) => setLocal((p) => ({ ...p, tier2_delay_minutes: Math.max(0, Math.min(1440, parseInt(e.target.value) || 0)) }))}
            className="mt-1 block w-24 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          />
        </label>
        <button
          onClick={() => onSave(local)}
          disabled={saving}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
      <p className="text-xs text-gray-400">
        T2 delay: the window an operator has to cancel a sign-in disable before it executes. 0 = immediate.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Decision feed row
// ---------------------------------------------------------------------------

function DecisionRow({
  d,
  isAdmin,
  onCancel,
  onApprove,
  cancelling,
  approving,
}: {
  d: DefenderAgentDecision;
  isAdmin: boolean;
  onCancel: (id: string) => void;
  onApprove: (id: string) => void;
  cancelling: boolean;
  approving: boolean;
}) {
  const tier = tierLabel(d);
  const status = decisionStatus(d);
  const canCancel = d.decision === "queue" && !d.cancelled && !d.job_ids.length;
  const canApprove = d.decision === "recommend" && !d.human_approved && !d.cancelled && isAdmin;

  return (
    <tr className="hover:bg-gray-50">
      <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{fmtTime(d.executed_at)}</td>
      <td className="px-3 py-2 max-w-xs">
        <div className="text-sm font-medium text-gray-800 truncate" title={d.alert_title}>
          {d.alert_title || d.alert_id}
        </div>
        {d.reason && <div className="text-xs text-gray-400 truncate" title={d.reason}>{d.reason}</div>}
      </td>
      <td className="whitespace-nowrap px-3 py-2">
        <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${severityColor(d.alert_severity)}`}>
          {d.alert_severity || "—"}
        </span>
      </td>
      <td className="whitespace-nowrap px-3 py-2">
        <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${tier.color}`}>
          {tier.label}
        </span>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-600 capitalize">{fmtAction(d)}</td>
      <td className="px-3 py-2 text-xs">
        <div className={status.color}>{status.label}</div>
        {d.not_before_at && !d.cancelled && !d.job_ids.length && (
          <div className="text-gray-400 text-xs">executes {fmtTime(d.not_before_at)}</div>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right">
        {canCancel && (
          <button
            onClick={() => onCancel(d.decision_id)}
            disabled={cancelling}
            className="rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs text-amber-700 hover:bg-amber-100 disabled:opacity-40"
          >
            Cancel
          </button>
        )}
        {canApprove && (
          <button
            onClick={() => onApprove(d.decision_id)}
            disabled={approving}
            className="rounded border border-blue-300 bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100 disabled:opacity-40"
          >
            Approve
          </button>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function AzureSecurityAgentPage() {
  const queryClient = useQueryClient();
  const [showConfig, setShowConfig] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [decisionFilter, setDecisionFilter] = useState<string>("");
  const [runningNow, setRunningNow] = useState(false);

  const configQuery = useQuery({
    queryKey: ["defender-agent-config"],
    queryFn: () => api.getDefenderAgentConfig(),
  });

  const summaryQuery = useQuery({
    queryKey: ["defender-agent-summary"],
    queryFn: () => api.getDefenderAgentSummary(),
    ...getPollingQueryOptions("live_30s"),
  });

  const decisionsQuery = useQuery({
    queryKey: ["defender-agent-decisions"],
    queryFn: () => api.listDefenderAgentDecisions({ limit: 200 }),
    ...getPollingQueryOptions("live_30s"),
  });

  const runsQuery = useQuery({
    queryKey: ["defender-agent-runs"],
    queryFn: () => api.listDefenderAgentRuns(10),
    ...getPollingQueryOptions("live_30s"),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => api.cancelDefenderAgentDecision(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }),
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => api.approveDefenderAgentDecision(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] });
      queryClient.invalidateQueries({ queryKey: ["defender-agent-summary"] });
    },
  });

  const config = configQuery.data;
  const summary = summaryQuery.data;
  const decisions = decisionsQuery.data?.decisions ?? [];
  const runs = runsQuery.data ?? [];

  // Determine admin status from session (assume session includes is_admin via cookie-based auth)
  // We'll surface the approve button based on whether the endpoint returns 200 or 403 on attempt
  // For display purposes, show the button to all logged-in users; the backend enforces admin-only
  const isAdmin = true; // Backend enforces; UI just shows the button

  async function handleSaveConfig(partial: Partial<DefenderAgentConfig>) {
    if (!config) return;
    setSavingConfig(true);
    try {
      await api.updateDefenderAgentConfig({
        enabled: partial.enabled ?? config.enabled,
        min_severity: partial.min_severity ?? config.min_severity,
        tier2_delay_minutes: partial.tier2_delay_minutes ?? config.tier2_delay_minutes,
        dry_run: partial.dry_run ?? config.dry_run,
      });
      queryClient.invalidateQueries({ queryKey: ["defender-agent-config"] });
      queryClient.invalidateQueries({ queryKey: ["defender-agent-summary"] });
    } finally {
      setSavingConfig(false);
    }
  }

  async function handleRunNow() {
    setRunningNow(true);
    try {
      await api.runDefenderAgentNow();
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["defender-agent-runs"] });
        queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] });
        queryClient.invalidateQueries({ queryKey: ["defender-agent-summary"] });
      }, 3000);
    } finally {
      setRunningNow(false);
    }
  }

  const filteredDecisions = useMemo(() => {
    if (!decisionFilter) return decisions;
    return decisions.filter((d) => d.decision === decisionFilter);
  }, [decisions, decisionFilter]);

  const enabled = config?.enabled ?? false;
  const dryRun = config?.dry_run ?? false;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Defender Autonomous Agent</h1>
          <p className="mt-1 text-sm text-gray-500">
            Polls Microsoft Defender alerts every 2 min. Auto-remediates T1, queues T2 with cancellation window, surfaces T3 for approval.
          </p>
        </div>
        <div className="flex items-center gap-2 mt-1">
          {dryRun && (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800">
              Dry Run — no actions taken
            </span>
          )}
          <span className={`rounded-full px-3 py-1 text-xs font-medium ${enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"}`}>
            {enabled ? "Agent Enabled" : "Agent Disabled"}
          </span>
          <button
            onClick={() => setShowConfig((v) => !v)}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 shadow-sm"
          >
            Configure
          </button>
          <button
            onClick={handleRunNow}
            disabled={runningNow}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 shadow-sm"
          >
            {runningNow ? "Running…" : "Run Now"}
          </button>
        </div>
      </div>

      {showConfig && config && (
        <ConfigDrawer config={config} onSave={handleSaveConfig} saving={savingConfig} />
      )}

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: "Actions Today", value: summary.total_actions_today, color: "text-blue-700" },
            { label: "Pending T2", value: summary.pending_tier2, color: summary.pending_tier2 ? "text-amber-700" : "text-gray-500" },
            { label: "Awaiting Approval", value: summary.pending_approvals, color: summary.pending_approvals ? "text-rose-700" : "text-gray-500" },
            { label: "Last Run", value: summary.last_run_at ? fmtTime(summary.last_run_at) : "—", color: summary.last_run_error ? "text-red-600" : "text-gray-700" },
          ].map(({ label, value, color }) => (
            <div key={label} className="rounded-lg bg-white shadow p-4">
              <p className="text-xs text-gray-500">{label}</p>
              <p className={`mt-1 text-lg font-semibold ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}
      {summary?.last_run_error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Last run error: {summary.last_run_error}
        </div>
      )}

      {/* Decision feed */}
      <div className="rounded-lg bg-white shadow">
        <div className="flex items-center gap-3 border-b border-gray-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Decision Feed</h2>
          <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">
            {filteredDecisions.length}{decisionFilter ? ` of ${decisions.length}` : ""}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <select
              value={decisionFilter}
              onChange={(e) => setDecisionFilter(e.target.value)}
              className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            >
              <option value="">All decisions</option>
              <option value="execute">T1 Immediate</option>
              <option value="queue">T2 Queued</option>
              <option value="recommend">T3 Recommend</option>
              <option value="skip">Skipped</option>
            </select>
          </div>
        </div>

        {decisionsQuery.isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="h-6 w-6 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
          </div>
        ) : filteredDecisions.length === 0 ? (
          <p className="py-8 text-center text-sm text-gray-500">
            {enabled ? "No decisions yet — agent will log all alert classifications here." : "Enable the agent to start monitoring Defender alerts."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-100 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {["Time", "Alert", "Severity", "Tier", "Action", "Status", ""].map((h) => (
                    <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {filteredDecisions.map((d) => (
                  <DecisionRow
                    key={d.decision_id}
                    d={d}
                    isAdmin={isAdmin}
                    onCancel={(id) => cancelMutation.mutate(id)}
                    onApprove={(id) => approveMutation.mutate(id)}
                    cancelling={cancelMutation.isPending}
                    approving={approveMutation.isPending}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Run history */}
      <div className="rounded-lg bg-white shadow">
        <div className="border-b border-gray-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Run History</h2>
        </div>
        {runs.length === 0 ? (
          <p className="py-6 text-center text-sm text-gray-500">No runs yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-100 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {["Started", "Completed", "Fetched", "New", "Decisions", "Actions", "Error"].map((h) => (
                    <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {runs.map((r) => (
                  <tr key={r.run_id} className={r.error ? "bg-red-50" : ""}>
                    <td className="px-3 py-2 text-xs text-gray-700 whitespace-nowrap">{fmtTime(r.started_at)}</td>
                    <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{fmtTime(r.completed_at)}</td>
                    <td className="px-3 py-2 text-xs text-gray-700 text-right">{r.alerts_fetched}</td>
                    <td className="px-3 py-2 text-xs text-gray-700 text-right">{r.alerts_new}</td>
                    <td className="px-3 py-2 text-xs text-gray-700 text-right">{r.decisions_made}</td>
                    <td className="px-3 py-2 text-xs text-gray-700 text-right">{r.actions_queued}</td>
                    <td className="px-3 py-2 text-xs text-red-600 max-w-xs truncate" title={r.error}>{r.error || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
