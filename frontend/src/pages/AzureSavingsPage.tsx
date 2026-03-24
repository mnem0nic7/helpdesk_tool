import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  type AzureRecommendation,
  type AzureRecommendationActionContract,
  type AzureRecommendationActionContractItem,
  type AzureRecommendationActionEvent,
  type AzureRecommendationCreateTicketResponse,
  type AzureRecommendationRunSafeScriptResponse,
  type AzureRecommendationSendAlertResponse,
} from "../lib/api.ts";
import AzureSourceBadge from "../components/AzureSourceBadge.tsx";
import AzureSavingsHighlightsSection, { formatAzureCurrency } from "../components/AzureSavingsHighlightsSection.tsx";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type SavingsSortKey =
  | "title"
  | "category"
  | "subscription"
  | "resource_group"
  | "effort"
  | "risk"
  | "confidence"
  | "estimated_monthly_savings";

const effortOptions = ["low", "medium", "high"] as const;
const confidenceOptions = ["high", "medium", "low"] as const;
const actionStateOptions = [
  "none",
  "reviewed",
  "ticket_pending",
  "ticket_created",
  "alert_pending",
  "alert_sent",
  "exported",
  "script_pending",
  "script_executed",
] as const;

function formatActionState(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

function workflowBadgeClass(value: string, kind: "lifecycle" | "action"): string {
  const normalized = value.toLowerCase();
  if (kind === "lifecycle") {
    if (normalized === "open") return "bg-emerald-100 text-emerald-700";
    if (normalized === "dismissed") return "bg-amber-100 text-amber-700";
    return "bg-sky-100 text-sky-700";
  }
  if (normalized === "none") return "bg-slate-100 text-slate-600";
  if (normalized.includes("ticket")) return "bg-sky-100 text-sky-700";
  if (normalized.includes("alert")) return "bg-amber-100 text-amber-700";
  if (normalized.includes("script")) return "bg-purple-100 text-purple-700";
  return "bg-emerald-100 text-emerald-700";
}

function actionContractStatusClass(value: AzureRecommendationActionContractItem["status"]): string {
  if (value === "available") return "bg-emerald-100 text-emerald-700";
  if (value === "pending") return "bg-amber-100 text-amber-700";
  if (value === "completed") return "bg-sky-100 text-sky-700";
  if (value === "future") return "bg-violet-100 text-violet-700";
  return "bg-slate-100 text-slate-600";
}

function formatActionContractStatus(value: AzureRecommendationActionContractItem["status"]): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatCoverageWindow(start?: string | null, end?: string | null): string {
  if (!start || !end) return "";
  if (start === end) return start;
  return `${start} to ${end}`;
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

function toneBadgeClass(value: string, tone: "effort" | "risk" | "confidence"): string {
  const normalized = value.toLowerCase();
  if (tone === "confidence") {
    if (normalized === "high") return "bg-emerald-100 text-emerald-700";
    if (normalized === "medium") return "bg-amber-100 text-amber-700";
    return "bg-slate-100 text-slate-600";
  }
  if (normalized === "low") return "bg-emerald-100 text-emerald-700";
  if (normalized === "medium") return "bg-amber-100 text-amber-700";
  return "bg-rose-100 text-rose-700";
}

function ToneBadge({ label, value, tone }: { label: string; value: string; tone: "effort" | "risk" | "confidence" }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${toneBadgeClass(value, tone)}`}>
      {label}: {value}
    </span>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
        active
          ? "bg-sky-700 text-white"
          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
      }`}
    >
      {label}
    </button>
  );
}

function OpportunityDrawer({
  opportunity,
  actionContract,
  actionContractLoading,
  history,
  historyLoading,
  isAdmin,
  onDismiss,
  onReopen,
  onUpdateActionState,
  onCreateTicket,
  onSendAlert,
  onRunSafeScript,
  createTicketBusy,
  sendAlertBusy,
  runSafeScriptBusy,
  workflowBusy,
  workflowError,
  onClose,
}: {
  opportunity: AzureRecommendation | null;
  actionContract: AzureRecommendationActionContract | null;
  actionContractLoading: boolean;
  history: AzureRecommendationActionEvent[];
  historyLoading: boolean;
  isAdmin: boolean;
  onDismiss: (reason: string) => void;
  onReopen: (note: string) => void;
  onUpdateActionState: (actionState: string, note: string) => void;
  onCreateTicket: (projectKey: string, issueType: string, summary: string, note: string) => void;
  onSendAlert: (channel: string, teamsWebhookUrl: string, note: string) => void;
  onRunSafeScript: (hookKey: string, dryRun: boolean, note: string) => void;
  createTicketBusy: boolean;
  sendAlertBusy: boolean;
  runSafeScriptBusy: boolean;
  workflowBusy: boolean;
  workflowError: string;
  onClose: () => void;
}) {
  const [note, setNote] = useState("");
  const [actionState, setActionState] = useState("none");
  const [ticketProjectKey, setTicketProjectKey] = useState("");
  const [ticketIssueType, setTicketIssueType] = useState("");
  const [ticketSummary, setTicketSummary] = useState("");
  const [ticketNote, setTicketNote] = useState("");
  const [alertChannel, setAlertChannel] = useState("");
  const [alertWebhookUrl, setAlertWebhookUrl] = useState("");
  const [alertNote, setAlertNote] = useState("");
  const [scriptHookKey, setScriptHookKey] = useState("");
  const [scriptDryRun, setScriptDryRun] = useState(true);
  const [scriptNote, setScriptNote] = useState("");

  useEffect(() => {
    setNote("");
    setActionState(opportunity?.action_state || "none");
    setTicketProjectKey("");
    setTicketIssueType("");
    setTicketSummary(opportunity ? `[FinOps] ${opportunity.title}` : "");
    setTicketNote("");
    setAlertChannel("");
    setAlertWebhookUrl("");
    setAlertNote("");
    const safeScriptAction = actionContract?.actions.find((action) => action.action_type === "run_safe_script") ?? null;
    const firstHook = safeScriptAction?.options?.[0] ?? null;
    setScriptHookKey(firstHook?.key || "");
    setScriptDryRun(firstHook ? firstHook.default_dry_run !== false : true);
    setScriptNote("");
  }, [opportunity?.id, opportunity?.action_state, actionContract]);

  if (!opportunity) return null;

  const createTicketAction = actionContract?.actions.find((action) => action.action_type === "create_ticket") ?? null;
  const createTicketLatestEvent =
    createTicketAction && typeof createTicketAction.latest_event === "object" && createTicketAction.latest_event
      ? (createTicketAction.latest_event as Record<string, unknown>)
      : null;
  const createTicketLatestMetadata =
    createTicketLatestEvent && typeof createTicketLatestEvent.metadata === "object" && createTicketLatestEvent.metadata
      ? (createTicketLatestEvent.metadata as Record<string, unknown>)
      : null;
  const createTicketLatestUrl = typeof createTicketLatestMetadata?.ticket_url === "string" ? createTicketLatestMetadata.ticket_url : "";
  const createTicketLatestKey = typeof createTicketLatestMetadata?.ticket_key === "string" ? createTicketLatestMetadata.ticket_key : "";
  const createTicketDisabled = !isAdmin || workflowBusy || createTicketBusy || !createTicketAction?.can_execute;
  const sendAlertAction = actionContract?.actions.find((action) => action.action_type === "send_alert") ?? null;
  const sendAlertLatestEvent =
    sendAlertAction && typeof sendAlertAction.latest_event === "object" && sendAlertAction.latest_event
      ? (sendAlertAction.latest_event as Record<string, unknown>)
      : null;
  const sendAlertLatestMetadata =
    sendAlertLatestEvent && typeof sendAlertLatestEvent.metadata === "object" && sendAlertLatestEvent.metadata
      ? (sendAlertLatestEvent.metadata as Record<string, unknown>)
      : null;
  const sendAlertLatestChannel = typeof sendAlertLatestMetadata?.channel === "string" ? sendAlertLatestMetadata.channel : "";
  const sendAlertDisabled = !isAdmin || workflowBusy || sendAlertBusy || !sendAlertAction?.can_execute;
  const safeScriptAction = actionContract?.actions.find((action) => action.action_type === "run_safe_script") ?? null;
  const safeScriptLatestEvent =
    safeScriptAction && typeof safeScriptAction.latest_event === "object" && safeScriptAction.latest_event
      ? (safeScriptAction.latest_event as Record<string, unknown>)
      : null;
  const safeScriptLatestMetadata =
    safeScriptLatestEvent && typeof safeScriptLatestEvent.metadata === "object" && safeScriptLatestEvent.metadata
      ? (safeScriptLatestEvent.metadata as Record<string, unknown>)
      : null;
  const selectedHookOption = safeScriptAction?.options?.find((option) => option.key === scriptHookKey) ?? safeScriptAction?.options?.[0] ?? null;
  const safeScriptResolvedDryRun = selectedHookOption?.allow_apply ? scriptDryRun : true;
  const safeScriptDisabled =
    !isAdmin ||
    workflowBusy ||
    runSafeScriptBusy ||
    !safeScriptAction?.can_execute ||
    !(safeScriptAction?.options?.length);

  return (
    <aside className="fixed inset-y-0 right-0 z-30 w-full max-w-2xl overflow-y-auto border-l border-slate-200 bg-white shadow-2xl">
      <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-slate-200 bg-white px-6 py-5">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{opportunity.category}</div>
          <h2 className="mt-1 text-2xl font-semibold text-slate-900">{opportunity.title}</h2>
          <p className="mt-2 text-sm text-slate-600">{opportunity.summary}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
        >
          Close
        </button>
      </div>

      <div className="space-y-6 px-6 py-6">
        <div className="grid gap-4 md:grid-cols-3">
          <StatCard
            label="Estimated Savings"
            value={opportunity.quantified ? formatAzureCurrency(opportunity.estimated_monthly_savings, opportunity.currency) : "Unquantified"}
            tone={opportunity.quantified ? "text-emerald-700" : "text-slate-900"}
          />
          <StatCard
            label="Current Monthly Cost"
            value={formatAzureCurrency(opportunity.current_monthly_cost, opportunity.currency)}
          />
          <StatCard
            label="Scope"
            value={opportunity.resource_name || opportunity.resource_type || "Tenant-wide"}
            sub={opportunity.subscription_name || opportunity.subscription_id || undefined}
          />
        </div>

        <section className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Triage</div>
          <div className="mt-3 flex flex-wrap gap-2">
            <ToneBadge label="Effort" value={opportunity.effort} tone="effort" />
            <ToneBadge label="Risk" value={opportunity.risk} tone="risk" />
            <ToneBadge label="Confidence" value={opportunity.confidence} tone="confidence" />
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${workflowBadgeClass(opportunity.lifecycle_status || "open", "lifecycle")}`}>
              Status: {formatActionState(opportunity.lifecycle_status || "open")}
            </span>
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${workflowBadgeClass(opportunity.action_state || "none", "action")}`}>
              Action: {formatActionState(opportunity.action_state || "none")}
            </span>
          </div>
          <div className="mt-4 grid gap-3 text-sm text-slate-600 md:grid-cols-2">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Estimate basis</div>
              <div className="mt-1">{opportunity.estimate_basis}</div>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Follow-up page</div>
              <div className="mt-1">
                <Link to={opportunity.follow_up_route} className="text-sky-700 hover:text-sky-800">
                  {opportunity.follow_up_route}
                </Link>
              </div>
            </div>
          </div>
          {opportunity.dismissed_reason ? (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <div className="text-xs font-semibold uppercase tracking-wide text-amber-700">Dismissed reason</div>
              <div className="mt-1">{opportunity.dismissed_reason}</div>
            </div>
          ) : null}
        </section>

        <section>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</div>
          <div className="mt-3 overflow-hidden rounded-2xl border border-slate-200">
            <table className="min-w-full text-left text-sm">
              <tbody>
                {opportunity.evidence.map((row, index) => (
                  <tr key={`${row.label}-${index}`} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/70"}>
                    <td className="w-48 px-4 py-3 font-medium text-slate-700">{row.label}</td>
                    <td className="px-4 py-3 text-slate-600">{row.value}</td>
                  </tr>
                ))}
                <tr className={opportunity.evidence.length % 2 === 0 ? "bg-white" : "bg-slate-50/70"}>
                  <td className="w-48 px-4 py-3 font-medium text-slate-700">Resource ID</td>
                  <td className="px-4 py-3 break-all text-slate-600">{opportunity.resource_id || "—"}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Recommended Steps</div>
          <ol className="mt-3 space-y-2 text-sm text-slate-700">
            {opportunity.recommended_steps.map((step, index) => (
              <li key={`${opportunity.id}-step-${index}`} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
                <span className="font-semibold text-slate-900">{index + 1}.</span> {step}
              </li>
            ))}
          </ol>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Action Contract</div>
          {actionContractLoading ? (
            <div className="mt-3 text-sm text-slate-500">Loading recommendation actions...</div>
          ) : (
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {(actionContract?.actions ?? []).map((action) => (
                <div key={action.action_type} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-medium text-slate-900">{action.label}</div>
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${actionContractStatusClass(action.status)}`}>
                      {formatActionContractStatus(action.status)}
                    </span>
                  </div>
                  <div className="mt-2 text-sm text-slate-600">{action.description}</div>
                  {action.blocked_reason ? (
                    <div className="mt-2 text-xs text-slate-500">{action.blocked_reason}</div>
                  ) : null}
                  <div className="mt-2 text-xs text-slate-500">
                    State binding: {action.pending_action_state || "—"} / {action.completed_action_state || "—"}
                  </div>
                  {action.note_placeholder ? (
                    <div className="mt-1 text-xs text-slate-400">{action.note_placeholder}</div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
          {createTicketAction ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="text-sm font-medium text-slate-900">Create Jira Follow-Up</div>
              <div className="mt-1 text-sm text-slate-600">
                Use the configured defaults or override the project, issue type, and summary before creating a linked Jira ticket.
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <input
                  value={ticketProjectKey}
                  onChange={(event) => setTicketProjectKey(event.target.value)}
                  placeholder="Project key (optional)"
                  disabled={createTicketDisabled}
                  className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
                />
                <input
                  value={ticketIssueType}
                  onChange={(event) => setTicketIssueType(event.target.value)}
                  placeholder="Issue type (optional)"
                  disabled={createTicketDisabled}
                  className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
                />
              </div>
              <input
                value={ticketSummary}
                onChange={(event) => setTicketSummary(event.target.value)}
                placeholder="Ticket summary"
                disabled={createTicketDisabled}
                className="mt-3 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
              />
              <textarea
                value={ticketNote}
                onChange={(event) => setTicketNote(event.target.value)}
                rows={3}
                placeholder={createTicketAction.note_placeholder || "Add an operator note for the Jira follow-up."}
                disabled={createTicketDisabled}
                className="mt-3 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
              />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => onCreateTicket(ticketProjectKey, ticketIssueType, ticketSummary, ticketNote)}
                  disabled={createTicketDisabled}
                  className="rounded-xl bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {createTicketBusy ? "Creating Jira Ticket..." : "Create Jira Ticket"}
                </button>
                {!isAdmin ? (
                  <span className="text-xs text-slate-500">Admin access is required for direct recommendation actions.</span>
                ) : null}
                {createTicketAction.blocked_reason ? (
                  <span className="text-xs text-slate-500">{createTicketAction.blocked_reason}</span>
                ) : null}
                {createTicketLatestUrl ? (
                  <a
                    href={createTicketLatestUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sm font-medium text-sky-700 hover:text-sky-800"
                  >
                    Open {createTicketLatestKey || "linked ticket"}
                  </a>
                ) : null}
              </div>
            </div>
          ) : null}
          {sendAlertAction ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="text-sm font-medium text-slate-900">Send Teams Alert</div>
              <div className="mt-1 text-sm text-slate-600">
                Send the recommendation to a Teams webhook using the configured default channel or an operator-supplied override.
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <input
                  value={alertChannel}
                  onChange={(event) => setAlertChannel(event.target.value)}
                  placeholder="Channel label (optional)"
                  disabled={sendAlertDisabled}
                  className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
                />
                <input
                  value={alertWebhookUrl}
                  onChange={(event) => setAlertWebhookUrl(event.target.value)}
                  placeholder="Teams webhook override (optional)"
                  disabled={sendAlertDisabled}
                  className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
                />
              </div>
              <textarea
                value={alertNote}
                onChange={(event) => setAlertNote(event.target.value)}
                rows={3}
                placeholder={sendAlertAction.note_placeholder || "Add an operator note for the Teams alert."}
                disabled={sendAlertDisabled}
                className="mt-3 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
              />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => onSendAlert(alertChannel, alertWebhookUrl, alertNote)}
                  disabled={sendAlertDisabled}
                  className="rounded-xl bg-amber-500 px-4 py-2 text-sm font-medium text-white hover:bg-amber-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {sendAlertBusy ? "Sending Teams Alert..." : "Send Teams Alert"}
                </button>
                {!isAdmin ? (
                  <span className="text-xs text-slate-500">Admin access is required for direct recommendation actions.</span>
                ) : null}
                {sendAlertAction.blocked_reason ? (
                  <span className="text-xs text-slate-500">{sendAlertAction.blocked_reason}</span>
                ) : null}
                {sendAlertLatestChannel ? (
                  <span className="text-xs text-slate-500">Last sent to {sendAlertLatestChannel}</span>
                ) : null}
              </div>
            </div>
          ) : null}
          {safeScriptAction ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="text-sm font-medium text-slate-900">Run Safe Remediation Hook</div>
              <div className="mt-1 text-sm text-slate-600">
                Execute an allowlisted remediation hook with structured recommendation input. Dry-run stays the default unless the selected hook explicitly permits apply mode.
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
                <select
                  value={scriptHookKey}
                  onChange={(event) => {
                    const nextHook = safeScriptAction.options.find((option) => option.key === event.target.value) ?? null;
                    setScriptHookKey(event.target.value);
                    setScriptDryRun(nextHook ? nextHook.default_dry_run !== false : true);
                  }}
                  disabled={safeScriptDisabled}
                  className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {(safeScriptAction.options ?? []).map((option) => (
                    <option key={option.key} value={option.key}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <label className="flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={safeScriptResolvedDryRun}
                    onChange={(event) => setScriptDryRun(event.target.checked)}
                    disabled={safeScriptDisabled || !selectedHookOption?.allow_apply}
                    className="h-4 w-4 rounded border-slate-300"
                  />
                  <span>Dry run</span>
                </label>
              </div>
              {selectedHookOption ? (
                <div className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                  <div className="font-medium text-slate-900">{selectedHookOption.label}</div>
                  {selectedHookOption.description ? <div className="mt-1">{selectedHookOption.description}</div> : null}
                  <div className="mt-2 text-xs text-slate-500">
                    {selectedHookOption.allow_apply
                      ? "Apply mode is permitted for this hook."
                      : "This hook is dry-run only."}
                  </div>
                </div>
              ) : null}
              <textarea
                value={scriptNote}
                onChange={(event) => setScriptNote(event.target.value)}
                rows={3}
                placeholder={safeScriptAction.note_placeholder || "Add an operator note for the safe remediation hook run."}
                disabled={safeScriptDisabled}
                className="mt-3 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
              />
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => onRunSafeScript(scriptHookKey, safeScriptResolvedDryRun, scriptNote)}
                  disabled={safeScriptDisabled}
                  className="rounded-xl bg-violet-700 px-4 py-2 text-sm font-medium text-white hover:bg-violet-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {runSafeScriptBusy ? "Running Safe Hook..." : safeScriptResolvedDryRun ? "Run Dry-Run Hook" : "Run Safe Hook"}
                </button>
                {!isAdmin ? (
                  <span className="text-xs text-slate-500">Admin access is required for direct recommendation actions.</span>
                ) : null}
                {safeScriptAction.blocked_reason ? (
                  <span className="text-xs text-slate-500">{safeScriptAction.blocked_reason}</span>
                ) : null}
                {typeof safeScriptLatestMetadata?.hook_label === "string" && safeScriptLatestMetadata.hook_label ? (
                  <span className="text-xs text-slate-500">Last hook: {safeScriptLatestMetadata.hook_label}</span>
                ) : null}
              </div>
              {typeof safeScriptLatestMetadata?.output_excerpt === "string" && safeScriptLatestMetadata.output_excerpt ? (
                <div className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                  {safeScriptLatestMetadata.output_excerpt}
                </div>
              ) : null}
            </div>
          ) : null}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Workflow</div>
          <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              placeholder="Add an operator note for dismiss, reopen, or action-state updates..."
              className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500"
            />
            <div className="space-y-3">
              <select
                value={actionState}
                onChange={(event) => setActionState(event.target.value)}
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 outline-none transition focus:border-sky-500"
                disabled={!isAdmin || workflowBusy}
              >
                {actionStateOptions.map((value) => (
                  <option key={value} value={value}>
                    {formatActionState(value)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => onUpdateActionState(actionState, note)}
                disabled={!isAdmin || workflowBusy}
                className="w-full rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Save Action State
              </button>
              {opportunity.lifecycle_status === "dismissed" ? (
                <button
                  type="button"
                  onClick={() => onReopen(note)}
                  disabled={!isAdmin || workflowBusy}
                  className="w-full rounded-xl border border-emerald-300 px-4 py-2 text-sm font-medium text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Reopen Recommendation
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => onDismiss(note)}
                  disabled={!isAdmin || workflowBusy}
                  className="w-full rounded-xl border border-amber-300 px-4 py-2 text-sm font-medium text-amber-700 hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Dismiss Recommendation
                </button>
              )}
            </div>
          </div>
          {!isAdmin ? (
            <div className="mt-3 text-xs text-slate-500">Admin access is required to change recommendation workflow state.</div>
          ) : null}
          {workflowError ? (
            <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{workflowError}</div>
          ) : null}
        </section>

        <section>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Action History</div>
          {historyLoading ? (
            <div className="mt-3 text-sm text-slate-500">Loading recommendation history...</div>
          ) : history.length === 0 ? (
            <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
              No workflow history has been recorded for this recommendation yet.
            </div>
          ) : (
            <div className="mt-3 space-y-3">
              {history.map((event) => (
                <div key={event.event_id} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-medium text-slate-900">
                      {formatActionState(event.action_type)} · {formatActionState(event.action_status)}
                    </div>
                    <div className="text-xs text-slate-400">{event.created_at}</div>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {event.actor_id ? `${event.actor_id} · ` : ""}{event.actor_type || "system"}
                  </div>
                  {typeof event.metadata.channel === "string" && event.metadata.channel ? (
                    <div className="mt-1 text-xs text-slate-500">Channel: {event.metadata.channel}</div>
                  ) : null}
                  {typeof event.metadata.hook_label === "string" && event.metadata.hook_label ? (
                    <div className="mt-1 text-xs text-slate-500">
                      Hook: {event.metadata.hook_label}
                      {typeof event.metadata.dry_run === "boolean" ? ` · ${event.metadata.dry_run ? "Dry run" : "Apply"}` : ""}
                    </div>
                  ) : null}
                  {event.note ? <div className="mt-2 text-sm text-slate-700">{event.note}</div> : null}
                  {typeof event.metadata.ticket_url === "string" && event.metadata.ticket_url ? (
                    <div className="mt-2">
                      <a
                        href={event.metadata.ticket_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-sm font-medium text-sky-700 hover:text-sky-800"
                      >
                        Open {typeof event.metadata.ticket_key === "string" && event.metadata.ticket_key ? event.metadata.ticket_key : "linked ticket"}
                      </a>
                    </div>
                  ) : null}
                  {typeof event.metadata.error === "string" && event.metadata.error ? (
                    <div className="mt-2 text-sm text-rose-700">{event.metadata.error}</div>
                  ) : null}
                  {typeof event.metadata.output_excerpt === "string" && event.metadata.output_excerpt ? (
                    <div className="mt-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600">
                      {event.metadata.output_excerpt}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="flex flex-wrap gap-3">
          <a
            href={opportunity.portal_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-xl bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800"
          >
            Open in Azure Portal
          </a>
          <Link
            to={opportunity.follow_up_route}
            className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Open follow-up page
          </Link>
        </section>
      </div>
    </aside>
  );
}

export default function AzureSavingsPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [opportunityType, setOpportunityType] = useState("");
  const [subscriptionId, setSubscriptionId] = useState("");
  const [resourceGroup, setResourceGroup] = useState("");
  const [effort, setEffort] = useState("");
  const [risk, setRisk] = useState("");
  const [confidence, setConfidence] = useState("");
  const [quantifiedOnly, setQuantifiedOnly] = useState(false);
  const [selectedOpportunityId, setSelectedOpportunityId] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const { sortKey, sortDir, toggleSort } = useTableSort<SavingsSortKey>("estimated_monthly_savings", "desc");
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => api.getMe(),
    staleTime: 60_000,
  });

  const summaryQuery = useQuery({
    queryKey: ["azure", "recommendations", "summary"],
    queryFn: () => api.getAzureRecommendationsSummary(),
    refetchInterval: 60_000,
  });

  const opportunitiesQuery = useQuery({
    queryKey: ["azure", "recommendations", { search, category, opportunityType, subscriptionId, resourceGroup, effort, risk, confidence, quantifiedOnly }],
    queryFn: () => api.getAzureRecommendations({
      search,
      category,
      opportunity_type: opportunityType,
      subscription_id: subscriptionId,
      resource_group: resourceGroup,
      effort,
      risk,
      confidence,
      quantified_only: quantifiedOnly,
    }),
    refetchInterval: 60_000,
  });
  const detailQuery = useQuery({
    queryKey: ["azure", "recommendation", selectedOpportunityId],
    queryFn: () => api.getAzureRecommendation(selectedOpportunityId),
    enabled: !!selectedOpportunityId,
    placeholderData: (prev) => prev,
  });
  const historyQuery = useQuery({
    queryKey: ["azure", "recommendation", selectedOpportunityId, "history"],
    queryFn: () => api.getAzureRecommendationHistory(selectedOpportunityId),
    enabled: !!selectedOpportunityId,
    placeholderData: (prev) => prev,
  });
  const actionContractQuery = useQuery({
    queryKey: ["azure", "recommendation", selectedOpportunityId, "actions"],
    queryFn: () => api.getAzureRecommendationActionContract(selectedOpportunityId),
    enabled: !!selectedOpportunityId,
    placeholderData: (prev) => prev,
  });

  async function refreshRecommendationQueries(recommendationId: string) {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["azure", "recommendations"] }),
      queryClient.invalidateQueries({ queryKey: ["azure", "savings"] }),
      queryClient.invalidateQueries({ queryKey: ["azure", "recommendation", recommendationId] }),
      queryClient.invalidateQueries({ queryKey: ["azure", "recommendation", recommendationId, "actions"] }),
      queryClient.invalidateQueries({ queryKey: ["azure", "recommendation", recommendationId, "history"] }),
    ]);
  }

  const dismissMutation = useMutation({
    mutationFn: ({ recommendationId, reason }: { recommendationId: string; reason: string }) =>
      api.dismissAzureRecommendation(recommendationId, reason),
    onMutate: () => setWorkflowError(""),
    onSuccess: async (_, variables) => {
      await refreshRecommendationQueries(variables.recommendationId);
    },
    onError: (error) => {
      setWorkflowError(error instanceof Error ? error.message : "Failed to dismiss recommendation.");
    },
  });
  const reopenMutation = useMutation({
    mutationFn: ({ recommendationId, note }: { recommendationId: string; note: string }) =>
      api.reopenAzureRecommendation(recommendationId, note),
    onMutate: () => setWorkflowError(""),
    onSuccess: async (_, variables) => {
      await refreshRecommendationQueries(variables.recommendationId);
    },
    onError: (error) => {
      setWorkflowError(error instanceof Error ? error.message : "Failed to reopen recommendation.");
    },
  });
  const actionStateMutation = useMutation({
    mutationFn: ({
      recommendationId,
      actionState,
      note,
    }: {
      recommendationId: string;
      actionState: string;
      note: string;
    }) =>
      api.updateAzureRecommendationActionState(recommendationId, {
        action_state: actionState,
        action_type: "portal_workflow_update",
        note,
      }),
    onMutate: () => setWorkflowError(""),
    onSuccess: async (_, variables) => {
      await refreshRecommendationQueries(variables.recommendationId);
    },
    onError: (error) => {
      setWorkflowError(error instanceof Error ? error.message : "Failed to update recommendation workflow.");
    },
  });
  const createTicketMutation = useMutation({
    mutationFn: ({
      recommendationId,
      projectKey,
      issueType,
      summary,
      note,
    }: {
      recommendationId: string;
      projectKey: string;
      issueType: string;
      summary: string;
      note: string;
    }) =>
      api.createAzureRecommendationTicket(recommendationId, {
        project_key: projectKey,
        issue_type: issueType,
        summary,
        note,
      }),
    onMutate: () => setWorkflowError(""),
    onSuccess: async (result: AzureRecommendationCreateTicketResponse) => {
      await refreshRecommendationQueries(result.recommendation.id);
    },
    onError: (error) => {
      setWorkflowError(error instanceof Error ? error.message : "Failed to create Jira ticket.");
    },
  });
  const sendAlertMutation = useMutation({
    mutationFn: ({
      recommendationId,
      channel,
      teamsWebhookUrl,
      note,
    }: {
      recommendationId: string;
      channel: string;
      teamsWebhookUrl: string;
      note: string;
    }) =>
      api.sendAzureRecommendationAlert(recommendationId, {
        channel,
        teams_webhook_url: teamsWebhookUrl,
        note,
      }),
    onMutate: () => setWorkflowError(""),
    onSuccess: async (result: AzureRecommendationSendAlertResponse) => {
      await refreshRecommendationQueries(result.recommendation.id);
    },
    onError: (error) => {
      setWorkflowError(error instanceof Error ? error.message : "Failed to send Teams alert.");
    },
  });
  const runSafeScriptMutation = useMutation({
    mutationFn: ({
      recommendationId,
      hookKey,
      dryRun,
      note,
    }: {
      recommendationId: string;
      hookKey: string;
      dryRun: boolean;
      note: string;
    }) =>
      api.runAzureRecommendationSafeScript(recommendationId, {
        hook_key: hookKey,
        dry_run: dryRun,
        note,
      }),
    onMutate: () => setWorkflowError(""),
    onSuccess: async (result: AzureRecommendationRunSafeScriptResponse) => {
      await refreshRecommendationQueries(result.recommendation.id);
    },
    onError: (error) => {
      setWorkflowError(error instanceof Error ? error.message : "Failed to run safe remediation hook.");
    },
  });

  const summary = summaryQuery.data;
  const opportunities = opportunitiesQuery.data ?? [];
  const actionableRows = opportunities.filter((item) => item.category !== "commitment");
  const commitmentRows = opportunities.filter((item) => item.category === "commitment");
  const selectedOpportunity = detailQuery.data ?? opportunities.find((item) => item.id === selectedOpportunityId) ?? null;
  const isAdmin = !!meQuery.data?.is_admin;
  const workflowBusy =
    dismissMutation.isPending ||
    reopenMutation.isPending ||
    actionStateMutation.isPending ||
    createTicketMutation.isPending ||
    sendAlertMutation.isPending ||
    runSafeScriptMutation.isPending;

  const sortedActionableRows = sortRows(actionableRows, sortKey, sortDir, (item, key) => {
    if (key === "subscription") return item.subscription_name || item.subscription_id;
    if (key === "estimated_monthly_savings") return item.estimated_monthly_savings;
    if (key === "effort" || key === "risk") {
      return { low: 0, medium: 1, high: 2 }[item[key]] ?? 99;
    }
    if (key === "confidence") {
      return { high: 0, medium: 1, low: 2 }[item.confidence] ?? 99;
    }
    return (item as unknown as Record<string, string | number | null | undefined>)[key];
  });
  const scrollKey = [search, category, opportunityType, subscriptionId, resourceGroup, effort, risk, confidence, String(quantifiedOnly), sortKey, sortDir].join("|");
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(sortedActionableRows.length, 20, scrollKey);
  const visibleRows = sortedActionableRows.slice(0, visibleCount);

  const categoryOptions = (summary?.by_category ?? []).map((item) => item.label);
  const opportunityTypeOptions = Array.from(new Set(opportunities.map((item) => item.opportunity_type))).sort();
  const subscriptionOptions = Array.from(new Set(opportunities.map((item) => item.subscription_name || item.subscription_id).filter(Boolean))).sort();
  const resourceGroupOptions = Array.from(new Set(opportunities.map((item) => item.resource_group).filter(Boolean))).sort();
  const costContext = summary?.cost_context;
  const coverageWindow = formatCoverageWindow(costContext?.window_start, costContext?.window_end);

  if (summaryQuery.isLoading || opportunitiesQuery.isLoading) {
    return <div className="text-sm text-slate-500">Loading Azure savings opportunities...</div>;
  }

  if (summaryQuery.isError || opportunitiesQuery.isError || !summary) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure savings data.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Savings</h1>
          <p className="mt-1 text-sm text-slate-500">
            Ranked Azure cost-cutting opportunities across compute, storage, network cleanup, and reservation strategy.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <AzureSourceBadge
              label={summary.source_label || "Persisted recommendation workspace"}
              description={
                summary.source_description ||
                "This page now uses the local recommendation model and workflow APIs, with cache and export-backed inputs hydrated behind the scenes."
              }
              tone="amber"
            />
            {costContext && (
              <AzureSourceBadge
                label={costContext.source_label}
                description={
                  costContext.source_description ||
                  "Quantified savings on this page use the current shared cost context for prioritization."
                }
                tone={costContext.export_backed ? "sky" : "amber"}
              />
            )}
            <AzureSourceBadge
              label="Operational, not invoice-grade"
              description="Use the governed reporting handoff on Azure Overview for shared finance and showback reporting."
              tone="emerald"
            />
          </div>
          {coverageWindow ? (
            <div className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
              Cost coverage window: {coverageWindow}
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-3">
          <a
            href={api.exportAzureRecommendationsCsv({
              search,
              category,
              opportunity_type: opportunityType,
              subscription_id: subscriptionId,
              resource_group: resourceGroup,
              effort,
              risk,
              confidence,
              quantified_only: quantifiedOnly,
            })}
            className="rounded-xl border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Export CSV
          </a>
          <a
            href={api.exportAzureRecommendationsExcel({
              search,
              category,
              opportunity_type: opportunityType,
              subscription_id: subscriptionId,
              resource_group: resourceGroup,
              effort,
              risk,
              confidence,
              quantified_only: quantifiedOnly,
            })}
            className="rounded-xl bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800"
          >
            Export Excel
          </a>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Quantified Savings"
          value={formatAzureCurrency(summary.quantified_monthly_savings, summary.currency)}
          sub={
            costContext?.export_backed
              ? "Monthly proxy using export-backed cost analytics"
              : "Monthly proxy from cached Azure cost data"
          }
          tone="text-emerald-700"
        />
        <StatCard
          label="Quick Wins"
          value={summary.quick_win_count.toLocaleString()}
          sub={`${formatAzureCurrency(summary.quick_win_monthly_savings, summary.currency)} quantified`}
          tone="text-sky-700"
        />
        <StatCard
          label="Total Opportunities"
          value={summary.total_opportunities.toLocaleString()}
          sub={`${summary.quantified_opportunities.toLocaleString()} quantified`}
        />
        <StatCard
          label="Commitment Strategy"
          value={summary.unquantified_opportunity_count.toLocaleString()}
          sub="Unquantified reservation and commitment follow-up"
        />
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search resource, summary, recommendation..."
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
          />
          <select value={category} onChange={(event) => setCategory(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="">All categories</option>
            {categoryOptions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
          <select value={opportunityType} onChange={(event) => setOpportunityType(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="">All opportunity types</option>
            {opportunityTypeOptions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
          <select value={subscriptionId} onChange={(event) => setSubscriptionId(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="">All subscriptions</option>
            {subscriptionOptions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
          <select value={resourceGroup} onChange={(event) => setResourceGroup(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
            <option value="">All resource groups</option>
            {resourceGroupOptions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Effort</span>
          <FilterChip label="All" active={!effort} onClick={() => setEffort("")} />
          {effortOptions.map((value) => (
            <FilterChip key={value} label={value} active={effort === value} onClick={() => setEffort(value)} />
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Risk</span>
          <FilterChip label="All" active={!risk} onClick={() => setRisk("")} />
          {effortOptions.map((value) => (
            <FilterChip key={value} label={value} active={risk === value} onClick={() => setRisk(value)} />
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Confidence</span>
          <FilterChip label="All" active={!confidence} onClick={() => setConfidence("")} />
          {confidenceOptions.map((value) => (
            <FilterChip key={value} label={value} active={confidence === value} onClick={() => setConfidence(value)} />
          ))}
          <button
            type="button"
            onClick={() => setQuantifiedOnly((value) => !value)}
            className={`ml-3 rounded-full px-3 py-1.5 text-xs font-semibold transition ${
              quantifiedOnly
                ? "bg-emerald-600 text-white"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            Quantified only
          </button>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Actionable Savings Opportunities</h2>
            <p className="mt-1 text-sm text-slate-500">
              Quantified cleanup wins and non-commitment follow-up items, ranked by savings and implementation friction.
            </p>
          </div>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
            {sortedActionableRows.length.toLocaleString()} results
          </span>
        </div>

        {visibleRows.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-slate-400">No savings opportunities matched the current filters.</div>
        ) : (
          <div className="max-h-[70vh] overflow-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <SortHeader col="title" label="Recommendation" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="category" label="Category" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="subscription" label="Subscription" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="resource_group" label="Resource Group" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="effort" label="Effort" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="risk" label="Risk" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="confidence" label="Confidence" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                  <SortHeader col="estimated_monthly_savings" label="Est. Monthly Savings" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((item, index) => (
                  <tr
                    key={item.id}
                    className={`${index % 2 === 0 ? "bg-white" : "bg-slate-50/50"} cursor-pointer hover:bg-sky-50/60`}
                    onClick={() => setSelectedOpportunityId(item.id)}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{item.title}</div>
                      <div className="mt-1 line-clamp-2 text-xs text-slate-500">{item.summary}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{item.category}</td>
                    <td className="px-4 py-3 text-slate-700">{item.subscription_name || item.subscription_id || "—"}</td>
                    <td className="px-4 py-3 text-slate-700">{item.resource_group || "—"}</td>
                    <td className="px-4 py-3"><ToneBadge label="Effort" value={item.effort} tone="effort" /></td>
                    <td className="px-4 py-3"><ToneBadge label="Risk" value={item.risk} tone="risk" /></td>
                    <td className="px-4 py-3"><ToneBadge label="Confidence" value={item.confidence} tone="confidence" /></td>
                    <td className="px-4 py-3 text-right font-semibold text-emerald-700">
                      {item.quantified ? formatAzureCurrency(item.estimated_monthly_savings, item.currency) : "Unquantified"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {hasMore ? (
              <div ref={sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
                Showing {visibleRows.length.toLocaleString()} of {sortedActionableRows.length.toLocaleString()} results — scroll for more
              </div>
            ) : null}
          </div>
        )}
      </section>

      <AzureSavingsHighlightsSection
        title="Commitment Strategy"
          description="Reservation coverage gaps and excesses need review, but they are intentionally kept out of the quantified totals until pricing is validated."
          opportunities={commitmentRows}
        emptyMessage="No reservation strategy items are active in the current filtered view."
        maxItems={8}
      />

      <section className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Top Categories</h2>
          <div className="mt-4 space-y-3">
            {summary.by_category.map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-800">{item.label}</span>
                <span className="text-sm font-semibold text-slate-900">
                  {item.count.toLocaleString()} · {formatAzureCurrency(item.estimated_monthly_savings, summary.currency)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Top Subscriptions</h2>
          <div className="mt-4 space-y-3">
            {summary.top_subscriptions.map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-800">{item.label}</span>
                <span className="text-sm font-semibold text-slate-900">
                  {item.count.toLocaleString()} · {formatAzureCurrency(item.estimated_monthly_savings, summary.currency)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <OpportunityDrawer
        opportunity={selectedOpportunity}
        actionContract={actionContractQuery.data ?? null}
        actionContractLoading={actionContractQuery.isLoading}
        history={historyQuery.data ?? []}
        historyLoading={historyQuery.isLoading}
        isAdmin={isAdmin}
        workflowBusy={workflowBusy}
        workflowError={workflowError}
        onDismiss={(reason) => {
          if (!selectedOpportunityId) return;
          dismissMutation.mutate({ recommendationId: selectedOpportunityId, reason });
        }}
        onReopen={(note) => {
          if (!selectedOpportunityId) return;
          reopenMutation.mutate({ recommendationId: selectedOpportunityId, note });
        }}
        onUpdateActionState={(actionState, note) => {
          if (!selectedOpportunityId) return;
          actionStateMutation.mutate({ recommendationId: selectedOpportunityId, actionState, note });
        }}
        onCreateTicket={(projectKey, issueType, summary, note) => {
          if (!selectedOpportunityId) return;
          createTicketMutation.mutate({
            recommendationId: selectedOpportunityId,
            projectKey,
            issueType,
            summary,
            note,
          });
        }}
        createTicketBusy={createTicketMutation.isPending}
        onSendAlert={(channel, teamsWebhookUrl, note) => {
          if (!selectedOpportunityId) return;
          sendAlertMutation.mutate({
            recommendationId: selectedOpportunityId,
            channel,
            teamsWebhookUrl,
            note,
          });
        }}
        onRunSafeScript={(hookKey, dryRun, note) => {
          if (!selectedOpportunityId) return;
          runSafeScriptMutation.mutate({
            recommendationId: selectedOpportunityId,
            hookKey,
            dryRun,
            note,
          });
        }}
        sendAlertBusy={sendAlertMutation.isPending}
        runSafeScriptBusy={runSafeScriptMutation.isPending}
        onClose={() => {
          setSelectedOpportunityId("");
          setWorkflowError("");
        }}
      />
    </div>
  );
}
