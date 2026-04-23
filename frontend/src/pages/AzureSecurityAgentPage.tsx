import { useState, useMemo, useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { DefenderAgentConfig, DefenderAgentCustomRule, DefenderAgentPlaybook, DefenderAgentDecision, DefenderAgentMetrics, DefenderAgentSuppression, DefenderAgentWatchlistEntry, DefenderSuppressionType } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";
import { DEFENDER_FAQ } from "../lib/defenderFaq.ts";

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
  if (d.resolved)       return { label: "Resolved", color: "text-emerald-600 font-medium" };
  if (d.human_approved) return { label: "Approved", color: "text-blue-600 font-medium" };
  return { label: "Logged",                          color: "text-gray-500" };
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

function confidenceBadge(score: number): { label: string; color: string } {
  if (score >= 85) return { label: `${score}%`, color: "bg-emerald-100 text-emerald-800" };
  if (score >= 70) return { label: `${score}%`, color: "bg-yellow-100 text-yellow-800" };
  if (score > 0)   return { label: `${score}%`, color: "bg-orange-100 text-orange-800" };
  return { label: "—", color: "bg-gray-100 text-gray-400" };
}

function dispositionBadge(d: DefenderAgentDecision["disposition"]): { label: string; color: string } | null {
  if (!d) return null;
  if (d === "true_positive")  return { label: "TP",           color: "bg-emerald-100 text-emerald-800" };
  if (d === "false_positive") return { label: "FP",           color: "bg-red-100 text-red-800" };
  if (d === "inconclusive")   return { label: "Inconclusive", color: "bg-yellow-100 text-yellow-800" };
  return null;
}

// ---------------------------------------------------------------------------
// FAQ drawer
// ---------------------------------------------------------------------------

function renderFaqInline(text: string): ReactNode {
  const parts: ReactNode[] = [];
  const re = /(\*\*(.+?)\*\*|`(.+?)`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[0].startsWith("**")) {
      parts.push(<strong key={m.index} className="font-semibold">{m[2]}</strong>);
    } else {
      parts.push(
        <code key={m.index} className="rounded bg-slate-100 px-1 font-mono text-xs text-slate-700">{m[3]}</code>
      );
    }
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.length === 1 && typeof parts[0] === "string" ? parts[0] : <>{parts}</>;
}

function FaqMarkdown({ content }: { content: string }) {
  const blocks = content.trim().split(/\n\n+/);
  return (
    <div className="space-y-4 text-sm leading-relaxed text-gray-800">
      {blocks.map((block, i) => {
        const trimmed = block.trim();
        if (!trimmed) return null;

        // Horizontal rule
        if (/^-{3,}$/.test(trimmed))
          return <hr key={i} className="border-gray-200" />;

        // H1 — page title, render as small label
        if (trimmed.startsWith("# "))
          return (
            <p key={i} className="text-xs text-gray-400 uppercase tracking-wide">
              {trimmed.slice(2)}
            </p>
          );

        // H2 — section header
        if (trimmed.startsWith("## "))
          return (
            <h2 key={i} className="mt-2 border-b border-gray-200 pb-1 text-base font-bold text-gray-900">
              {trimmed.slice(3)}
            </h2>
          );

        // H3 — question
        if (trimmed.startsWith("### "))
          return (
            <h3 key={i} className="font-semibold text-gray-900">
              {trimmed.slice(4)}
            </h3>
          );

        // Markdown table
        const tableLines = trimmed.split("\n");
        if (tableLines.length >= 3 && tableLines[0].includes("|") && tableLines[1].replace(/[-|: ]/g, "") === "") {
          const headers = tableLines[0].split("|").map(c => c.trim()).filter(Boolean);
          const rows = tableLines.slice(2).map(line =>
            line.split("|").map(c => c.trim()).filter(Boolean)
          );
          return (
            <div key={i} className="overflow-x-auto rounded border border-gray-200">
              <table className="min-w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    {headers.map((h, j) => (
                      <th key={j} className="px-3 py-2 text-left font-semibold text-gray-700 whitespace-nowrap">
                        {renderFaqInline(h)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {rows.map((row, j) => (
                    <tr key={j} className="even:bg-gray-50/50">
                      {row.map((cell, k) => (
                        <td key={k} className="px-3 py-2 text-gray-700 align-top">
                          {renderFaqInline(cell)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }

        const lines = trimmed.split("\n").filter(l => l.trim());

        // Unordered list
        if (lines.length > 0 && lines.every(l => /^[-*]\s/.test(l))) {
          return (
            <ul key={i} className="space-y-1 pl-1">
              {lines.map((l, j) => (
                <li key={j} className="flex gap-2">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-gray-400" />
                  <span>{renderFaqInline(l.replace(/^[-*]\s+/, ""))}</span>
                </li>
              ))}
            </ul>
          );
        }

        // Plain paragraph
        return <p key={i}>{renderFaqInline(trimmed)}</p>;
      })}
    </div>
  );
}

function FaqDrawer({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} aria-hidden="true" />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-2xl flex-col bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900">Defender Agent — FAQ</h2>
            <p className="text-xs text-gray-500 mt-0.5">Common questions about tiers, rules, config, and troubleshooting</p>
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-full p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
            aria-label="Close FAQ"
          >
            <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/>
            </svg>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <FaqMarkdown content={DEFENDER_FAQ} />
        </div>
      </div>
    </>
  );
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
    min_confidence: config.min_confidence ?? 0,
    poll_interval_seconds: config.poll_interval_seconds ?? 0,
    teams_tier1_webhook: config.teams_tier1_webhook ?? "",
    teams_tier2_webhook: config.teams_tier2_webhook ?? "",
    teams_tier3_webhook: config.teams_tier3_webhook ?? "",
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
        <label className="block">
          <span className="text-xs text-gray-500">Min confidence (0–100)</span>
          <input
            type="number"
            min={0}
            max={100}
            value={local.min_confidence ?? 0}
            onChange={(e) => setLocal((p) => ({ ...p, min_confidence: Math.max(0, Math.min(100, parseInt(e.target.value) || 0)) }))}
            className="mt-1 block w-24 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs text-gray-500">Poll interval (seconds, 0 = default)</span>
          <input
            type="number"
            min={0}
            max={86400}
            value={local.poll_interval_seconds ?? 0}
            onChange={(e) => setLocal((p) => ({ ...p, poll_interval_seconds: Math.max(0, parseInt(e.target.value) || 0) }))}
            className="mt-1 block w-28 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
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
      <div className="mt-3 space-y-2">
        <p className="text-xs font-medium text-gray-600">Teams notification webhooks (per tier, optional — overrides global webhook)</p>
        {[1, 2, 3].map((tier) => {
          const key = `teams_tier${tier}_webhook` as keyof DefenderAgentConfig;
          return (
            <label key={tier} className="flex items-center gap-2 text-xs">
              <span className={`w-16 shrink-0 text-right font-medium ${tier === 1 ? "text-green-700" : tier === 2 ? "text-amber-700" : "text-blue-700"}`}>T{tier} hook</span>
              <input
                type="url"
                value={(local[key] as string) ?? ""}
                placeholder="https://…"
                onChange={(e) => setLocal((p) => ({ ...p, [key]: e.target.value }))}
                className="flex-1 rounded-md border border-gray-300 px-2 py-1 text-xs"
              />
            </label>
          );
        })}
      </div>
      <div className="text-xs text-gray-400 space-y-0.5 mt-2">
        <p>T2 delay: the window an operator has to cancel a sign-in disable before it executes. 0 = immediate.</p>
        <p>Entity cooldown: suppress repeat actions on the same user or device within this window. 0 = disabled.</p>
        <p>Alert dedup window: collapse multiple alerts that would trigger the same action on the same entity within this window into a single decision. 0 = disabled.</p>
        <p>Min confidence: T1/T2 decisions from rules below this score (0–100) are downgraded to T3 recommend. 0 = disabled (all rules execute at their assigned tier).</p>
        <p>Poll interval: how often the agent polls for new alerts. 0 = use the server default (AZURE_DEFENDER_AGENT_POLL_SECONDS).</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Entity chips
// ---------------------------------------------------------------------------

function complianceColor(state: string | undefined): string {
  switch ((state || "").toLowerCase()) {
    case "compliant":    return "bg-emerald-100 text-emerald-700";
    case "noncompliant": return "bg-red-100 text-red-700";
    default:             return "bg-gray-100 text-gray-500";
  }
}

function priorityBandColor(band: string | undefined): string {
  switch ((band || "").toLowerCase()) {
    case "p0": return "bg-red-100 text-red-700";
    case "p1": return "bg-orange-100 text-orange-700";
    case "p2": return "bg-yellow-100 text-yellow-700";
    case "p3": return "bg-slate-100 text-slate-600";
    default:   return "bg-gray-100 text-gray-500";
  }
}

function EntityChips({
  entities,
  onEntityClick,
  watchlistedIds,
}: {
  entities: DefenderAgentDecision["entities"];
  onEntityClick?: (entityId: string, entityName: string) => void;
  watchlistedIds?: Set<string>;
}) {
  if (!entities.length) return null;
  const shown = entities.slice(0, 2);
  const overflow = entities.length - shown.length;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {shown.map((e, i) => {
        const tooltip = [
          `${e.type}: ${e.id}`,
          e.department ? `Dept: ${e.department}` : "",
          e.compliance_state ? `Compliance: ${e.compliance_state}` : "",
          e.enabled === false ? "DISABLED" : "",
        ].filter(Boolean).join(" | ");
        const entityLookupKey = e.id || e.name;
        const isWatchlisted = watchlistedIds && entityLookupKey ? watchlistedIds.has((entityLookupKey).toLowerCase()) : false;
        return (
          <span
            key={i}
            className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-xs ${isWatchlisted ? "bg-amber-100 text-amber-800 ring-1 ring-amber-300" : "bg-gray-100 text-gray-600"} ${onEntityClick ? "cursor-pointer hover:bg-gray-200" : ""}`}
            title={onEntityClick ? `${tooltip} — click to view timeline` : tooltip || `${e.type}: ${e.id}`}
            onClick={onEntityClick && entityLookupKey ? (ev) => { ev.stopPropagation(); onEntityClick(entityLookupKey, e.name || e.id); } : undefined}
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
            {isWatchlisted && (
              <svg className="h-3 w-3 shrink-0 text-amber-600" viewBox="0 0 16 16" fill="currentColor" aria-label="Watchlisted entity">
                <path d="M8 1l1.8 3.6L14 5.3l-3 2.9.7 4.1L8 10.2l-3.7 2.1.7-4.1-3-2.9 4.2-.7L8 1Z"/>
              </svg>
            )}
            <span className="max-w-[140px] truncate">{e.name || e.id}</span>
            {e.enabled === false && (
              <span className="rounded-full bg-red-200 px-1 text-[10px] text-red-700 font-medium">disabled</span>
            )}
            {e.priority_band && (
              <span className={`rounded-full px-1 text-[10px] font-medium ${priorityBandColor(e.priority_band)}`}>
                {e.priority_band.toUpperCase()}
              </span>
            )}
            {e.compliance_state && (
              <span className={`rounded-full px-1 text-[10px] font-medium ${complianceColor(e.compliance_state)}`}>
                {e.compliance_state}
              </span>
            )}
          </span>
        );
      })}
      {overflow > 0 && (
        <span className="inline-flex items-center rounded-full bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
          +{overflow} more
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Entity timeline drawer
// ---------------------------------------------------------------------------

function EntityTimelineDrawer({
  entityId,
  entityName,
  onClose,
  onOpenDecision,
}: {
  entityId: string;
  entityName: string;
  onClose: () => void;
  onOpenDecision: (id: string) => void;
}) {
  const { data, isLoading } = useQuery({
    queryKey: ["defender-agent-entity-timeline", entityId],
    queryFn: () => api.getEntityTimeline(entityId, 100),
    staleTime: 30_000,
  });

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const decisions = data?.decisions ?? [];

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose} aria-hidden="true" />
      <div className="fixed right-0 top-0 z-50 flex h-full w-full max-w-xl flex-col bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-gray-200 px-6 py-4">
          <div className="min-w-0 flex-1 pr-4">
            <h2 className="text-base font-semibold text-gray-900">Entity Timeline</h2>
            <p className="mt-0.5 text-xs text-gray-500 break-all">{entityName || entityId}</p>
            {data && (
              <p className="mt-0.5 text-xs text-gray-400">{data.total} decision{data.total !== 1 ? "s" : ""} on record</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="shrink-0 rounded-full p-1 text-gray-400 hover:bg-gray-100"
            aria-label="Close"
          >
            <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/>
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {isLoading && (
            <div className="flex items-center justify-center py-16">
              <div className="h-6 w-6 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
            </div>
          )}
          {!isLoading && decisions.length === 0 && (
            <p className="py-12 text-center text-sm text-gray-400">No decisions found for this entity.</p>
          )}
          {decisions.length > 0 && (
            <div className="divide-y divide-gray-100">
              {decisions.map((d) => {
                const tl = tierLabel(d);
                const st = decisionStatus(d);
                const disp = dispositionBadge(d.disposition);
                return (
                  <button
                    key={d.decision_id}
                    className="w-full text-left px-5 py-3 hover:bg-gray-50 transition-colors"
                    onClick={() => { onClose(); onOpenDecision(d.decision_id); }}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-800 truncate">{d.alert_title || d.alert_id}</p>
                        <p className="mt-0.5 text-xs text-gray-400 truncate">{d.reason}</p>
                        {(d.mitre_techniques ?? []).length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {(d.mitre_techniques ?? []).slice(0, 2).map((t) => (
                              <span key={t} className="rounded bg-red-50 border border-red-200 px-1 py-0.5 text-[10px] font-mono text-red-700">{t}</span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="shrink-0 text-right space-y-1">
                        <p className="text-xs text-gray-400 whitespace-nowrap">{fmtTime(d.executed_at)}</p>
                        <span className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium ${tl.color}`}>{tl.label}</span>
                        {d.action_type && (
                          <span className={`ml-1 inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium ${actionBadgeColor(d.action_type)}`}>
                            {ACTION_LABELS[d.action_type] ?? d.action_type.replace(/_/g, " ")}
                          </span>
                        )}
                        <p className={`text-[10px] ${st.color}`}>{st.label}</p>
                        {disp && (
                          <span className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium ${disp.color}`}>{disp.label}</span>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Metrics dashboard
// ---------------------------------------------------------------------------

const ACTION_LABELS_SHORT: Record<string, string> = {
  isolate_device: "Isolate Device",
  unisolate_device: "Release Isolation",
  run_av_scan: "AV Scan",
  collect_investigation_package: "Forensic Pkg",
  restrict_app_execution: "Restrict App",
  revoke_sessions: "Revoke Sessions",
  disable_sign_in: "Disable Sign-In",
  device_sync: "Device Sync",
  device_retire: "Retire Device",
  device_wipe: "Wipe Device",
  stop_and_quarantine_file: "Stop+Quarantine",
  start_investigation: "Start Invest.",
  create_block_indicator: "Block IOC",
  unrestrict_app_execution: "Remove Restriction",
  reset_password: "Reset Password",
  account_lockout: "Account Lockout",
};

function MetricsDashboard({ metrics }: { metrics: DefenderAgentMetrics }) {
  const tierOrder = ["T1", "T2", "T3", "skip"] as const;
  const tierColors: Record<string, string> = {
    T1: "bg-green-500",
    T2: "bg-amber-500",
    T3: "bg-blue-500",
    skip: "bg-gray-300",
  };
  const tierLabels: Record<string, string> = { T1: "T1 Immediate", T2: "T2 Queued", T3: "T3 Recommend", skip: "Skipped" };
  const total = metrics.total_decisions || 1;

  const maxDaily = Math.max(...metrics.daily_volumes.map((d) => d.count), 1);

  const dispColors: Record<string, string> = {
    true_positive: "text-emerald-700",
    false_positive: "text-red-600",
    inconclusive: "text-yellow-600",
    unreviewed: "text-gray-400",
  };

  return (
    <div className="space-y-4">
      {/* Tier distribution */}
      <div>
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Tier Distribution ({metrics.total_decisions} decisions)</p>
        <div className="flex h-4 rounded-full overflow-hidden gap-px bg-gray-100">
          {tierOrder.map((tier) => {
            const count = metrics.by_tier[tier] ?? 0;
            const pct = (count / total) * 100;
            if (!pct) return null;
            return (
              <div
                key={tier}
                className={`${tierColors[tier]} h-full transition-all`}
                style={{ width: `${pct}%` }}
                title={`${tierLabels[tier]}: ${count} (${pct.toFixed(0)}%)`}
              />
            );
          })}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
          {tierOrder.map((tier) => {
            const count = metrics.by_tier[tier] ?? 0;
            return (
              <span key={tier} className="flex items-center gap-1 text-xs text-gray-600">
                <span className={`inline-block h-2 w-2 rounded-full ${tierColors[tier]}`} />
                {tierLabels[tier]}: <strong>{count}</strong>
              </span>
            );
          })}
        </div>
      </div>

      {/* Daily volume sparkline */}
      {metrics.daily_volumes.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Daily Volume (last {metrics.period_days} days)</p>
          <div className="flex items-end gap-0.5 h-12">
            {metrics.daily_volumes.map((d) => (
              <div
                key={d.date}
                className="flex-1 bg-blue-200 rounded-t min-w-[2px]"
                style={{ height: `${Math.max(4, (d.count / maxDaily) * 48)}px` }}
                title={`${d.date}: ${d.count}`}
              />
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Disposition summary */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Disposition</p>
          <div className="space-y-0.5">
            {(["true_positive", "false_positive", "inconclusive", "unreviewed"] as const).map((key) => {
              const count = metrics.disposition_summary[key] ?? 0;
              return (
                <div key={key} className="flex justify-between text-xs">
                  <span className={dispColors[key]}>{key.replace(/_/g, " ")}</span>
                  <strong className={dispColors[key]}>{count}</strong>
                </div>
              );
            })}
            <div className="flex justify-between text-xs border-t border-gray-100 pt-0.5 mt-0.5">
              <span className="text-gray-500">FP rate</span>
              <strong className={metrics.false_positive_rate > 0.2 ? "text-red-600" : "text-gray-700"}>
                {(metrics.false_positive_rate * 100).toFixed(0)}%
              </strong>
            </div>
          </div>
        </div>

        {/* Top entities */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Top Entities</p>
          {metrics.top_entities.length === 0 && <p className="text-xs text-gray-400">None</p>}
          <div className="space-y-0.5">
            {metrics.top_entities.slice(0, 5).map((e) => (
              <div key={e.id} className="flex justify-between text-xs gap-2">
                <span className="text-gray-700 truncate" title={e.id}>{e.name || e.id}</span>
                <strong className="text-gray-500 shrink-0">{e.count}</strong>
              </div>
            ))}
          </div>
        </div>

        {/* Top alert types */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Top Alert Types</p>
          {metrics.top_alert_titles.length === 0 && <p className="text-xs text-gray-400">None</p>}
          <div className="space-y-0.5">
            {metrics.top_alert_titles.slice(0, 5).map((a) => (
              <div key={a.title} className="flex justify-between text-xs gap-2">
                <span className="text-gray-700 truncate" title={a.title}>{a.title}</span>
                <strong className="text-gray-500 shrink-0">{a.count}</strong>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Top actions */}
      {metrics.top_actions.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Top Response Actions</p>
          <div className="flex flex-wrap gap-1.5">
            {metrics.top_actions.slice(0, 8).map((a) => (
              <span key={a.action} className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-700">
                {ACTION_LABELS_SHORT[a.action] ?? a.action.replace(/_/g, " ")}
                <span className="rounded-full bg-gray-200 px-1 font-medium">{a.count}</span>
              </span>
            ))}
          </div>
        </div>
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
  onResolve,
  onUnisolate,
  onUnrestrict,
  onForceInvestigate,
  onExecuteNow,
  onEnableSignIn,
  onSuppressEntity,
  onOpenEntityTimeline,
}: {
  decisionId: string;
  onClose: () => void;
  isAdmin: boolean;
  onCancel: (id: string) => void;
  onApprove: (id: string) => void;
  onResolve: (id: string) => void;
  onUnisolate: (id: string) => void;
  onUnrestrict: (id: string) => void;
  onForceInvestigate: (id: string) => void;
  onExecuteNow: (id: string) => void;
  onEnableSignIn: (id: string) => void;
  onSuppressEntity: (type: DefenderSuppressionType, value: string) => void;
  onOpenEntityTimeline: (entityId: string, entityName: string) => void;
}) {
  const queryClient = useQueryClient();
  const { data: d, isLoading } = useQuery({
    queryKey: ["defender-agent-decision", decisionId],
    queryFn: () => api.getDefenderAgentDecision(decisionId),
    staleTime: 10_000,
  });

  const [dispositionNote, setDispositionNote] = useState("");
  const dispositionMut = useMutation({
    mutationFn: ({ disp }: { disp: "true_positive" | "false_positive" | "inconclusive" }) =>
      api.setDefenderAgentDisposition(decisionId, disp, dispositionNote),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["defender-agent-decision", decisionId] });
      queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] });
      queryClient.invalidateQueries({ queryKey: ["defender-agent-disposition-stats"] });
    },
  });

  const [noteText, setNoteText] = useState("");
  const noteMut = useMutation({
    mutationFn: () => api.addDecisionNote(decisionId, noteText),
    onSuccess: () => {
      setNoteText("");
      queryClient.invalidateQueries({ queryKey: ["defender-agent-decision", decisionId] });
    },
  });

  const narrativeMut = useMutation({
    mutationFn: () => api.generateDefenderNarrative(decisionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["defender-agent-decision", decisionId] });
      queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] });
    },
  });

  const [tagInput, setTagInput] = useState("");
  const addTagMut = useMutation({
    mutationFn: (tag: string) => api.addDecisionTag(decisionId, tag),
    onSuccess: () => {
      setTagInput("");
      queryClient.invalidateQueries({ queryKey: ["defender-agent-decision", decisionId] });
    },
  });
  const removeTagMut = useMutation({
    mutationFn: (tag: string) => api.removeDecisionTag(decisionId, tag),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-decision", decisionId] }),
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
  const canApprove = d && !d.human_approved && !d.cancelled && isAdmin;
  const canResolve = d && !d.resolved;
  const canExecuteNow = d && d.decision === "queue" && !d.cancelled && !d.job_ids.length && isAdmin;
  const canForceInvestigate = d && d.entities.some(e => e.type === "device") && isAdmin;
  const canUnisolate = d && d.entities.some(e => e.type === "device") && !d.cancelled && isAdmin;
  const canUnrestrict = d && d.entities.some(e => e.type === "device") && !d.cancelled && isAdmin;
  const canEnableSignIn = d && d.entities.some(e => e.type === "user" || e.type === "account") && !d.cancelled && isAdmin;

  function Section({ title, children }: { title: string; children: React.ReactNode }) {
    return (
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">{title}</h4>
        {children}
      </div>
    );
  }

  function Row({ label, value, valueClass }: { label: string; value: React.ReactNode; valueClass?: string }) {
    if (!value) return null;
    return (
      <div className="flex gap-2 py-0.5">
        <span className="w-36 shrink-0 text-xs text-gray-400">{label}</span>
        <span className={`text-xs break-all ${valueClass ?? "text-gray-800"}`}>{value}</span>
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
                      <div
                        key={i}
                        className="flex items-start gap-2 rounded-lg bg-gray-50 px-3 py-2 cursor-pointer hover:bg-gray-100 transition-colors"
                        title="Click to view entity timeline"
                        onClick={() => {
                          const lookupKey = e.id || e.name;
                          if (lookupKey) onOpenEntityTimeline(lookupKey, e.name || e.id);
                        }}
                      >
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
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <p className="text-xs font-medium text-gray-800 break-all">{e.name || e.id}</p>
                            {e.enabled === false && (
                              <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700">Disabled</span>
                            )}
                            {e.priority_band && (
                              <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${priorityBandColor(e.priority_band)}`}>
                                {e.priority_band.toUpperCase()}
                              </span>
                            )}
                            {e.compliance_state && (
                              <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${complianceColor(e.compliance_state)}`}>
                                {e.compliance_state}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-gray-400 break-all">{e.id}</p>
                          <p className="text-xs text-gray-400 capitalize">{e.type}</p>
                          {/* User enrichment */}
                          {(e.job_title || e.department) && (
                            <p className="text-xs text-gray-500 mt-0.5">
                              {[e.job_title, e.department].filter(Boolean).join(" · ")}
                            </p>
                          )}
                          {e.last_sign_in && (
                            <p className="text-xs text-gray-400 mt-0.5">Last sign-in: {fmtTime(e.last_sign_in)}</p>
                          )}
                          {/* Device enrichment */}
                          {e.os && <p className="text-xs text-gray-500 mt-0.5">{e.os}</p>}
                          {e.last_sync && (
                            <p className="text-xs text-gray-400 mt-0.5">Last sync: {fmtTime(e.last_sync)}</p>
                          )}
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
                {/* AI narrative — shown when present; Generate button when absent (FIX-04) */}
                {d.ai_narrative ? (
                  <div className="mb-3 rounded-md bg-blue-50 border border-blue-200 px-3 py-2">
                    <p className="text-xs font-semibold text-blue-700 mb-1">AI Narrative</p>
                    <p className="text-xs text-blue-800 leading-relaxed">{d.ai_narrative}</p>
                  </div>
                ) : d.decision !== "skip" ? (
                  <div className="mb-3">
                    <button
                      onClick={() => narrativeMut.mutate()}
                      disabled={narrativeMut.isPending}
                      className="rounded-md border border-blue-300 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                    >
                      {narrativeMut.isPending ? "Generating…" : "Generate AI summary"}
                    </button>
                  </div>
                ) : null}
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
                  {(d.confidence_score ?? 0) > 0 && (
                    <Row
                      label="Confidence"
                      value={
                        <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${confidenceBadge(d.confidence_score ?? 0).color}`}>
                          {confidenceBadge(d.confidence_score ?? 0).label}
                        </span>
                      }
                    />
                  )}
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
                  {d.remediation_confirmed && (
                    <Row
                      label="Remediation"
                      value={`Confirmed ✓ at ${fmtTime(d.confirmed_at)}`}
                      valueClass="text-emerald-600 font-medium"
                    />
                  )}
                  {d.remediation_failed && (
                    <Row
                      label="Remediation"
                      value={`Failed ✗ at ${fmtTime(d.confirmed_at)} — check job logs`}
                      valueClass="text-red-600 font-medium"
                    />
                  )}
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
                  {d.disposition && (
                    <>
                      <Row
                        label="Disposition"
                        value={
                          <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${dispositionBadge(d.disposition)?.color ?? ""}`}>
                            {d.disposition === "true_positive" ? "True Positive" :
                             d.disposition === "false_positive" ? "False Positive" : "Inconclusive"}
                          </span>
                        }
                      />
                      {d.disposition_note && <Row label="Analyst note" value={d.disposition_note} />}
                      {d.disposition_by && <Row label="Reviewed by" value={d.disposition_by} />}
                      {d.disposition_at && <Row label="Reviewed at" value={fmtTime(d.disposition_at)} />}
                    </>
                  )}
                </div>
              </Section>
            </>
          )}
        </div>

        {/* Analyst disposition panel — always shown for non-skip decisions */}
        {d && d.decision !== "skip" && (
          <div className="border-t border-gray-100 px-6 py-3 bg-gray-50">
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">Analyst disposition</p>
            <div className="flex flex-wrap items-center gap-2">
              {(["true_positive", "false_positive", "inconclusive"] as const).map((disp) => {
                const active = d.disposition === disp;
                const styles: Record<string, string> = {
                  true_positive:  active ? "bg-emerald-600 text-white border-emerald-600" : "border-gray-300 text-gray-600 hover:bg-emerald-50 hover:border-emerald-400",
                  false_positive: active ? "bg-red-600 text-white border-red-600"         : "border-gray-300 text-gray-600 hover:bg-red-50 hover:border-red-400",
                  inconclusive:   active ? "bg-yellow-500 text-white border-yellow-500"   : "border-gray-300 text-gray-600 hover:bg-yellow-50 hover:border-yellow-400",
                };
                const labels: Record<string, string> = {
                  true_positive: "True Positive", false_positive: "False Positive", inconclusive: "Inconclusive",
                };
                return (
                  <button
                    key={disp}
                    onClick={() => dispositionMut.mutate({ disp })}
                    disabled={dispositionMut.isPending}
                    className={`rounded-md border px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${styles[disp]}`}
                  >
                    {labels[disp]}
                  </button>
                );
              })}
              <input
                type="text"
                placeholder="Optional note…"
                value={dispositionNote}
                onChange={(e) => setDispositionNote(e.target.value)}
                className="ml-1 flex-1 min-w-[160px] rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
            </div>
          </div>
        )}

        {/* Investigation notes */}
        {/* Tags section */}
        {d && (
          <div className="border-t border-gray-100 px-6 py-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">Tags</p>
            <div className="flex flex-wrap gap-1 mb-2">
              {(d.tags ?? []).map((tag) => (
                <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-indigo-50 border border-indigo-200 pl-2 pr-1 py-0.5 text-xs text-indigo-700">
                  #{tag}
                  <button
                    onClick={() => removeTagMut.mutate(tag)}
                    disabled={removeTagMut.isPending}
                    className="rounded-full p-0.5 hover:bg-indigo-200 disabled:opacity-40"
                    title={`Remove tag #${tag}`}
                  >
                    <svg className="h-2.5 w-2.5" viewBox="0 0 20 20" fill="currentColor">
                      <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"/>
                    </svg>
                  </button>
                </span>
              ))}
              {(d.tags ?? []).length === 0 && <span className="text-xs text-gray-400">No tags.</span>}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && tagInput.trim()) { addTagMut.mutate(tagInput.trim().toLowerCase()); } }}
                placeholder="Add tag…"
                className="flex-1 rounded-md border border-gray-300 px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
              />
              <button
                onClick={() => { if (tagInput.trim()) addTagMut.mutate(tagInput.trim().toLowerCase()); }}
                disabled={!tagInput.trim() || addTagMut.isPending}
                className="shrink-0 rounded-md bg-indigo-600 px-2 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
              >
                Add
              </button>
            </div>
          </div>
        )}

        {d && (
          <div className="border-t border-gray-100 px-6 py-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">Investigation notes</p>
            {(d.investigation_notes ?? []).length > 0 && (
              <div className="mb-2 space-y-1.5 max-h-40 overflow-y-auto">
                {(d.investigation_notes ?? []).map((n, i) => (
                  <div key={i} className="rounded-md bg-gray-50 border border-gray-100 px-3 py-2 text-xs">
                    <p className="text-gray-800 whitespace-pre-wrap break-words">{n.text}</p>
                    <p className="mt-0.5 text-gray-400">
                      {n.by ? `${n.by} · ` : ""}{fmtTime(n.at)}
                    </p>
                  </div>
                ))}
              </div>
            )}
            {(d.investigation_notes ?? []).length === 0 && (
              <p className="text-xs text-gray-400 mb-2">No notes yet.</p>
            )}
            <div className="flex gap-2">
              <textarea
                rows={2}
                placeholder="Add an investigation note…"
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                className="flex-1 rounded-md border border-gray-300 px-2 py-1.5 text-xs text-gray-700 placeholder-gray-400 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
              />
              <button
                onClick={() => { if (noteText.trim()) noteMut.mutate(); }}
                disabled={!noteText.trim() || noteMut.isPending}
                className="shrink-0 self-end rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40"
              >
                {noteMut.isPending ? "…" : "Add"}
              </button>
            </div>
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

      {/* Sticky footer — always visible at the bottom of the drawer */}
      {d && (canCancel || canApprove || canResolve || canUnisolate || canUnrestrict || canForceInvestigate || canExecuteNow || canEnableSignIn) && (
        <div className="shrink-0 border-t border-gray-200 bg-white px-6 py-4 space-y-3">
          {(canForceInvestigate || canUnisolate || canUnrestrict || canEnableSignIn) && (
            <div>
              <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Manual Actions</p>
              <div className="flex flex-wrap gap-2">
                {canForceInvestigate && (
                  <button
                    onClick={() => {
                      if (confirm("Manually trigger an MDE investigation on the device(s) in this alert?")) {
                        onForceInvestigate(d.decision_id);
                        onClose();
                      }
                    }}
                    className="rounded-lg border border-violet-300 bg-violet-50 px-3 py-1.5 text-sm text-violet-700 hover:bg-violet-100"
                  >
                    Force Investigate
                  </button>
                )}
                {canUnisolate && (
                  <button
                    onClick={() => {
                      if (confirm("Manually release device(s) from network isolation?")) {
                        onUnisolate(d.decision_id);
                        onClose();
                      }
                    }}
                    className="rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
                  >
                    Release Isolation
                  </button>
                )}
                {canUnrestrict && (
                  <button
                    onClick={() => {
                      if (confirm("Manually remove the app execution restriction from device(s)?")) {
                        onUnrestrict(d.decision_id);
                        onClose();
                      }
                    }}
                    className="rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
                  >
                    Remove App Restriction
                  </button>
                )}
                {canEnableSignIn && (
                  <button
                    onClick={() => {
                      if (confirm("Manually re-enable sign-in for the user(s) in this alert?")) {
                        onEnableSignIn(d.decision_id);
                        onClose();
                      }
                    }}
                    className="rounded-lg border border-slate-300 bg-slate-50 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
                  >
                    Enable Sign-in
                  </button>
                )}
              </div>
            </div>
          )}
          {(canCancel || canApprove || canResolve || canExecuteNow) && (
            <div className="flex justify-end gap-3">
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
              {canResolve && (
                <button
                  onClick={() => { onResolve(d.decision_id); onClose(); }}
                  className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-100"
                >
                  Mark Resolved
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
          {/* Investigate with Copilot — always available for non-skip decisions */}
          {d.decision !== "skip" && (
            <div className="mt-2 flex justify-start">
              <a
                href={`/security/copilot?decisionId=${d.decision_id}`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-sky-300 bg-sky-50 px-4 py-2 text-sm font-medium text-sky-700 hover:bg-sky-100"
              >
                <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3 6.5 6.2v6.6L12 16l5.5-3.2V6.2L12 3Z" />
                  <path d="M12 8.2 9.2 9.8v3.4L12 14.8l2.8-1.6V9.8L12 8.2Z" />
                </svg>
                Investigate with Copilot
              </a>
            </div>
          )}
        </div>
      )}
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
  onResolve,
  onUnisolate,
  onUnrestrict,
  onForceInvestigate,
  onExecuteNow,
  onEnableSignIn,
  onOpenDetail,
  onOpenEntityTimeline,
}: {
  d: DefenderAgentDecision;
  isAdmin: boolean;
  onCancel: (id: string) => void;
  onApprove: (id: string) => void;
  onResolve: (id: string) => void;
  onUnisolate: (id: string) => void;
  onUnrestrict: (id: string) => void;
  onForceInvestigate: (id: string) => void;
  onExecuteNow: (id: string) => void;
  onEnableSignIn: (id: string) => void;
  onOpenDetail: (id: string) => void;
  onOpenEntityTimeline: (entityId: string, entityName: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const tier = tierLabel(d);
  const status = decisionStatus(d);

  // Primary actions
  const canCancel           = d.decision === "queue" && !d.cancelled && !d.job_ids.length;
  const canApprove          = !d.human_approved && !d.cancelled && isAdmin;
  const canResolve          = !d.resolved;
  const canExecuteNow       = d.decision === "queue" && !d.cancelled && !d.job_ids.length && isAdmin;
  const canForceInvestigate = d.entities.some(e => e.type === "device") && isAdmin;
  const canUnisolate        = d.entities.some(e => e.type === "device") && !d.cancelled && isAdmin;
  const canUnrestrict       = d.entities.some(e => e.type === "device") && !d.cancelled && isAdmin;
  const canEnableSignIn     = d.entities.some(e => e.type === "user" || e.type === "account") && !d.cancelled && isAdmin;

  const hasAnyAction = canCancel || canApprove || canResolve || canExecuteNow || canForceInvestigate || canUnisolate || canUnrestrict || canEnableSignIn;

  return (
    <>
      <tr
        className={`hover:bg-gray-50 cursor-pointer ${expanded ? "bg-blue-50/40" : ""}`}
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{fmtTime(d.executed_at)}</td>
        <td className="px-3 py-2 max-w-xs">
          <div className="text-sm font-medium text-gray-800 truncate" title={d.alert_title}>
            {d.alert_title || d.alert_id}
          </div>
          {d.ai_narrative && (
            <div className="text-xs text-blue-600 italic truncate mt-0.5" title={d.ai_narrative}>{d.ai_narrative}</div>
          )}
          {d.reason && <div className="text-xs text-gray-400 truncate" title={d.reason}>{d.reason}</div>}
          <EntityChips
            entities={d.entities}
            onEntityClick={onOpenEntityTimeline}
            watchlistedIds={d.watchlisted_entities?.length ? new Set(d.watchlisted_entities.map(w => w.entity_id?.toLowerCase())) : undefined}
          />
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
          {(d.tags ?? []).length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {(d.tags ?? []).map((tag) => (
                <span key={tag} className="inline-block rounded-full bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 text-xs text-indigo-700">
                  #{tag}
                </span>
              ))}
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
          {(d.confidence_score ?? 0) > 0 && (
            <span className={`ml-1 inline-block rounded-full px-1.5 py-0.5 text-xs font-medium ${confidenceBadge(d.confidence_score ?? 0).color}`}
              title={`Rule confidence: ${d.confidence_score}%`}>
              {d.confidence_score}%
            </span>
          )}
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
          {dispositionBadge(d.disposition) && (
            <span className={`mt-1 inline-block rounded-full px-1.5 py-0.5 text-[10px] font-medium ${dispositionBadge(d.disposition)!.color}`}>
              {dispositionBadge(d.disposition)!.label}
            </span>
          )}
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-right">
          <svg className={`inline h-4 w-4 text-gray-400 transition-transform ${expanded ? "rotate-180" : ""}`} viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z" clipRule="evenodd"/>
          </svg>
        </td>
      </tr>

      {/* Inline action panel */}
      {expanded && (
        <tr className="bg-blue-50/30">
          <td colSpan={8} className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
            <div className="flex flex-wrap items-center gap-2">
              {/* Primary actions */}
              {canExecuteNow && (
                <button
                  onClick={() => { onExecuteNow(d.decision_id); setExpanded(false); }}
                  className="rounded border border-green-300 bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700 hover:bg-green-100"
                >
                  ⚡ Execute Now
                </button>
              )}
              {canCancel && (
                <button
                  onClick={() => { onCancel(d.decision_id); setExpanded(false); }}
                  className="rounded border border-amber-300 bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 hover:bg-amber-100"
                >
                  ✕ Cancel
                </button>
              )}
              {canApprove && (
                <button
                  onClick={() => { onApprove(d.decision_id); setExpanded(false); }}
                  className="rounded border border-blue-300 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
                >
                  ✓ Approve & Execute
                </button>
              )}
              {canResolve && (
                <button
                  onClick={() => { onResolve(d.decision_id); setExpanded(false); }}
                  className="rounded border border-emerald-300 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
                >
                  ✓ Mark Resolved
                </button>
              )}
              {canForceInvestigate && (
                <button
                  onClick={() => { onForceInvestigate(d.decision_id); setExpanded(false); }}
                  className="rounded border border-purple-300 bg-purple-50 px-2.5 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100"
                >
                  🔍 Force Investigate
                </button>
              )}

              {/* Undo / reversal actions */}
              {canEnableSignIn && (
                <>
                  {(canCancel || canApprove || canExecuteNow || canForceInvestigate) && (
                    <span className="text-gray-300 select-none">|</span>
                  )}
                  <button
                    onClick={() => { onEnableSignIn(d.decision_id); setExpanded(false); }}
                    className="rounded border border-slate-300 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                  >
                    ↩ Enable Sign-in
                  </button>
                </>
              )}
              {canUnisolate && (
                <>
                  {(canCancel || canApprove || canExecuteNow || canForceInvestigate) && (
                    <span className="text-gray-300 select-none">|</span>
                  )}
                  <button
                    onClick={() => { onUnisolate(d.decision_id); setExpanded(false); }}
                    className="rounded border border-slate-300 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                  >
                    ↩ Release Isolation
                  </button>
                </>
              )}
              {canUnrestrict && (
                <button
                  onClick={() => { onUnrestrict(d.decision_id); setExpanded(false); }}
                  className="rounded border border-slate-300 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                >
                  ↩ Remove App Restriction
                </button>
              )}

              {!hasAnyAction && (
                <span className="text-xs text-gray-400 italic">No actions available for this decision</span>
              )}

              {/* Spacer + details/investigate links */}
              <span className="ml-auto flex items-center gap-2">
                {d.decision !== "skip" && (
                  <a
                    href={`/security/copilot?decisionId=${d.decision_id}`}
                    onClick={(e) => { e.stopPropagation(); setExpanded(false); }}
                    className="rounded border border-sky-300 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100"
                  >
                    🔬 Investigate
                  </a>
                )}
                <button
                  onClick={() => { setExpanded(false); onOpenDetail(d.decision_id); }}
                  className="rounded border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
                >
                  Details →
                </button>
              </span>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Phase 17: Built-in rule management panel
// ---------------------------------------------------------------------------

function RulesPanel() {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const rulesQuery = useQuery({
    queryKey: ["defender-agent-builtin-rules"],
    queryFn: () => api.listDefenderAgentBuiltinRules(),
    enabled: expanded,
  });
  const updateRuleMut = useMutation({
    mutationFn: ({ ruleId, disabled, confidence_score }: { ruleId: string; disabled: boolean; confidence_score?: number | null }) =>
      api.updateDefenderAgentRule(ruleId, { disabled, confidence_score }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-builtin-rules"] }),
  });

  return (
    <div className="mt-6 rounded-xl border border-gray-200 bg-white shadow">
      <button
        className="flex w-full items-center justify-between px-5 py-4 border-b border-gray-200 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <svg className={`h-4 w-4 transition-transform text-gray-400 ${expanded ? "rotate-90" : ""}`} viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z" clipRule="evenodd"/>
          </svg>
          Built-in Detection Rules
        </h2>
        <span className="text-xs text-gray-400">Disable or adjust confidence scores for built-in classification rules</span>
      </button>
      {expanded && (
        <div className="overflow-x-auto">
          {rulesQuery.isLoading && (
            <div className="flex items-center justify-center py-8">
              <div className="h-5 w-5 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
            </div>
          )}
          {rulesQuery.data && (
            <table className="min-w-full text-xs">
              <thead className="bg-gray-50">
                <tr>
                  {["ID", "Tier", "Action", "Confidence", "Keywords", "Status", ""].map((h) => (
                    <th key={h} className="px-3 py-2 text-left font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {rulesQuery.data.map((rule) => (
                  <tr key={rule.rule_id} className={`hover:bg-gray-50 ${rule.disabled ? "opacity-50" : ""}`}>
                    <td className="px-3 py-2 font-mono text-gray-500">{rule.rule_id}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${rule.tier === 1 ? "bg-green-100 text-green-700" : rule.tier === 2 ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700"}`}>
                        T{rule.tier}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-700">{rule.action_type || rule.action_types[0] || "—"}</td>
                    <td className="px-3 py-2">
                      {rule.override_confidence != null ? (
                        <span className="inline-flex items-center gap-1">
                          <span className="line-through text-gray-400">{rule.confidence_score}%</span>
                          <span className="text-blue-600 font-medium">{rule.override_confidence}%</span>
                        </span>
                      ) : (
                        <span className="text-gray-600">{rule.confidence_score}%</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-gray-500 max-w-xs truncate" title={[...rule.title_keywords, ...rule.category_keywords].join(", ") || rule.reason}>
                      {[...rule.title_keywords, ...rule.category_keywords].slice(0, 3).join(", ") || <span className="italic text-gray-300">catch-all</span>}
                    </td>
                    <td className="px-3 py-2">
                      {rule.disabled ? (
                        <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-700">Disabled</span>
                      ) : (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">Active</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <button
                        onClick={() => updateRuleMut.mutate({ ruleId: rule.rule_id, disabled: !rule.disabled, confidence_score: rule.override_confidence })}
                        disabled={updateRuleMut.isPending}
                        className={`mr-2 text-xs rounded px-2 py-1 ${rule.disabled ? "bg-emerald-50 text-emerald-700 hover:bg-emerald-100" : "bg-red-50 text-red-600 hover:bg-red-100"} disabled:opacity-40`}
                      >
                        {rule.disabled ? "Enable" : "Disable"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Phase 18: Custom detection rules panel
// ---------------------------------------------------------------------------

function CustomRulesPanel() {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [responseType, setResponseType] = useState<"single" | "playbook">("single");
  const [form, setForm] = useState<Partial<DefenderAgentCustomRule>>({
    name: "",
    match_field: "title",
    match_value: "",
    match_mode: "contains",
    tier: 3,
    action_type: "start_investigation",
    confidence_score: 50,
    playbook_id: null,
  });

  const rulesQuery = useQuery({
    queryKey: ["defender-agent-custom-rules"],
    queryFn: () => api.listDefenderAgentCustomRules(),
    enabled: expanded,
  });
  const playbooksQuery = useQuery<DefenderAgentPlaybook[]>({
    queryKey: ["defender-playbooks"],
    queryFn: () => api.listDefenderAgentPlaybooks(),
    enabled: expanded,
    staleTime: 30_000,
  });
  const createMut = useMutation({
    mutationFn: (body: Omit<DefenderAgentCustomRule, "id" | "enabled" | "created_by" | "created_at" | "playbook_name">) =>
      api.createDefenderAgentCustomRule(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["defender-agent-custom-rules"] });
      setForm({ name: "", match_field: "title", match_value: "", match_mode: "contains", tier: 3, action_type: "start_investigation", confidence_score: 50, playbook_id: null });
      setResponseType("single");
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteDefenderAgentCustomRule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-custom-rules"] }),
  });
  const toggleMut = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.toggleDefenderAgentCustomRule(id, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-custom-rules"] }),
  });

  return (
    <div className="mt-6 rounded-xl border border-gray-200 bg-white shadow">
      <button
        className="flex w-full items-center justify-between px-5 py-4 border-b border-gray-200 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <svg className={`h-4 w-4 transition-transform text-gray-400 ${expanded ? "rotate-90" : ""}`} viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z" clipRule="evenodd"/>
          </svg>
          Custom Detection Rules
        </h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">Add keyword / field matching rules beyond the built-in ruleset</span>
          <Link
            to="/security/playbooks"
            onClick={e => e.stopPropagation()}
            className="rounded border border-indigo-200 bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
          >
            Manage Playbooks →
          </Link>
        </div>
      </button>
      {expanded && (
        <div>
          {/* Add form */}
          <div className="border-b border-gray-100 bg-gray-50 px-5 py-4">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">New custom rule</p>
            <div className="flex flex-wrap gap-3 items-end">
              <label className="block">
                <span className="text-xs text-gray-500">Name (optional)</span>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm w-40"
                  placeholder="e.g. Phishing catch"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Match field</span>
                <select value={form.match_field} onChange={(e) => setForm((f) => ({ ...f, match_field: e.target.value as DefenderAgentCustomRule["match_field"] }))}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm">
                  <option value="title">Alert title</option>
                  <option value="category">Category</option>
                  <option value="service_source">Service source</option>
                  <option value="severity">Severity</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Mode</span>
                <select value={form.match_mode} onChange={(e) => setForm((f) => ({ ...f, match_mode: e.target.value as DefenderAgentCustomRule["match_mode"] }))}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm">
                  <option value="contains">Contains</option>
                  <option value="exact">Exact</option>
                  <option value="startswith">Starts with</option>
                </select>
              </label>
              <label className="block flex-1 min-w-[140px]">
                <span className="text-xs text-gray-500">Match value *</span>
                <input
                  type="text"
                  value={form.match_value}
                  onChange={(e) => setForm((f) => ({ ...f, match_value: e.target.value }))}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                  placeholder="e.g. phishing"
                />
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Tier</span>
                <select value={form.tier} onChange={(e) => setForm((f) => ({ ...f, tier: Number(e.target.value) }))}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm">
                  <option value={1}>T1 Immediate</option>
                  <option value={2}>T2 Queued</option>
                  <option value={3}>T3 Recommend</option>
                </select>
              </label>
              <label className="block">
                <span className="text-xs text-gray-500">Response type</span>
                <select
                  value={responseType}
                  onChange={e => { setResponseType(e.target.value as "single" | "playbook"); setForm(f => ({ ...f, playbook_id: null })); }}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                >
                  <option value="single">Single action</option>
                  <option value="playbook">Playbook</option>
                </select>
              </label>
              {responseType === "single" ? (
                <label className="block">
                  <span className="text-xs text-gray-500">Action type</span>
                  <input
                    type="text"
                    value={form.action_type}
                    onChange={(e) => setForm((f) => ({ ...f, action_type: e.target.value }))}
                    className="mt-1 block w-40 rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                    placeholder="start_investigation"
                  />
                </label>
              ) : (
                <label className="block">
                  <span className="text-xs text-gray-500">Playbook</span>
                  <select
                    value={form.playbook_id ?? ""}
                    onChange={e => setForm(f => ({ ...f, playbook_id: e.target.value || null }))}
                    className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                  >
                    <option value="">— select —</option>
                    {(playbooksQuery.data ?? []).filter(p => p.enabled).map(p => (
                      <option key={p.id} value={p.id}>{p.name} ({p.actions.length} actions)</option>
                    ))}
                  </select>
                  {(playbooksQuery.data ?? []).filter(p => p.enabled).length === 0 && (
                    <p className="mt-1 text-xs text-amber-600">No enabled playbooks — <Link to="/security/playbooks" className="underline">create one first</Link>.</p>
                  )}
                </label>
              )}
              <label className="block">
                <span className="text-xs text-gray-500">Confidence</span>
                <input type="number" min={0} max={100} value={form.confidence_score}
                  onChange={(e) => setForm((f) => ({ ...f, confidence_score: Math.max(0, Math.min(100, parseInt(e.target.value) || 0)) }))}
                  className="mt-1 block w-20 rounded-md border border-gray-300 px-2 py-1.5 text-sm" />
              </label>
              <button
                onClick={() => {
                  if (!form.match_value?.trim()) return;
                  if (responseType === "playbook" && !form.playbook_id) return;
                  createMut.mutate(form as Omit<DefenderAgentCustomRule, "id" | "enabled" | "created_by" | "created_at" | "playbook_name">);
                }}
                disabled={!form.match_value?.trim() || (responseType === "playbook" && !form.playbook_id) || createMut.isPending}
                className="self-end rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
              >
                {createMut.isPending ? "Adding…" : "Add rule"}
              </button>
            </div>
          </div>
          {/* Rules table */}
          {rulesQuery.isLoading ? (
            <div className="flex items-center justify-center py-6">
              <div className="h-5 w-5 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
            </div>
          ) : (rulesQuery.data?.length ?? 0) === 0 ? (
            <p className="py-6 text-center text-sm text-gray-400">No custom rules. Add one above.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    {["Name", "Match", "Tier", "Action", "Confidence", "Status", ""].map((h) => (
                      <th key={h} className="px-3 py-2 text-left font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {rulesQuery.data!.map((cr) => (
                    <tr key={cr.id} className={`hover:bg-gray-50 ${!cr.enabled ? "opacity-50" : ""}`}>
                      <td className="px-3 py-2 text-gray-700">{cr.name || <span className="italic text-gray-400">unnamed</span>}</td>
                      <td className="px-3 py-2">
                        <span className="text-gray-500">{cr.match_field}</span>
                        <span className="mx-1 text-gray-300">·</span>
                        <span className="text-gray-400">{cr.match_mode}</span>
                        <span className="mx-1 text-gray-300">·</span>
                        <span className="font-mono text-gray-800">{cr.match_value}</span>
                      </td>
                      <td className="px-3 py-2">
                        <span className={`rounded-full px-1.5 py-0.5 text-xs font-medium ${cr.tier === 1 ? "bg-green-100 text-green-700" : cr.tier === 2 ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700"}`}>
                          T{cr.tier}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-gray-600">
                        {cr.playbook_id ? (
                          <span className="inline-flex items-center gap-1">
                            <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-xs font-medium text-indigo-700">playbook</span>
                            <Link to="/security/playbooks" className="text-indigo-600 hover:underline">{cr.playbook_name || cr.playbook_id}</Link>
                          </span>
                        ) : cr.action_type}
                      </td>
                      <td className="px-3 py-2 text-gray-600">{cr.confidence_score}%</td>
                      <td className="px-3 py-2">
                        {cr.enabled
                          ? <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">Active</span>
                          : <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">Disabled</span>
                        }
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <button
                          onClick={() => toggleMut.mutate({ id: cr.id, enabled: !cr.enabled })}
                          disabled={toggleMut.isPending}
                          className={`mr-2 text-xs rounded px-2 py-1 ${cr.enabled ? "bg-gray-50 text-gray-600 hover:bg-gray-100" : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"} disabled:opacity-40`}
                        >
                          {cr.enabled ? "Disable" : "Enable"}
                        </button>
                        <button
                          onClick={() => { if (confirm(`Delete custom rule "${cr.name || cr.match_value}"?`)) deleteMut.mutate(cr.id); }}
                          disabled={deleteMut.isPending}
                          className="text-xs text-red-500 hover:text-red-700 disabled:opacity-40"
                        >
                          Delete
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function AzureSecurityAgentPage() {
  const queryClient = useQueryClient();
  const [showConfig, setShowConfig] = useState(false);
  const [showFaq, setShowFaq] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [decisionFilter, setDecisionFilter] = useState<string>("");
  const [mitreFilter, setMitreFilter] = useState<string>("");
  const [runningNow, setRunningNow] = useState(false);
  const [selectedDecisionId, setSelectedDecisionId] = useState<string | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<{ id: string; name: string } | null>(null);
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

  const dispositionStatsQuery = useQuery({
    queryKey: ["defender-agent-disposition-stats"],
    queryFn: () => api.getDefenderAgentDispositionStats(),
    staleTime: 60_000,
  });

  const [metricsDays, setMetricsDays] = useState(30);
  const [showMetrics, setShowMetrics] = useState(false);
  const metricsQuery = useQuery({
    queryKey: ["defender-agent-metrics", metricsDays],
    queryFn: () => api.getDefenderAgentMetrics(metricsDays),
    staleTime: 120_000,
    enabled: showMetrics,
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

  const resolveMutation = useMutation({
    mutationFn: (id: string) => api.resolveDefenderAgentDecision(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }),
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

  const enableSignInMutation = useMutation({
    mutationFn: (id: string) => api.enableSignInDecision(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }),
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

  const watchlistQuery = useQuery({
    queryKey: ["defender-agent-watchlist"],
    queryFn: () => api.listWatchlist(),
    staleTime: 60_000,
  });

  const addWatchlistMutation = useMutation({
    mutationFn: (body: { entity_type: string; entity_id: string; entity_name: string; reason: string; boost_tier: boolean }) =>
      api.addWatchlistEntry(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-watchlist"] }),
  });

  const removeWatchlistMutation = useMutation({
    mutationFn: (id: string) => api.removeWatchlistEntry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["defender-agent-watchlist"] }),
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
  const watchlistEntries = watchlistQuery.data?.entries ?? [];

  const [suppressionForm, setSuppressionForm] = useState<{
    suppression_type: DefenderSuppressionType;
    value: string;
    reason: string;
    expires_at: string;
  }>({ suppression_type: "entity_user", value: "", reason: "", expires_at: "" });

  const [watchlistForm, setWatchlistForm] = useState({
    entity_type: "user" as "user" | "device",
    entity_id: "",
    entity_name: "",
    reason: "",
    boost_tier: false,
  });

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
            onClick={() => setShowFaq(true)}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 shadow-sm"
            title="Open FAQ"
          >
            FAQ
          </button>
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
            <a
              href={api.exportDefenderAgentDecisions(30)}
              download
              className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
              title="Export last 30 days of decisions as CSV"
            >
              <svg className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 3a.75.75 0 0 1 .75.75v6.19l2.22-2.22a.75.75 0 1 1 1.06 1.06l-3.5 3.5a.75.75 0 0 1-1.06 0l-3.5-3.5a.75.75 0 0 1 1.06-1.06l2.22 2.22V3.75A.75.75 0 0 1 10 3Zm-5.25 12a.75.75 0 0 1 0-1.5h10.5a.75.75 0 0 1 0 1.5H4.75Z" clipRule="evenodd"/>
              </svg>
              Export CSV
            </a>
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

        {/* Disposition stats strip */}
        {dispositionStatsQuery.data && dispositionStatsQuery.data.reviewed > 0 && (
          <div className="border-b border-gray-100 bg-gray-50 px-5 py-2 flex flex-wrap items-center gap-4 text-xs">
            <span className="font-medium text-gray-600">Analyst coverage:</span>
            <span className="text-gray-500">{dispositionStatsQuery.data.reviewed}/{dispositionStatsQuery.data.total_actioned} reviewed</span>
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <span className="text-emerald-700 font-medium">{dispositionStatsQuery.data.true_positive} TP</span>
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-red-500" />
              <span className="text-red-700 font-medium">{dispositionStatsQuery.data.false_positive} FP</span>
              {dispositionStatsQuery.data.false_positive_rate > 0 && (
                <span className="text-gray-400">({(dispositionStatsQuery.data.false_positive_rate * 100).toFixed(0)}%)</span>
              )}
            </span>
            {dispositionStatsQuery.data.inconclusive > 0 && (
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-yellow-400" />
                <span className="text-yellow-700 font-medium">{dispositionStatsQuery.data.inconclusive} Inconclusive</span>
              </span>
            )}
          </div>
        )}

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
                      onResolve={(id) => resolveMutation.mutate(id)}
                      onUnisolate={(id) => unisolateMutation.mutate(id)}
                      onUnrestrict={(id) => unrestrictMutation.mutate(id)}
                      onForceInvestigate={(id) => forceInvestigateMutation.mutate(id)}
                      onExecuteNow={(id) => executeNowMutation.mutate(id)}
                      onEnableSignIn={(id) => enableSignInMutation.mutate(id)}
                      onOpenDetail={setSelectedDecisionId}
                      onOpenEntityTimeline={(id, name) => setSelectedEntity({ id, name })}
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

      {/* Metrics dashboard */}
      <div className="rounded-lg bg-white shadow">
        <div className="border-b border-gray-200 px-5 py-4 flex items-center justify-between gap-3">
          <button
            className="flex items-center gap-2 text-lg font-semibold text-gray-900 hover:text-blue-600 transition-colors"
            onClick={() => setShowMetrics((v) => !v)}
          >
            <svg
              className={`h-4 w-4 transition-transform ${showMetrics ? "rotate-90" : ""}`}
              viewBox="0 0 20 20" fill="currentColor"
            >
              <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z" clipRule="evenodd"/>
            </svg>
            Detection Metrics
          </button>
          {showMetrics && (
            <div className="flex items-center gap-1">
              {[7, 14, 30, 90].map((d) => (
                <button
                  key={d}
                  onClick={() => setMetricsDays(d)}
                  className={`rounded px-2 py-0.5 text-xs font-medium ${metricsDays === d ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
                >
                  {d}d
                </button>
              ))}
            </div>
          )}
        </div>
        {showMetrics && (
          <div className="px-5 py-4">
            {metricsQuery.isLoading && (
              <div className="flex items-center justify-center py-8">
                <div className="h-5 w-5 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
              </div>
            )}
            {metricsQuery.data && !metricsQuery.isLoading && (
              <MetricsDashboard metrics={metricsQuery.data} />
            )}
            {metricsQuery.isError && (
              <p className="text-sm text-red-500 py-4 text-center">Failed to load metrics.</p>
            )}
          </div>
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

      {/* Watchlist panel (admin write, all read) */}
      <div className="rounded-lg bg-white shadow">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            Entity Watchlist
            {watchlistEntries.length > 0 && (
              <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                {watchlistEntries.length} active
              </span>
            )}
          </h2>
          <span className="text-xs text-gray-400">Watchlisted entities get visual callouts; boost_tier escalates decisions one tier</span>
        </div>

        {/* Add form (admin only) */}
        {isAdmin && (
          <div className="px-5 py-4 border-b border-gray-100 bg-gray-50">
            <div className="flex flex-wrap gap-2 items-end">
              <label className="block">
                <span className="text-xs text-gray-500">Type</span>
                <select
                  value={watchlistForm.entity_type}
                  onChange={(e) => setWatchlistForm((p) => ({ ...p, entity_type: e.target.value as "user" | "device" }))}
                  className="mt-1 block rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                >
                  <option value="user">User</option>
                  <option value="device">Device</option>
                </select>
              </label>
              <label className="block flex-1 min-w-[160px]">
                <span className="text-xs text-gray-500">Entity ID / UPN</span>
                <input
                  type="text"
                  placeholder="e.g. alice@contoso.com"
                  value={watchlistForm.entity_id}
                  onChange={(e) => setWatchlistForm((p) => ({ ...p, entity_id: e.target.value }))}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                />
              </label>
              <label className="block flex-1 min-w-[120px]">
                <span className="text-xs text-gray-500">Display name (optional)</span>
                <input
                  type="text"
                  placeholder="Alice Smith"
                  value={watchlistForm.entity_name}
                  onChange={(e) => setWatchlistForm((p) => ({ ...p, entity_name: e.target.value }))}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                />
              </label>
              <label className="block flex-1 min-w-[120px]">
                <span className="text-xs text-gray-500">Reason</span>
                <input
                  type="text"
                  placeholder="VIP / Privileged account"
                  value={watchlistForm.reason}
                  onChange={(e) => setWatchlistForm((p) => ({ ...p, reason: e.target.value }))}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm"
                />
              </label>
              <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer self-end pb-1.5">
                <input
                  type="checkbox"
                  checked={watchlistForm.boost_tier}
                  onChange={(e) => setWatchlistForm((p) => ({ ...p, boost_tier: e.target.checked }))}
                  className="h-4 w-4 rounded border-gray-300 text-amber-600"
                />
                Boost tier
              </label>
              <button
                onClick={() => {
                  if (!watchlistForm.entity_id.trim()) return;
                  addWatchlistMutation.mutate(watchlistForm, {
                    onSuccess: () => setWatchlistForm({ entity_type: "user", entity_id: "", entity_name: "", reason: "", boost_tier: false }),
                  });
                }}
                disabled={!watchlistForm.entity_id.trim() || addWatchlistMutation.isPending}
                className="self-end rounded-md bg-amber-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-40"
              >
                {addWatchlistMutation.isPending ? "Adding…" : "Add"}
              </button>
            </div>
          </div>
        )}

        {/* Watchlist table */}
        {watchlistEntries.length === 0 ? (
          <p className="py-6 text-center text-sm text-gray-400">No watchlisted entities.</p>
        ) : (
          <table className="min-w-full divide-y divide-gray-100 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {["Type", "Entity", "Reason", "Boost tier", "Added by", ""].map((h) => (
                  <th key={h} className="px-4 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {watchlistEntries.map((w: DefenderAgentWatchlistEntry) => (
                <tr key={w.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-xs capitalize text-gray-600">{w.entity_type}</td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-1.5">
                      <svg className="h-3.5 w-3.5 text-amber-500 shrink-0" viewBox="0 0 16 16" fill="currentColor">
                        <path d="M8 1l1.8 3.6L14 5.3l-3 2.9.7 4.1L8 10.2l-3.7 2.1.7-4.1-3-2.9 4.2-.7L8 1Z"/>
                      </svg>
                      <span className="font-medium text-gray-800">{w.entity_name || w.entity_id}</span>
                    </div>
                    {w.entity_name && <div className="text-xs text-gray-400 pl-5">{w.entity_id}</div>}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">{w.reason || "—"}</td>
                  <td className="px-4 py-2 text-center">
                    {w.boost_tier ? (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">Yes</span>
                    ) : (
                      <span className="text-gray-400 text-xs">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-400">{w.created_by || "—"}</td>
                  <td className="px-4 py-2 text-right">
                    {isAdmin && (
                      <button
                        onClick={() => { if (confirm(`Remove ${w.entity_id} from watchlist?`)) removeWatchlistMutation.mutate(w.id); }}
                        className="text-xs text-red-500 hover:text-red-700"
                      >
                        Remove
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
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

      {/* Phase 17: Rule management panel (admin-only) */}
      {isAdmin && (
        <RulesPanel />
      )}

      {/* Phase 18: Custom detection rules panel (admin-only) */}
      {isAdmin && (
        <CustomRulesPanel />
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
          onEnableSignIn={(id) => { enableSignInMutation.mutate(id); queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }); }}
          onResolve={(id) => { resolveMutation.mutate(id); queryClient.invalidateQueries({ queryKey: ["defender-agent-decisions"] }); }}
          onSuppressEntity={(type, value) => {
            const reason = prompt(`Suppression reason for "${value}" (optional):`);
            createSuppressionMutation.mutate({ suppression_type: type, value, reason: reason ?? "" });
          }}
          onOpenEntityTimeline={(id, name) => {
            setSelectedDecisionId(null);
            setSelectedEntity({ id, name });
          }}
        />
      )}

      {/* Entity timeline drawer */}
      {selectedEntity && (
        <EntityTimelineDrawer
          entityId={selectedEntity.id}
          entityName={selectedEntity.name}
          onClose={() => setSelectedEntity(null)}
          onOpenDecision={(id) => {
            setSelectedEntity(null);
            setSelectedDecisionId(id);
          }}
        />
      )}

      {/* FAQ drawer */}
      {showFaq && <FaqDrawer onClose={() => setShowFaq(false)} />}
    </div>
  );
}
