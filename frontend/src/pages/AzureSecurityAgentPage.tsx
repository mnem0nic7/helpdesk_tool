import { useState, useMemo, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { DefenderAgentConfig, DefenderAgentDecision, DefenderAgentSuppression, DefenderSuppressionType } from "../lib/api.ts";
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
  if (d.decision === "skip") {
    if (d.reason?.startsWith("Correlated:"))
      return { label: "Correlated", color: "bg-purple-100 text-purple-700" };
    return { label: "Skipped", color: "bg-gray-100 text-gray-500" };
  }
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

const ACTION_LABELS: Record<string, string> = {
  isolate_device:                "Isolate Device",
  unisolate_device:              "Release Isolation",
  run_av_scan:                   "Run AV Scan",
  collect_investigation_package: "Collect Forensic Package",
  restrict_app_execution:        "Restrict App Execution",
  revoke_sessions:               "Revoke Sessions",
  disable_sign_in:               "Disable Sign-In",
  device_sync:                   "Device Sync",
  device_retire:                 "Device Retire",
  device_wipe:                   "Device Wipe",
  // Red Canary parity
  stop_and_quarantine_file:      "Stop & Quarantine File",
  start_investigation:           "Start Investigation",
  create_block_indicator:        "Block IOC",
  unrestrict_app_execution:      "Remove App Restriction",
  reset_password:                "Reset Password",
  account_lockout:               "Account Lockout",
};

const ACTION_COLORS: Record<string, string> = {
  isolate_device:                "bg-orange-100 text-orange-800",
  unisolate_device:              "bg-emerald-100 text-emerald-800",
  run_av_scan:                   "bg-teal-100 text-teal-800",
  collect_investigation_package: "bg-indigo-100 text-indigo-800",
  restrict_app_execution:        "bg-rose-100 text-rose-800",
  revoke_sessions:               "bg-orange-100 text-orange-800",
  disable_sign_in:               "bg-red-100 text-red-800",
  device_sync:                   "bg-sky-100 text-sky-800",
  device_wipe:                   "bg-red-100 text-red-800",
  device_retire:                 "bg-red-100 text-red-800",
  // Red Canary parity
  stop_and_quarantine_file:      "bg-red-100 text-red-800",
  start_investigation:           "bg-violet-100 text-violet-800",
  create_block_indicator:        "bg-amber-100 text-amber-800",
  unrestrict_app_execution:      "bg-emerald-100 text-emerald-800",
  reset_password:                "bg-rose-100 text-rose-800",
  account_lockout:               "bg-red-200 text-red-900",
};

const SERVICE_SOURCE_MAP: Record<string, { label: string; color: string }> = {
  microsoftDefenderForEndpoint:    { label: "MDE",  color: "bg-blue-100 text-blue-800" },
  microsoftDefenderForOffice365:   { label: "MDO",  color: "bg-purple-100 text-purple-800" },
  microsoftCloudAppSecurity:       { label: "MCAS", color: "bg-cyan-100 text-cyan-800" },
  microsoftDefenderForCloudApps:   { label: "MCAS", color: "bg-cyan-100 text-cyan-800" },
  azureActiveDirectory:            { label: "AAD",  color: "bg-indigo-100 text-indigo-800" },
  microsoftDefenderForIdentity:    { label: "MDI",  color: "bg-violet-100 text-violet-800" },
  microsoftEntraIdProtection:      { label: "EIDP", color: "bg-violet-100 text-violet-800" },
  microsoftDefenderForCloud:       { label: "MDfC", color: "bg-sky-100 text-sky-800" },
};

function sourceLabel(src: string): { label: string; color: string } {
  if (!src) return { label: "—", color: "bg-gray-100 text-gray-500" };
  if (SERVICE_SOURCE_MAP[src]) return SERVICE_SOURCE_MAP[src];
  return { label: src.length > 8 ? src.slice(0, 7) + "…" : src, color: "bg-gray-100 text-gray-600" };
}

function fmtAction(d: DefenderAgentDecision): string {
  if (!d.action_type) return "—";
  return ACTION_LABELS[d.action_type] ?? d.action_type.replace(/_/g, " ");
}

function actionBadgeColor(actionType: string): string {
  return ACTION_COLORS[actionType] ?? "bg-gray-100 text-gray-600";
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
    entity_cooldown_hours: config.entity_cooldown_hours ?? 24,
    alert_dedup_window_minutes: config.alert_dedup_window_minutes ?? 30,
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
        <label className="block">
          <span className="text-xs text-gray-500">Entity cooldown (hours)</span>
          <input
            type="number"
            min={0}
            max={168}
            value={local.entity_cooldown_hours ?? 24}
            onChange={(e) => setLocal((p) => ({ ...p, entity_cooldown_hours: Math.max(0, Math.min(168, parseInt(e.target.value) || 0)) }))}
            className="mt-1 block w-24 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-500">Alert dedup window (min)</span>
          <input
            type="number"
            min={0}
            max={1440}
            value={local.alert_dedup_window_minutes ?? 30}
            onChange={(e) => setLocal((p) => ({ ...p, alert_dedup_window_minutes: Math.max(0, Math.min(1440, parseInt(e.target.value) || 0)) }))}
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
      <div className="text-xs text-gray-400 space-y-0.5">
        <p>T2 delay: the window an operator has to cancel a sign-in disable before it executes. 0 = immediate.</p>
        <p>Entity cooldown: suppress repeat actions on the same user or device within this window. 0 = disabled.</p>
        <p>Alert dedup window: collapse multiple alerts that would trigger the same action on the same entity within this window into a single decision. 0 = disabled.</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Entity chips
// ---------------------------------------------------------------------------

function EntityChips({ entities }: { entities: DefenderAgentDecision["entities"] }) {
  if (!entities.length) return null;
  const shown = entities.slice(0, 2);
  const overflow = entities.length - shown.length;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {shown.map((e, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600"
          title={`${e.type}: ${e.id}`}
        >
          {e.type === "user" ? (
            <svg className="h-3 w-3 shrink-0" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm4.5 4c0-2.485-2.015-4.5-4.5-4.5S3.5 9.515 3.5 12H12.5Z"/>
            </svg>
          ) : (
            <svg className="h-3 w-3 shrink-0" viewBox="0 0 16 16" fill="currentColor">
              <path d="M2 3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H9v1h1.5a.5.5 0 0 1 0 1h-5a.5.5 0 0 1 0-1H7v-1H3a1 1 0 0 1-1-1V3Z"/>
            </svg>
          )}
          <span className="max-w-[140px] truncate">{e.name || e.id}</span>
        </span>
      ))}
      {overflow > 0 && (
        <span className="inline-flex items-center rounded-full bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
          +{overflow} more
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail drawer
// ---------------------------------------------------------------------------

function AlertDetailDrawer({
  decisionId,
  onClose,
  isAdmin,
  onCancel,
  onApprove,
  onUnisolate,
  onUnrestrict,
  onForceInvestigate,
  onExecuteNow,
  onSuppressEntity,
}: {
  decisionId: string;
  onClose: () => void;
  isAdmin: boolean;
  onCancel: (id: string) => void;
  onApprove: (id: string) => void;
  onUnisolate: (id: string) => void;
  onUnrestrict: (id: string) => void;
  onForceInvestigate: (id: string) => void;
  onExecuteNow: (id: string) => void;
  onSuppressEntity: (type: DefenderSuppressionType, value: string) => void;
}) {
  const { data: d, isLoading } = useQuery({
    queryKey: ["defender-agent-decision", decisionId],
    queryFn: () => api.getDefenderAgentDecision(decisionId),
    staleTime: 10_000,
  });

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const raw = d?.alert_raw ?? {};
  const tier = d ? tierLabel(d) : null;
  const status = d ? decisionStatus(d) : null;
  const canCancel = d && d.decision === "queue" && !d.cancelled && !d.job_ids.length;
  const canApprove = d && d.decision === "recommend" && !d.human_approved && !d.cancelled && isAdmin;
  const canUnisolate = d && d.action_type === "isolate_device" && d.job_ids.length > 0 && !d.cancelled && isAdmin;
  const canUnrestrict = d && d.action_type === "restrict_app_execution" && d.job_ids.length > 0 && !d.cancelled && isAdmin;
  const canForceInvestigate = d && d.decision === "skip" && d.entities.some(e => e.type === "device") && isAdmin;
  const canExecuteNow = d && d.decision === "queue" && !d.cancelled && !d.job_ids.length && isAdmin;

  function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">{title}</h4>
        {children}
      </div>
    );
  }

  function Row({ label, value }: { label: string; value: React.ReactNode }) {
    if (!value) return null;
    return (
      <div className="flex gap-2 py-0.5">
        <span className="w-36 shrink-0 text-xs text-gray-400">{label}</span>
        <span className="text-xs text-gray-800 break-all">{value}</span>
      </div>
    );
  }

  const description = (raw.description as string) || "";
  const recommendedActions = (raw.recommendedActions as string) || "";
  const detectionSource = (raw.detectionSource as string) || "";
  const productName = (raw.productName as string) || "";
  const incidentId = (raw.incidentId as string | number | undefined);
  const lastUpdate = (raw.lastUpdateDateTime as string) || "";
  const evidence = Array.isArray(raw.evidence) ? raw.evidence as Record<string, unknown>[] : [];

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Slide-over panel */}
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-200 px-6 py-4">
          <div className="flex-1 min-w-0 pr-4">
            <h2 className="text-base font-semibold text-gray-900 leading-snug truncate">
              {d?.alert_title || "Alert Detail"}
            </h2>
            {d && (
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${severityColor(d.alert_severity)}`}>
                  {d.alert_severity}
                </span>
                {tier && (
                  <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${tier.color}`}>
                    {tier.label}
                  </span>
                )}
                {status && (
                  <span className={`text-xs ${status.color}`}>{status.label}</span>
                )}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-full p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close"
          >
            <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/>
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <div className="h-6 w-6 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
            </div>
          )}

          {d && (
            <>
              {/* Alert details */}
              <Section title="Alert details">
                <div className="space-y-0.5">
                  <Row label="Service source" value={d.service_source} />
                  <Row label="Detection source" value={detectionSource} />
                  <Row label="Product" value={productName} />
                  <Row label="Category" value={d.alert_category} />
                  <Row label="Incident ID" value={incidentId?.toString()} />
                  <Row label="Alert ID" value={d.alert_id} />
                  <Row label="Created" value={fmtTime(d.alert_created_at)} />
                  <Row label="Last updated" value={fmtTime(lastUpdate)} />
                </div>
              </Section>

              {/* MITRE ATT&CK techniques */}
              {(d.mitre_techniques ?? []).length > 0 && (
                <Section title="MITRE ATT&CK">
                  <div className="flex flex-wrap gap-1.5">
                    {(d.mitre_techniques ?? []).map((t) => (
                      <a
                        key={t}
                        href={`https://attack.mitre.org/techniques/${t.replace(".", "/")}/`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center rounded-md bg-red-50 border border-red-200 px-2 py-0.5 text-xs font-mono font-medium text-red-700 hover:bg-red-100"
                        title={`View ${t} on MITRE ATT&CK`}
                      >
                        {t}
                      </a>
                    ))}
                  </div>
                </Section>
              )}

              {description && (
                <Section title="Description">
                  <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap">{description}</p>
                </Section>
              )}

              {/* Affected entities */}
              {(d.entities.length > 0 || evidence.length > 0) && (
                <Section title="Affected entities">
                  <div className="space-y-2">
                    {d.entities.map((e, i) => (
                      <div key={i} className="flex items-start gap-2 rounded-lg bg-gray-50 px-3 py-2">
                        <span className="mt-0.5 shrink-0 text-gray-400">
                          {e.type === "user" ? (
                            <svg className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor">
                              <path d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm4.5 4c0-2.485-2.015-4.5-4.5-4.5S3.5 9.515 3.5 12H12.5Z"/>
                            </svg>
                          ) : (
                            <svg className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor">
                              <path d="M2 3a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H9v1h1.5a.5.5 0 0 1 0 1h-5a.5.5 0 0 1 0-1H7v-1H3a1 1 0 0 1-1-1V3Z"/>
                            </svg>
                          )}
                        </span>
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-gray-800 break-all">{e.name || e.id}</p>
                          <p className="text-xs text-gray-400 break-all">{e.id}</p>
                          <p className="text-xs text-gray-400 capitalize">{e.type}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {recommendedActions && (
                <Section title="Microsoft recommended actions">
                  <p className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap">{recommendedActions}</p>
                </Section>
              )}

              {/* Decision trace */}
              <Section title="Decision trace">
                <div className="space-y-0.5">
                  <Row
                    label="Tier / action"
                    value={
                      d.tier ? (
                        <span>
                          {`T${d.tier} — `}
                          {(d.action_types?.length ?? 0) > 1
                            ? (d.action_types ?? []).map(at => ACTION_LABELS[at] ?? at.replace(/_/g, " ")).join(" + ")
                            : fmtAction(d)}
                        </span>
                      ) : `Skip — ${d.reason}`
                    }
                  />
                  <Row label="Reason" value={d.reason} />
                  <Row label="Logged at" value={fmtTime(d.executed_at)} />
                  {d.decision !== "skip" && (
                    <Row
                      label="MDE write-back"
                      value={
                        d.alert_written_back
                          ? <span className="text-green-600 font-medium">✓ written</span>
                          : <span className="text-gray-400">—</span>
                      }
                    />
                  )}
                  {d.not_before_at && <Row label="Execute after" value={fmtTime(d.not_before_at)} />}
                  {d.job_ids.length > 0 && <Row label="Job IDs" value={d.job_ids.join(", ")} />}
                  {d.cancelled && (
                    <>
                      <Row label="Cancelled at" value={fmtTime(d.cancelled_at)} />
                      <Row label="Cancelled by" value={d.cancelled_by} />
                    </>
                  )}
                  {d.human_approved && (
                    <>
                      <Row label="Approved at" value={fmtTime(d.approved_at)} />
                      <Row label="Approved by" value={d.approved_by} />
                    </>
                  )}
                </div>
              </Section>
            </>
          )}
        </div>

        {/* Footer actions */}
        {d && (canCancel || canApprove || canUnisolate || canUnrestrict || canForceInvestigate || canExecuteNow) && (
          <div className="border-t border-gray-200 px-6 py-4 flex justify-end gap-3">
            {canExecuteNow && (
              <button
                onClick={() => {
                  if (confirm("Execute this T2 action immediately, skipping the delay window?")) {
                    onExecuteNow(d.decision_id);
                    onClose();
                  }
                }}
                className="rounded-lg border border-amber-400 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100"
              >
                Execute Now
              </button>
            )}
            {canCancel && (
              <button
                onClick={() => { onCancel(d.decision_id); onClose(); }}
                className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-700 hover:bg-amber-100"
              >
                Cancel action
              </button>
            )}
            {canUnisolate && (
              <button
                onClick={() => {
                  if (confirm("Release this device from network isolation? The device will regain full network access.")) {
                    onUnisolate(d.decision_id);
                    onClose();
                  }
                }}
                className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm text-emerald-700 hover:bg-emerald-100"
              >
                Release Isolation
              </button>
            )}
            {canUnrestrict && (
              <button
                onClick={() => {
                  if (confirm("Remove the app execution restriction from this device? The device will be able to run all applications again.")) {
                    onUnrestrict(d.decision_id);
                    onClose();
                  }
                }}
                className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm text-emerald-700 hover:bg-emerald-100"
              >
                Remove App Restriction
              </button>
            )}
            {canForceInvestigate && (
              <button
                onClick={() => {
                  if (confirm("Trigger an MDE automated investigation on the device(s) in this alert? This will create a device job.")) {
                    onForceInvestigate(d.decision_id);
                    onClose();
                  }
                }}
                className="rounded-lg border border-violet-300 bg-violet-50 px-4 py-2 text-sm text-violet-700 hover:bg-violet-100"
              >
                Force Investigate
              </button>
            )}
            {canApprove && (
              <button
                onClick={() => { onApprove(d.decision_id); onClose(); }}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                Approve & execute
              </button>
            )}
          </div>
        )}
        {isAdmin && d && d.entities.length > 0 && (
          <div className="mt-4 pt-3 border-t border-gray-100">
            <p className="text-xs text-gray-400 mb-2 font-medium uppercase tracking-wider">Suppress entity</p>
            <div className="flex flex-wrap gap-2">
              {d.entities.filter(e => e.type === "user" && (e.name || e.id)).map((e, i) => (
                <button
                  key={i}
                  onClick={() => {
                    const display = e.name || e.id;
                    if (confirm(`Add suppression for user "${display}"? The agent will skip future alerts for this user.`)) {
                      onSuppressEntity("entity_user", e.name || e.id);
                      onClose();
                    }
                  }}
                  className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                  title={`Suppress user: ${e.name || e.id}`}
                >
                  Suppress user: {(e.name || e.id).length > 30 ? (e.name || e.id).slice(0, 28) + "…" : (e.name || e.id)}
                </button>
              ))}
              {d.entities.filter(e => e.type === "device" && (e.name || e.id)).map((e, i) => (
                <button
                  key={i}
                  onClick={() => {
                    const display = e.name || e.id;
                    if (confirm(`Add suppression for device "${display}"? The agent will skip future alerts for this device.`)) {
                      onSuppressEntity("entity_device", e.name || e.id);
                      onClose();
                    }
                  }}
                  className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                  title={`Suppress device: ${e.name || e.id}`}
                >
                  Suppress device: {(e.name || e.id).length > 30 ? (e.name || e.id).slice(0, 28) + "…" : (e.name || e.id)}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
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
  onOpenDetail,
}: {
  d: DefenderAgentDecision;
  isAdmin: boolean;
  onCancel: (id: string) => void;
  onApprove: (id: string) => void;
  cancelling: boolean;
  approving: boolean;
  onOpenDetail: (id: string) => void;
}) {
  const tier = tierLabel(d);
  const status = decisionStatus(d);
  const canCancel = d.decision === "queue" && !d.cancelled && !d.job_ids.length;
  const canApprove = d.decision === "recommend" && !d.human_approved && !d.cancelled && isAdmin;

  return (
    <tr
      className="hover:bg-gray-50 cursor-pointer"
      onClick={() => onOpenDetail(d.decision_id)}
    >
      <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{fmtTime(d.executed_at)}</td>
      <td className="px-3 py-2 max-w-xs">
        <div className="text-sm font-medium text-gray-800 truncate" title={d.alert_title}>
          {d.alert_title || d.alert_id}
        </div>
        {d.reason && <div className="text-xs text-gray-400 truncate" title={d.reason}>{d.reason}</div>}
        <EntityChips entities={d.entities} />
        {(d.mitre_techniques ?? []).length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {(d.mitre_techniques ?? []).slice(0, 3).map((t) => (
              <span key={t} className="inline-block rounded bg-red-50 border border-red-200 px-1 py-0.5 text-xs font-mono text-red-700">
                {t}
              </span>
            ))}
            {(d.mitre_techniques ?? []).length > 3 && (
              <span className="inline-block rounded bg-red-50 border border-red-200 px-1 py-0.5 text-xs font-mono text-red-500">
                +{(d.mitre_techniques ?? []).length - 3}
              </span>
            )}
          </div>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2">
        {(() => { const s = sourceLabel(d.service_source); return (
          <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${s.color}`} title={d.service_source}>
            {s.label}
          </span>
        ); })()}
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
      <td className="whitespace-nowrap px-3 py-2">
        {d.action_type ? (
          <span className="inline-flex items-center gap-1">
            <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${actionBadgeColor(d.action_type)}`}>
              {fmtAction(d)}
            </span>
            {(d.action_types?.length ?? 0) > 1 && (
              <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-xs text-gray-600 font-medium"
                title={(d.action_types ?? []).map(at => ACTION_LABELS[at] ?? at.replace(/_/g, " ")).join(" + ")}>
                +{d.action_types.length - 1}
              </span>
            )}
          </span>
        ) : <span className="text-xs text-gray-400">—</span>}
      </td>
      <td className="px-3 py-2 text-xs">
        <div className={status.color}>{status.label}</div>
        {d.not_before_at && !d.cancelled && !d.job_ids.length && (
          <div className="text-gray-400 text-xs">executes {fmtTime(d.not_before_at)}</div>
        )}
      </td>
      <td
        className="whitespace-nowrap px-3 py-2 text-right"
        onClick={(e) => e.stopPropagation()}
      >
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
  const [mitreFilter, setMitreFilter] = useState<string>("");
  const [runningNow, setRunningNow] = useState(false);
  const [selectedDecisionId, setSelectedDecisionId] = useState<string | null>(null);
  const [showFindingsOnly, setShowFindingsOnly] = useState(false);
  const [expandedError, setExpandedError] = useState<string | null>(null);
  const [decisionLimit, setDecisionLimit] = useState(100);
  const decisionsHeadingRef = useRef<HTMLDivElement>(null);

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
    queryKey: ["defender-agent-decisions", decisionLimit],
    queryFn: () => api.listDefenderAgentDecisions({ limit: decisionLimit }),
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

  const unisolateMutation = useMutation({
    mutationFn: (id: string) => api.unisolateDefenderAgentDecision(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }),
  });

  const unrestrictMutation = useMutation({
    mutationFn: (id: string) => api.unrestrictDefenderAgentDecision(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }),
  });

  const forceInvestigateMutation = useMutation({
    mutationFn: (id: string) => api.forceInvestigateDecision(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }),
  });

  const executeNowMutation = useMutation({
    mutationFn: (id: string) => api.executeDecisionNow(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] });
      queryClient.invalidateQueries({ queryKey: ["defender-agent-summary"] });
    },
  });

  const indicatorsQuery = useQuery({
    queryKey: ["defender-agent-indicators"],
    queryFn: () => api.listDefenderIndicators(),
    staleTime: 60_000,
  });

  const deleteIndicatorMutation = useMutation({
    mutationFn: (id: string) => api.deleteDefenderIndicator(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-indicators"] }),
  });

  const suppressionsQuery = useQuery({
    queryKey: ["defender-agent-suppressions"],
    queryFn: () => api.listDefenderAgentSuppressions(),
    staleTime: 60_000,
  });

  const createSuppressionMutation = useMutation({
    mutationFn: (body: { suppression_type: DefenderSuppressionType; value: string; reason: string; expires_at?: string | null }) =>
      api.createDefenderAgentSuppression(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-suppressions"] }),
  });

  const deleteSuppressionMutation = useMutation({
    mutationFn: (id: string) => api.deleteDefenderAgentSuppression(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-suppressions"] }),
  });

  const { data: me } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.getMe(),
    staleTime: 5 * 60 * 1000,
  });

  const config = configQuery.data;
  const summary = summaryQuery.data;
  const decisions = decisionsQuery.data?.decisions ?? [];
  const decisionsTotal = decisionsQuery.data?.total ?? 0;
  const runs = runsQuery.data ?? [];
  const indicators = indicatorsQuery.data?.indicators ?? [];
  const suppressions = suppressionsQuery.data?.suppressions ?? [];

  const [suppressionForm, setSuppressionForm] = useState<{
    suppression_type: DefenderSuppressionType;
    value: string;
    reason: string;
    expires_at: string;
  }>({ suppression_type: "entity_user", value: "", reason: "", expires_at: "" });

  const isAdmin = me?.is_admin ?? false;

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
      setShowConfig(false);
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

  const allMitreTechniques = useMemo(() => {
    const seen = new Set<string>();
    for (const d of decisions) {
      for (const t of (d.mitre_techniques ?? [])) seen.add(t);
    }
    return Array.from(seen).sort();
  }, [decisions]);

  const filteredDecisions = useMemo(() => {
    let result = decisions;
    if (decisionFilter === "action_recommended") {
      result = result.filter((d) => d.decision !== "skip");
    } else if (decisionFilter) {
      result = result.filter((d) => d.decision === decisionFilter);
    }
    if (mitreFilter) {
      result = result.filter((d) => (d.mitre_techniques ?? []).includes(mitreFilter));
    }
    return result;
  }, [decisions, decisionFilter, mitreFilter]);

  function filterAndScrollToDecisions(filter: string) {
    setDecisionFilter(filter);
    setTimeout(() => decisionsHeadingRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

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
          <div className="rounded-lg bg-white shadow p-4">
            <p className="text-xs text-gray-500">Actions Today</p>
            <p className="mt-1 text-lg font-semibold text-blue-700">{summary.total_actions_today}</p>
          </div>
          <div
            className={`rounded-lg bg-white shadow p-4 transition ${summary.pending_tier2 ? "cursor-pointer hover:bg-amber-50" : ""}`}
            onClick={summary.pending_tier2 ? () => filterAndScrollToDecisions("queue") : undefined}
            title={summary.pending_tier2 ? "Click to filter decisions" : undefined}
          >
            <p className="text-xs text-gray-500">Pending T2</p>
            <p className={`mt-1 text-lg font-semibold ${summary.pending_tier2 ? "text-amber-700" : "text-gray-500"}`}>
              {summary.pending_tier2}
            </p>
          </div>
          <div
            className={`rounded-lg bg-white shadow p-4 transition ${summary.pending_approvals ? "cursor-pointer hover:bg-rose-50" : ""}`}
            onClick={summary.pending_approvals ? () => filterAndScrollToDecisions("recommend") : undefined}
            title={summary.pending_approvals ? "Click to filter decisions" : undefined}
          >
            <p className="text-xs text-gray-500">Awaiting Approval</p>
            <p className={`mt-1 text-lg font-semibold ${summary.pending_approvals ? "text-rose-700" : "text-gray-500"}`}>
              {summary.pending_approvals}
            </p>
          </div>
          <div className="rounded-lg bg-white shadow p-4">
            <p className="text-xs text-gray-500">Last Run</p>
            <p className={`mt-1 text-lg font-semibold ${summary.last_run_error ? "text-red-600" : "text-gray-700"}`}>
              {summary.last_run_at ? fmtTime(summary.last_run_at) : "—"}
            </p>
          </div>
        </div>
      )}
      {summary?.last_run_error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Last run error: {summary.last_run_error}
        </div>
      )}

      {/* Decision feed */}
      <div className="rounded-lg bg-white shadow" ref={decisionsHeadingRef}>
        <div className="flex items-center gap-3 border-b border-gray-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Decision Feed</h2>
          <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-700">
            {filteredDecisions.length}{(decisionFilter || mitreFilter) ? ` of ${decisions.length}` : ""}
          </span>
          <div className="ml-auto flex items-center gap-2 flex-wrap">
            {allMitreTechniques.length > 0 && (
              <select
                value={mitreFilter}
                onChange={(e) => setMitreFilter(e.target.value)}
                className="rounded-md border border-gray-300 px-2 py-1 text-xs"
                title="Filter by MITRE ATT&CK technique"
              >
                <option value="">All techniques</option>
                {allMitreTechniques.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            )}
            <select
              value={decisionFilter}
              onChange={(e) => setDecisionFilter(e.target.value)}
              className="rounded-md border border-gray-300 px-2 py-1 text-xs"
            >
              <option value="">All decisions</option>
              <option value="action_recommended">Action Recommended</option>
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
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-100 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    {["Time", "Alert", "Source", "Severity", "Tier", "Action", "Status", ""].map((h) => (
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
                      onOpenDetail={setSelectedDecisionId}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            {!decisionFilter && decisions.length < decisionsTotal && (
              <div className="border-t border-gray-100 px-5 py-3 flex items-center justify-between text-xs text-gray-500">
                <span>Showing {decisions.length} of {decisionsTotal}</span>
                <button
                  onClick={() => setDecisionLimit((l) => l + 100)}
                  className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
                >
                  Load more ({decisionsTotal - decisions.length} remaining)
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Run history */}
      <div className="rounded-lg bg-white shadow">
        <div className="border-b border-gray-200 px-5 py-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-gray-900">Run History</h2>
          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showFindingsOnly}
              onChange={(e) => setShowFindingsOnly(e.target.checked)}
              className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            Findings only
          </label>
        </div>
        {(() => {
          const visibleRuns = showFindingsOnly
            ? runs.filter((r) => r.decisions_made > 0 || r.actions_queued > 0)
            : runs;
          if (visibleRuns.length === 0) {
            return (
              <p className="py-6 text-center text-sm text-gray-500">
                {showFindingsOnly ? "No runs with findings." : "No runs yet."}
              </p>
            );
          }
          return (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-100 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    {["Started", "Completed", "Fetched", "New", "Decisions", "Skipped", "Actions", "Error"].map((h) => (
                      <th key={h} className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {visibleRuns.map((r) => (
                    <tr key={r.run_id} className={r.error ? "bg-red-50" : ""}>
                      <td className="px-3 py-2 text-xs text-gray-700 whitespace-nowrap">{fmtTime(r.started_at)}</td>
                      <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{fmtTime(r.completed_at)}</td>
                      <td className="px-3 py-2 text-xs text-gray-700 text-right">{r.alerts_fetched}</td>
                      <td className="px-3 py-2 text-xs text-gray-700 text-right">{r.alerts_new}</td>
                      <td className="px-3 py-2 text-xs text-gray-700 text-right">{r.decisions_made}</td>
                      <td className={`px-3 py-2 text-xs text-right ${(r.skips ?? 0) > 0 ? "text-amber-600 font-medium" : "text-gray-700"}`}>{r.skips ?? 0}</td>
                      <td className="px-3 py-2 text-xs text-gray-700 text-right">{r.actions_queued}</td>
                      <td className="px-3 py-2 text-xs max-w-xs">
                        {r.error ? (
                          <button
                            className="text-red-600 underline decoration-dotted text-left truncate block max-w-xs"
                            title="Click to view full error"
                            onClick={() => setExpandedError(r.error)}
                          >
                            {r.error}
                          </button>
                        ) : <span className="text-gray-400">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })()}
      </div>

      {/* Suppression rules panel (admin-only) */}
      {isAdmin && (
        <div className="mt-6 rounded-xl border border-slate-200 bg-white shadow">
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
            <h2 className="text-lg font-semibold text-gray-900">
              Suppression Rules
              {suppressions.length > 0 && (
                <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                  {suppressions.length} active
                </span>
              )}
            </h2>
            <span className="text-xs text-gray-400">Agent skips alerts matching any active rule</span>
          </div>

          {/* Add suppression form */}
          <div className="px-5 py-4 border-b border-slate-100 bg-slate-50/60">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Add suppression</p>
            <div className="flex flex-wrap gap-3 items-end">
              <label className="block">
                <span className="text-xs text-gray-500">Type</span>
                <select
                  value={suppressionForm.suppression_type}
                  onChange={(e) => setSuppressionForm((f) => ({ ...f, suppression_type: e.target.value as DefenderSuppressionType }))}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                >
                  <option value="entity_user">User (UPN / Object ID)</option>
                  <option value="entity_device">Device (name / ID)</option>
                  <option value="alert_title">Alert title contains</option>
                  <option value="alert_category">Alert category equals</option>
                </select>
              </label>
              <label className="block flex-1 min-w-[180px]">
                <span className="text-xs text-gray-500">Value</span>
                <input
                  type="text"
                  value={suppressionForm.value}
                  onChange={(e) => setSuppressionForm((f) => ({ ...f, value: e.target.value }))}
                  placeholder={
                    suppressionForm.suppression_type === "entity_user" ? "user@example.com" :
                    suppressionForm.suppression_type === "entity_device" ? "DESKTOP-ABC123" :
                    suppressionForm.suppression_type === "alert_title" ? "antivirus signature" :
                    "CredentialAccess"
                  }
                  className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                />
              </label>
              <label className="block flex-1 min-w-[160px]">
                <span className="text-xs text-gray-500">Reason</span>
                <input
                  type="text"
                  value={suppressionForm.reason}
                  onChange={(e) => setSuppressionForm((f) => ({ ...f, reason: e.target.value }))}
                  placeholder="Known good / false positive"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Expires (optional)</span>
                <input
                  type="datetime-local"
                  value={suppressionForm.expires_at}
                  onChange={(e) => setSuppressionForm((f) => ({ ...f, expires_at: e.target.value }))}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                />
              </label>
              <button
                onClick={() => {
                  if (!suppressionForm.value.trim()) return;
                  createSuppressionMutation.mutate({
                    suppression_type: suppressionForm.suppression_type,
                    value: suppressionForm.value.trim(),
                    reason: suppressionForm.reason,
                    expires_at: suppressionForm.expires_at
                      ? new Date(suppressionForm.expires_at).toISOString()
                      : null,
                  }, {
                    onSuccess: () => setSuppressionForm((f) => ({ ...f, value: "", reason: "", expires_at: "" })),
                  });
                }}
                disabled={!suppressionForm.value.trim() || createSuppressionMutation.isPending}
                className="rounded-lg bg-slate-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {createSuppressionMutation.isPending ? "Adding…" : "Add"}
              </button>
            </div>
          </div>

          {/* Active suppressions list */}
          {suppressions.length === 0 ? (
            <p className="py-6 text-center text-sm text-gray-400">No active suppressions.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    {["Type", "Value", "Reason", "Created by", "Created", "Expires", ""].map((h) => (
                      <th key={h} className="px-4 py-2 text-left font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {suppressions.map((s: DefenderAgentSuppression) => (
                    <tr key={s.id} className="hover:bg-slate-50">
                      <td className="whitespace-nowrap px-4 py-2">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          s.suppression_type === "entity_user" ? "bg-violet-100 text-violet-800" :
                          s.suppression_type === "entity_device" ? "bg-blue-100 text-blue-800" :
                          s.suppression_type === "alert_title" ? "bg-amber-100 text-amber-800" :
                          "bg-slate-100 text-slate-700"
                        }`}>
                          {s.suppression_type === "entity_user" ? "User" :
                           s.suppression_type === "entity_device" ? "Device" :
                           s.suppression_type === "alert_title" ? "Title contains" :
                           "Category"}
                        </span>
                      </td>
                      <td className="px-4 py-2 font-mono text-gray-800 max-w-xs truncate" title={s.value}>{s.value}</td>
                      <td className="px-4 py-2 text-gray-500 max-w-xs truncate" title={s.reason}>{s.reason || "—"}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-gray-400">{s.created_by || "—"}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-gray-400">{fmtTime(s.created_at)}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-gray-400">{s.expires_at ? fmtTime(s.expires_at) : "Permanent"}</td>
                      <td className="whitespace-nowrap px-4 py-2 text-right">
                        <button
                          onClick={() => {
                            if (confirm(`Remove suppression for "${s.value}"? The agent will resume acting on matching alerts.`)) {
                              deleteSuppressionMutation.mutate(s.id);
                            }
                          }}
                          disabled={deleteSuppressionMutation.isPending}
                          className="text-red-500 hover:text-red-700 disabled:opacity-50 text-xs"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Tenant-wide block indicators panel */}
      {indicators.length > 0 && (
        <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50/60">
          <div className="flex items-center justify-between px-5 py-3 border-b border-amber-200">
            <h3 className="text-sm font-semibold text-amber-900">
              Tenant-wide Block Indicators ({indicators.length})
            </h3>
            <span className="text-xs text-amber-700">Ti.ReadWrite.All required to manage</span>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead>
                <tr className="bg-amber-100/50">
                  <th className="px-4 py-2 text-left font-medium text-amber-800">Value</th>
                  <th className="px-4 py-2 text-left font-medium text-amber-800">Type</th>
                  <th className="px-4 py-2 text-left font-medium text-amber-800">Action</th>
                  <th className="px-4 py-2 text-left font-medium text-amber-800">Severity</th>
                  <th className="px-4 py-2 text-left font-medium text-amber-800">Title</th>
                  <th className="px-4 py-2 text-left font-medium text-amber-800">Created</th>
                  {isAdmin && <th className="px-4 py-2 text-right font-medium text-amber-800"></th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-100">
                {indicators.map((ind) => (
                  <tr key={ind.id} className="hover:bg-amber-50">
                    <td className="px-4 py-2 font-mono text-gray-700 break-all max-w-xs" title={ind.indicatorValue}>
                      {ind.indicatorValue.length > 40 ? ind.indicatorValue.slice(0, 38) + "…" : ind.indicatorValue}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-gray-600">{ind.indicatorType}</td>
                    <td className="whitespace-nowrap px-4 py-2">
                      <span className="rounded-full bg-red-100 px-2 py-0.5 text-red-800">{ind.action}</span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-gray-600">{ind.severity}</td>
                    <td className="px-4 py-2 text-gray-600 max-w-xs truncate" title={ind.title}>{ind.title}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-gray-400">
                      {ind.creationTimeDateTimeUtc ? fmtTime(ind.creationTimeDateTimeUtc) : "—"}
                    </td>
                    {isAdmin && (
                      <td className="whitespace-nowrap px-4 py-2 text-right">
                        <button
                          onClick={() => {
                            if (confirm(`Remove block indicator for "${ind.indicatorValue}"? This will allow this ${ind.indicatorType} on all devices.`)) {
                              deleteIndicatorMutation.mutate(ind.id);
                            }
                          }}
                          disabled={deleteIndicatorMutation.isPending}
                          className="text-red-500 hover:text-red-700 disabled:opacity-50 text-xs"
                        >
                          Remove
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Error expand modal */}
      {expandedError && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setExpandedError(null)}>
          <div className="w-full max-w-2xl rounded-xl bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
              <h3 className="text-sm font-semibold text-red-700">Run Error</h3>
              <button
                onClick={() => setExpandedError(null)}
                className="rounded-full p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
              >
                <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/>
                </svg>
              </button>
            </div>
            <pre className="max-h-96 overflow-y-auto px-5 py-4 text-xs text-red-800 whitespace-pre-wrap break-all font-mono bg-red-50 rounded-b-xl">
              {expandedError}
            </pre>
          </div>
        </div>
      )}

      {/* Detail drawer */}
      {selectedDecisionId && (
        <AlertDetailDrawer
          decisionId={selectedDecisionId}
          onClose={() => setSelectedDecisionId(null)}
          isAdmin={isAdmin}
          onCancel={(id) => { cancelMutation.mutate(id); queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }); }}
          onApprove={(id) => { approveMutation.mutate(id); queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }); }}
          onUnisolate={(id) => { unisolateMutation.mutate(id); queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }); }}
          onUnrestrict={(id) => { unrestrictMutation.mutate(id); queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }); }}
          onForceInvestigate={(id) => { forceInvestigateMutation.mutate(id); queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }); }}
          onExecuteNow={(id) => { executeNowMutation.mutate(id); }}
          onSuppressEntity={(type, value) => {
            const reason = prompt(`Suppression reason for "${value}" (optional):`);
            createSuppressionMutation.mutate({ suppression_type: type, value, reason: reason ?? "" });
          }}
        />
      )}
    </div>
  );
}
