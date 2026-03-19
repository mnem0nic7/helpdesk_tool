import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type RuleSortKey = "name" | "domain" | "trigger_type" | "frequency" | "last_sent";
type HistorySortKey = "rule_name" | "trigger_type" | "sent_at" | "match_count" | "status";
import {
  api,
  type AzureAlertRule,
  type AzureAlertRuleCreate,
  type AzureAlertHistoryItem,
  type AzureChatParseResponse,
} from "../lib/api.ts";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";

// ── Helpers ───────────────────────────────────────────────────────────────────

const DOMAIN_COLORS: Record<string, string> = {
  cost: "bg-blue-100 text-blue-700",
  vms: "bg-purple-100 text-purple-700",
  identity: "bg-emerald-100 text-emerald-700",
  resources: "bg-amber-100 text-amber-700",
};

function DomainChip({ domain }: { domain: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold capitalize ${DOMAIN_COLORS[domain] ?? "bg-slate-100 text-slate-700"}`}>
      {domain}
    </span>
  );
}

function StatusChip({ status }: { status: string }) {
  const colors: Record<string, string> = {
    sent: "bg-emerald-100 text-emerald-700",
    partial: "bg-amber-100 text-amber-700",
    failed: "bg-red-100 text-red-700",
    dry_run: "bg-slate-100 text-slate-600",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${colors[status] ?? "bg-slate-100 text-slate-700"}`}>
      {status.replace("_", " ")}
    </span>
  );
}

function formatSchedule(rule: AzureAlertRule): string {
  if (rule.frequency === "immediate") return "Every 10 min";
  if (rule.frequency === "hourly") return "Hourly";
  return `${rule.frequency.charAt(0).toUpperCase() + rule.frequency.slice(1)} ${rule.schedule_time} UTC`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

const EMPTY_RULE: AzureAlertRuleCreate = {
  name: "", domain: "cost", trigger_type: "", trigger_config: {},
  frequency: "daily", schedule_time: "09:00", schedule_days: "0,1,2,3,4",
  recipients: "", teams_webhook_url: "", custom_subject: "", custom_message: "",
};

// ── Quick Builder Modal ───────────────────────────────────────────────────────

function QuickBuilderModal({
  onClose,
  onEditInBuilder,
}: {
  onClose: () => void;
  onEditInBuilder: (rule: AzureAlertRuleCreate) => void;
}) {
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<AzureChatParseResponse | null>(null);
  const qc = useQueryClient();

  const parseMutation = useMutation({
    mutationFn: () => api.chatParseAzureAlert(message),
    onSuccess: (data) => setResult(data),
  });

  const saveMutation = useMutation({
    mutationFn: () => api.createAzureAlertRule(result!.rule!),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["azure", "alerts", "rules"] });
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4" onClick={onClose}>
      <div
        className="w-full max-w-xl rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-slate-900">Quick Alert</h2>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">Close</button>
        </div>

        <p className="mt-3 text-sm text-slate-500">Describe what you want to monitor:</p>
        <ul className="mt-2 space-y-1 text-xs text-slate-400">
          <li>· "Alert me when monthly spend exceeds $10k"</li>
          <li>· "Email me when a VM is off for 7+ days"</li>
          <li>· "Notify Teams when new guests are added"</li>
        </ul>

        <div className="mt-4 flex gap-2">
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !parseMutation.isPending && message.trim()) {
                parseMutation.mutate();
              }
            }}
            placeholder="Describe your alert..."
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
          <button
            type="button"
            onClick={() => parseMutation.mutate()}
            disabled={parseMutation.isPending || !message.trim()}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {parseMutation.isPending ? "..." : "Send"}
          </button>
        </div>

        {result ? (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
            {result.parsed && result.rule ? (
              <>
                <div className="space-y-1 text-sm">
                  <div><span className="font-medium text-slate-500">Name:</span> {result.rule.name || "—"}</div>
                  <div><span className="font-medium text-slate-500">Domain:</span> {result.rule.domain}</div>
                  <div><span className="font-medium text-slate-500">Trigger:</span> {result.rule.trigger_type.replace(/_/g, " ")}</div>
                  <div><span className="font-medium text-slate-500">Schedule:</span> {result.rule.frequency} {result.rule.schedule_time} UTC</div>
                  {result.summary ? <div className="mt-2 text-xs text-slate-400">{result.summary}</div> : null}
                </div>
                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    onClick={() => { onEditInBuilder(result.rule!); onClose(); }}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
                  >
                    Edit in Builder
                  </button>
                  <button
                    type="button"
                    onClick={() => saveMutation.mutate()}
                    disabled={saveMutation.isPending}
                    className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    {saveMutation.isPending ? "Saving..." : "Save"}
                  </button>
                </div>
                {saveMutation.isError ? (
                  <p className="mt-2 text-xs text-red-600">{(saveMutation.error as Error).message}</p>
                ) : null}
              </>
            ) : (
              <p className="text-sm text-red-700">
                I couldn't parse that — {result.error || "try the Builder instead."}
              </p>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ── Form Builder Drawer ───────────────────────────────────────────────────────

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function FormBuilderDrawer({
  initial,
  editingId,
  onClose,
}: {
  initial: AzureAlertRuleCreate;
  editingId: string | null;
  onClose: () => void;
}) {
  const [form, setForm] = useState<AzureAlertRuleCreate>(initial);
  const [testResult, setTestResult] = useState<{ count: number } | null>(null);
  const [emailInput, setEmailInput] = useState("");
  const qc = useQueryClient();

  const triggerTypesQuery = useQuery({
    queryKey: ["azure", "alerts", "trigger-types"],
    queryFn: () => api.getAzureAlertTriggerTypes(),
    staleTime: 60_000,
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      editingId
        ? api.updateAzureAlertRule(editingId, form)
        : api.createAzureAlertRule(form),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["azure", "alerts", "rules"] });
      onClose();
    },
  });

  // For test: if editing, test directly; if creating, create temp rule → test → delete
  const testMutation = useMutation({
    mutationFn: async () => {
      if (editingId) return api.testAzureAlertRule(editingId);
      const created = await api.createAzureAlertRule(form);
      try {
        return await api.testAzureAlertRule(created.id);
      } finally {
        await api.deleteAzureAlertRule(created.id);
      }
    },
    onSuccess: (data) => setTestResult({ count: data.match_count }),
  });

  const triggers = triggerTypesQuery.data ?? {};
  const domainTriggers = Object.keys(triggers[form.domain] ?? {});

  function setField<K extends keyof AzureAlertRuleCreate>(key: K, value: AzureAlertRuleCreate[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function toggleDay(dayIdx: number) {
    const current = new Set(
      form.schedule_days.split(",").map(Number).filter((n) => !isNaN(n))
    );
    if (current.has(dayIdx)) current.delete(dayIdx);
    else current.add(dayIdx);
    setField("schedule_days", Array.from(current).sort().join(","));
  }

  const activeDays = new Set(
    form.schedule_days.split(",").map(Number).filter((n) => !isNaN(n))
  );
  const configSchema = (triggers[form.domain] ?? {})[form.trigger_type] ?? {};

  const canSave = Boolean(
    form.name.trim() &&
    form.trigger_type &&
    (form.recipients.trim() || form.teams_webhook_url.trim())
  );

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-lg flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-slate-200 px-6 py-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">{editingId ? "Edit Alert" : "New Alert"}</h2>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">Close</button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* Domain */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Domain</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {(["cost", "vms", "identity", "resources"] as const).map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => { setField("domain", d); setField("trigger_type", ""); setField("trigger_config", {}); }}
                  className={`rounded-full border px-4 py-1.5 text-sm font-medium transition capitalize ${
                    form.domain === d
                      ? "border-sky-500 bg-sky-50 text-sky-700"
                      : "border-slate-300 text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
          </section>

          {/* Trigger */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Trigger</h3>
            <select
              value={form.trigger_type}
              onChange={(e) => { setField("trigger_type", e.target.value); setField("trigger_config", {}); }}
              className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            >
              <option value="">Select trigger...</option>
              {domainTriggers.map((t) => (
                <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
              ))}
            </select>
            {Object.entries(configSchema).map(([key, defaultVal]) => (
              <div key={key} className="mt-3">
                <label className="text-xs font-medium text-slate-600 capitalize">{key.replace(/_/g, " ")}</label>
                {Array.isArray(defaultVal) ? (
                  <input
                    value={((form.trigger_config[key] as string[] | undefined) ?? []).join(", ")}
                    onChange={(e) => setField("trigger_config", {
                      ...form.trigger_config,
                      [key]: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                    })}
                    placeholder="tag1, tag2, ..."
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                ) : key === "period" ? (
                  <select
                    value={(form.trigger_config[key] as string | undefined) ?? String(defaultVal)}
                    onChange={(e) => setField("trigger_config", { ...form.trigger_config, [key]: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="monthly">Monthly</option>
                    <option value="weekly">Weekly</option>
                  </select>
                ) : typeof defaultVal === "number" ? (
                  <input
                    type="number"
                    value={(form.trigger_config[key] as number | undefined) ?? defaultVal}
                    onChange={(e) => setField("trigger_config", { ...form.trigger_config, [key]: Number(e.target.value) })}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                ) : (
                  <input
                    value={(form.trigger_config[key] as string | undefined) ?? String(defaultVal)}
                    onChange={(e) => setField("trigger_config", { ...form.trigger_config, [key]: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                )}
              </div>
            ))}
          </section>

          {/* Schedule */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Schedule</h3>
            <div className="mt-2 flex flex-wrap gap-2">
              {(["immediate", "hourly", "daily", "weekly"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setField("frequency", f)}
                  className={`rounded-full border px-4 py-1.5 text-sm font-medium transition capitalize ${
                    form.frequency === f
                      ? "border-sky-500 bg-sky-50 text-sky-700"
                      : "border-slate-300 text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            {(form.frequency === "daily" || form.frequency === "weekly") ? (
              <div className="mt-3 space-y-3">
                <div>
                  <label className="text-xs font-medium text-slate-600">Time (UTC)</label>
                  <input
                    type="time"
                    value={form.schedule_time}
                    onChange={(e) => setField("schedule_time", e.target.value)}
                    className="mt-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-slate-600">Days</label>
                  <div className="mt-1 flex gap-1">
                    {WEEKDAYS.map((label, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => toggleDay(idx)}
                        className={`rounded px-2 py-1 text-xs font-medium transition ${
                          activeDays.has(idx) ? "bg-sky-600 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            ) : null}
          </section>

          {/* Notify */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Notify</h3>
            <div className="mt-2">
              <label className="text-xs font-medium text-slate-600">Email recipients</label>
              <div className="mt-1 flex flex-wrap gap-1">
                {form.recipients.split(",").filter((e) => e.trim()).map((email) => (
                  <span key={email} className="flex items-center gap-1 rounded-full bg-sky-50 px-2 py-0.5 text-xs text-sky-700">
                    {email.trim()}
                    <button
                      type="button"
                      onClick={() => setField("recipients", form.recipients.split(",").filter((e) => e.trim() !== email.trim()).join(","))}
                      className="text-sky-400 hover:text-sky-700"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <div className="mt-1 flex gap-2">
                <input
                  value={emailInput}
                  onChange={(e) => setEmailInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && emailInput.includes("@")) {
                      setField("recipients", [form.recipients, emailInput.trim()].filter(Boolean).join(","));
                      setEmailInput("");
                    }
                  }}
                  placeholder="email@company.com"
                  className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (emailInput.includes("@")) {
                      setField("recipients", [form.recipients, emailInput.trim()].filter(Boolean).join(","));
                      setEmailInput("");
                    }
                  }}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
                >
                  Add
                </button>
              </div>
            </div>
            <div className="mt-3">
              <label className="text-xs font-medium text-slate-600">Teams webhook URL</label>
              <input
                value={form.teams_webhook_url}
                onChange={(e) => setField("teams_webhook_url", e.target.value)}
                placeholder="https://...webhook.office.com/..."
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            {!form.recipients.trim() && !form.teams_webhook_url.trim() ? (
              <p className="mt-1 text-xs text-amber-600">At least one delivery channel is required.</p>
            ) : null}
          </section>

          {/* Name */}
          <section>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Name</h3>
            <input
              value={form.name}
              onChange={(e) => setField("name", e.target.value)}
              placeholder="My alert rule name"
              className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-sky-500"
            />
          </section>
        </div>

        <div className="border-t border-slate-200 px-6 py-4 flex items-center gap-3">
          <button
            type="button"
            onClick={() => testMutation.mutate()}
            disabled={testMutation.isPending || !form.trigger_type}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {testMutation.isPending ? "Testing..." : "Test"}
          </button>
          {testResult !== null ? (
            <span className="text-sm text-slate-600">
              {testResult.count} match{testResult.count !== 1 ? "es" : ""} now
            </span>
          ) : null}
          <div className="flex-1" />
          {saveMutation.isError ? (
            <span className="text-xs text-red-600">{(saveMutation.error as Error).message}</span>
          ) : null}
          <button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !canSave}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {saveMutation.isPending ? "Saving..." : "Save"}
          </button>
        </div>
      </aside>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AzureAlertsPage() {
  const [tab, setTab] = useState<"rules" | "history">("rules");
  const [showQuick, setShowQuick] = useState(false);
  const [showBuilder, setShowBuilder] = useState(false);
  const [builderInitial, setBuilderInitial] = useState<AzureAlertRuleCreate>(EMPTY_RULE);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, number>>({});
  const qc = useQueryClient();

  const rulesQuery = useQuery({
    queryKey: ["azure", "alerts", "rules"],
    queryFn: () => api.getAzureAlertRules(),
    refetchInterval: 30_000,
  });

  const historyQuery = useQuery({
    queryKey: ["azure", "alerts", "history"],
    queryFn: () => api.getAzureAlertHistory({ limit: 200 }),
    enabled: tab === "history",
    refetchInterval: 60_000,
  });

  const toggleMutation = useMutation({
    mutationFn: (id: string) => api.toggleAzureAlertRule(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["azure", "alerts", "rules"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteAzureAlertRule(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["azure", "alerts", "rules"] }),
  });

  const testMutation = useMutation({
    mutationFn: (id: string) => api.testAzureAlertRule(id),
    onSuccess: (data, id) => setTestResults((prev) => ({ ...prev, [id]: data.match_count })),
  });

  const rules = rulesQuery.data ?? [];
  const history = historyQuery.data ?? [];
  const { sortKey: ruleSortKey, sortDir: ruleSortDir, toggleSort: toggleRuleSort } = useTableSort<RuleSortKey>("name");
  const { sortKey: histSortKey, sortDir: histSortDir, toggleSort: toggleHistSort } = useTableSort<HistorySortKey>("sent_at", "desc");
  const sortedRules = sortRows(rules, ruleSortKey, ruleSortDir);
  const sortedHistory = sortRows(history, histSortKey, histSortDir);
  const rulesScroll = useInfiniteScrollCount(sortedRules.length, 50, `rules|${ruleSortKey}|${ruleSortDir}`);
  const historyScroll = useInfiniteScrollCount(sortedHistory.length, 50, `history|${histSortKey}|${histSortDir}`);
  const visibleRules = sortedRules.slice(0, rulesScroll.visibleCount);
  const visibleHistory = sortedHistory.slice(0, historyScroll.visibleCount);

  function openBuilder(initial: AzureAlertRuleCreate = EMPTY_RULE, id: string | null = null) {
    setBuilderInitial(initial);
    setEditingId(id);
    setShowBuilder(true);
  }

  function openEdit(rule: AzureAlertRule) {
    openBuilder(
      {
        name: rule.name, domain: rule.domain, trigger_type: rule.trigger_type,
        trigger_config: rule.trigger_config as Record<string, unknown>,
        frequency: rule.frequency, schedule_time: rule.schedule_time,
        schedule_days: rule.schedule_days, recipients: rule.recipients,
        teams_webhook_url: rule.teams_webhook_url,
        custom_subject: rule.custom_subject, custom_message: rule.custom_message,
      },
      rule.id,
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Alerts</h1>
          <p className="mt-1 text-sm text-slate-500">
            Monitor Azure and get notified when conditions are met.
          </p>
        </div>
        <div className="flex overflow-hidden rounded-lg border border-slate-300 shadow-sm">
          <button
            type="button"
            onClick={() => setShowQuick(true)}
            className="border-r border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Quick (AI)
          </button>
          <button
            type="button"
            onClick={() => openBuilder()}
            className="bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Builder
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200">
        {(["rules", "history"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize transition border-b-2 -mb-px ${
              tab === t
                ? "border-sky-600 text-sky-700"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Rules tab */}
      {tab === "rules" ? (
        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          {rulesQuery.isLoading ? (
            <div className="px-4 py-8 text-center text-sm text-slate-500">Loading alert rules...</div>
          ) : rules.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm text-slate-500">
              No alert rules yet — use Quick or Builder to create your first one.
            </div>
          ) : (
            <div className="overflow-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <SortHeader col="name" label="Name" sortKey={ruleSortKey} sortDir={ruleSortDir} onSort={toggleRuleSort} />
                    <SortHeader col="domain" label="Domain" sortKey={ruleSortKey} sortDir={ruleSortDir} onSort={toggleRuleSort} />
                    <SortHeader col="trigger_type" label="Trigger" sortKey={ruleSortKey} sortDir={ruleSortDir} onSort={toggleRuleSort} />
                    <SortHeader col="frequency" label="Schedule" sortKey={ruleSortKey} sortDir={ruleSortDir} onSort={toggleRuleSort} />
                    <SortHeader col="last_sent" label="Last Sent" sortKey={ruleSortKey} sortDir={ruleSortDir} onSort={toggleRuleSort} />
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRules.map((rule, idx) => (
                    <tr key={rule.id} className={idx % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => openEdit(rule)}
                          className="font-medium text-sky-700 hover:underline text-left"
                        >
                          {rule.name}
                        </button>
                      </td>
                      <td className="px-4 py-3"><DomainChip domain={rule.domain} /></td>
                      <td className="px-4 py-3 text-slate-600">{rule.trigger_type.replace(/_/g, " ")}</td>
                      <td className="px-4 py-3 text-slate-600 whitespace-nowrap">{formatSchedule(rule)}</td>
                      <td className="px-4 py-3 text-slate-500 whitespace-nowrap text-xs">{formatDate(rule.last_sent)}</td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => toggleMutation.mutate(rule.id)}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${rule.enabled ? "bg-sky-600" : "bg-slate-300"}`}
                        >
                          <span className={`inline-block h-3.5 w-3.5 translate-x-0.5 rounded-full bg-white shadow transition-transform ${rule.enabled ? "translate-x-4" : ""}`} />
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            onClick={() => testMutation.mutate(rule.id)}
                            disabled={testMutation.isPending}
                            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                          >
                            Test
                          </button>
                          {testResults[rule.id] !== undefined ? (
                            <span className="text-xs text-slate-500">
                              {testResults[rule.id]} hit{testResults[rule.id] !== 1 ? "s" : ""}
                            </span>
                          ) : null}
                          <button
                            type="button"
                            onClick={() => {
                              if (confirm(`Delete "${rule.name}"?`)) deleteMutation.mutate(rule.id);
                            }}
                            className="rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rulesScroll.hasMore ? (
                <div ref={rulesScroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
                  Showing {visibleRules.length} of {rules.length} rules — scroll for more
                </div>
              ) : null}
            </div>
          )}
        </section>
      ) : null}

      {/* History tab */}
      {tab === "history" ? (
        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          {historyQuery.isLoading ? (
            <div className="px-4 py-8 text-center text-sm text-slate-500">Loading alert history...</div>
          ) : history.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm text-slate-500">No alert history yet.</div>
          ) : (
            <div className="overflow-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <tr>
                    <SortHeader col="rule_name" label="Rule" sortKey={histSortKey} sortDir={histSortDir} onSort={toggleHistSort} />
                    <SortHeader col="trigger_type" label="Trigger" sortKey={histSortKey} sortDir={histSortDir} onSort={toggleHistSort} />
                    <SortHeader col="sent_at" label="Sent At" sortKey={histSortKey} sortDir={histSortDir} onSort={toggleHistSort} />
                    <th className="px-4 py-3">Recipients</th>
                    <SortHeader col="match_count" label="Matches" sortKey={histSortKey} sortDir={histSortDir} onSort={toggleHistSort} />
                    <SortHeader col="status" label="Status" sortKey={histSortKey} sortDir={histSortDir} onSort={toggleHistSort} />
                  </tr>
                </thead>
                <tbody>
                  {visibleHistory.map((item: AzureAlertHistoryItem, idx: number) => {
                    const emails = item.recipients.split(",").filter(Boolean);
                    const recipientLabel = emails.length > 1
                      ? `${emails[0]} +${emails.length - 1}`
                      : emails[0] ?? "—";
                    return (
                      <tr key={item.id} className={idx % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                        <td className="px-4 py-3 font-medium text-slate-900">{item.rule_name}</td>
                        <td className="px-4 py-3 text-slate-600">{item.trigger_type.replace(/_/g, " ")}</td>
                        <td className="px-4 py-3 text-slate-500 whitespace-nowrap text-xs">{formatDate(item.sent_at)}</td>
                        <td className="px-4 py-3 text-slate-600 text-xs">{recipientLabel}</td>
                        <td className="px-4 py-3 font-semibold text-slate-900">{item.match_count}</td>
                        <td className="px-4 py-3"><StatusChip status={item.status} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {historyScroll.hasMore ? (
                <div ref={historyScroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
                  Showing {visibleHistory.length} of {history.length} entries — scroll for more
                </div>
              ) : null}
            </div>
          )}
        </section>
      ) : null}

      {showQuick ? (
        <QuickBuilderModal
          onClose={() => setShowQuick(false)}
          onEditInBuilder={(rule) => openBuilder(rule)}
        />
      ) : null}

      {showBuilder ? (
        <FormBuilderDrawer
          initial={builderInitial}
          editingId={editingId}
          onClose={() => { setShowBuilder(false); setEditingId(null); }}
        />
      ) : null}
    </div>
  );
}
