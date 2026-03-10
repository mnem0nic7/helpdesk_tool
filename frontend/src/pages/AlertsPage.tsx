import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { AlertRule, AlertTriggerType, AlertTestResult } from "../lib/api.ts";
import { getSiteBranding } from "../lib/siteContext.ts";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FREQUENCIES = [
  { value: "immediate", label: "Every check (~1 min)" },
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
];

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const TRIGGER_CONFIGS: Record<string, { label: string; field: string; default: number }[]> = {
  stale: [{ label: "Stale after (hours)", field: "stale_hours", default: 24 }],
  fr_approaching: [{ label: "Threshold (%)", field: "threshold_pct", default: 80 }],
  res_approaching: [{ label: "Threshold (%)", field: "threshold_pct", default: 80 }],
};

function sortOptionValues(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
}

function describeSelection(selected: string[], placeholder: string): string {
  if (selected.length === 0) return placeholder;
  if (selected.length === 1) return selected[0];
  return `${selected.length} selected`;
}

function MultiSelectDropdown({
  label,
  placeholder,
  options,
  selected,
  onChange,
}: {
  label: string;
  placeholder: string;
  options: string[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const sortedOptions = useMemo(() => sortOptionValues(options), [options]);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [open]);

  function toggleValue(value: string) {
    if (selected.includes(value)) {
      onChange(selected.filter((entry) => entry !== value));
      return;
    }
    onChange([...selected, value]);
  }

  return (
    <div ref={containerRef} className="relative">
      <span className="text-xs text-gray-500">{label}</span>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="mt-1 flex w-full items-center justify-between rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm"
      >
        <span className={selected.length === 0 ? "text-gray-400" : "text-gray-700"}>
          {describeSelection(selected, placeholder)}
        </span>
        <span className="ml-3 text-xs text-gray-400">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="absolute z-20 mt-1 w-full rounded-md border border-gray-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
            <span className="text-xs font-medium text-gray-500">{selected.length} selected</span>
            <button
              type="button"
              onClick={() => onChange([])}
              disabled={selected.length === 0}
              className="text-xs font-medium text-blue-600 disabled:cursor-not-allowed disabled:text-gray-300"
            >
              Clear
            </button>
          </div>
          <div className="max-h-52 overflow-y-auto py-1">
            {sortedOptions.length === 0 ? (
              <div className="px-3 py-2 text-sm text-gray-400">No options available.</div>
            ) : (
              sortedOptions.map((option) => (
                <label
                  key={option}
                  className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  <input
                    type="checkbox"
                    checked={selected.includes(option)}
                    onChange={() => toggleValue(option)}
                    className="h-4 w-4 rounded border-gray-300"
                  />
                  <span>{option}</span>
                </label>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rule Builder Modal
// ---------------------------------------------------------------------------

function RuleModal({
  rule,
  triggerTypes,
  onSave,
  onClose,
}: {
  rule: Partial<AlertRule> | null;
  triggerTypes: AlertTriggerType[];
  onSave: (data: Partial<AlertRule>) => Promise<void>;
  onClose: () => void;
}) {
  const isEdit = rule?.id != null;
  const branding = getSiteBranding();
  const [form, setForm] = useState<Record<string, unknown>>({
    name: rule?.name ?? "",
    trigger_type: rule?.trigger_type ?? "stale",
    trigger_config: rule?.trigger_config ?? {},
    frequency: rule?.frequency ?? "daily",
    schedule_time: rule?.schedule_time ?? "08:00",
    schedule_days: rule?.schedule_days ?? "0,1,2,3,4",
    recipients: rule?.recipients ?? "",
    cc: rule?.cc ?? "",
    custom_subject: rule?.custom_subject ?? "",
    custom_message: rule?.custom_message ?? "",
    filters: rule?.filters ?? {},
    enabled: rule?.enabled ?? true,
  });

  const activeDays = useMemo(() => {
    const s = (form.schedule_days as string) || "0,1,2,3,4";
    return new Set(s.split(",").filter(Boolean).map(Number));
  }, [form.schedule_days]);

  function toggleDay(d: number) {
    const next = new Set(activeDays);
    if (next.has(d)) next.delete(d);
    else next.add(d);
    setForm({ ...form, schedule_days: [...next].sort().join(",") });
  }

  const triggerConfig = (form.trigger_config as Record<string, unknown>) ?? {};
  const configFields = TRIGGER_CONFIGS[form.trigger_type as string] ?? [];

  function setConfigField(field: string, value: number) {
    setForm({ ...form, trigger_config: { ...triggerConfig, [field]: value } });
  }

  const filterObj = (form.filters as Record<string, unknown>) ?? {};
  const selectedPriorities = ((filterObj.priorities as string[]) ?? []).filter(Boolean);
  const selectedAssignees = ((filterObj.assignees as string[]) ?? []).filter(Boolean);
  const selectedRequestTypes = ((filterObj.request_types as string[]) ?? []).filter(Boolean);

  const { data: filterOptions } = useQuery({
    queryKey: ["filter-options"],
    queryFn: () => api.getFilterOptions(),
    staleTime: 5 * 60 * 1000,
  });
  const { data: assignees = [] } = useQuery({
    queryKey: ["assignees"],
    queryFn: () => api.getAssignees(),
    staleTime: Infinity,
  });
  const { data: requestTypes = [] } = useQuery({
    queryKey: ["request-types"],
    queryFn: () => api.getRequestTypes(),
    staleTime: 5 * 60 * 1000,
  });

  const priorityOptions = filterOptions?.priorities ?? [];
  const assigneeOptions = assignees
    .map((assignee) => assignee.display_name)
    .filter(Boolean);
  const requestTypeOptions = requestTypes
    .map((requestType) => requestType.name)
    .filter(Boolean);

  const [saving, setSaving] = useState(false);

  function setFilterValues(field: "priorities" | "assignees" | "request_types", values: string[]) {
    const nextFilters = { ...filterObj };
    if (values.length > 0) {
      nextFilters[field] = sortOptionValues(values);
    } else {
      delete nextFilters[field];
    }
    setForm({ ...form, filters: nextFilters });
  }

  async function handleSubmit() {
    if (!(form.name as string)?.trim()) return alert("Name is required");
    if (!(form.recipients as string)?.trim()) return alert("Recipients are required");
    setSaving(true);
    try {
      await onSave(form as Partial<AlertRule>);
    } catch (err) {
      alert(`Failed to save: ${err}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-xl rounded-xl bg-white p-6 shadow-2xl max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-bold text-gray-900">{isEdit ? "Edit Alert Rule" : "Create Alert Rule"}</h2>

        <div className="mt-4 space-y-4">
          {/* Name */}
          <label className="block">
            <span className="text-sm font-medium text-gray-700">Rule Name</span>
            <input type="text" value={(form.name as string) ?? ""}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Daily Stale Ticket Alert"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
          </label>

          {/* Trigger Type */}
          <label className="block">
            <span className="text-sm font-medium text-gray-700">Trigger Type</span>
            <select value={(form.trigger_type as string) ?? "stale"}
              onChange={(e) => setForm({ ...form, trigger_type: e.target.value, trigger_config: {} })}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm">
              {triggerTypes.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>

          {(form.trigger_type as string) === "new_ticket" && (
            <p className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800">
              New ticket alerts only send for tickets the rule has not already seen. For cases like
              security notifications, use <span className="font-semibold">Every check (~1 min)</span> with
              <span className="font-semibold"> Request Types = Security Alert</span>.
            </p>
          )}

          {/* Trigger Config */}
          {configFields.length > 0 && (
            <div className="grid grid-cols-2 gap-3">
              {configFields.map((cf) => (
                <label key={cf.field} className="block">
                  <span className="text-xs text-gray-500">{cf.label}</span>
                  <input type="number" value={(triggerConfig[cf.field] as number) ?? cf.default}
                    onChange={(e) => setConfigField(cf.field, Number(e.target.value))}
                    className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
                </label>
              ))}
            </div>
          )}

          {/* Frequency */}
          <label className="block">
            <span className="text-sm font-medium text-gray-700">Frequency</span>
            <select value={(form.frequency as string) ?? "daily"}
              onChange={(e) => setForm({ ...form, frequency: e.target.value })}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm">
              {FREQUENCIES.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </label>

          {/* Schedule */}
          {(form.frequency === "daily" || form.frequency === "weekly") && (
            <div className="space-y-2">
              <label className="block">
                <span className="text-xs text-gray-500">Send at (UTC)</span>
                <input type="time" value={(form.schedule_time as string) ?? "08:00"}
                  onChange={(e) => setForm({ ...form, schedule_time: e.target.value })}
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
              </label>
              <div>
                <span className="text-xs text-gray-500">Active Days</span>
                <div className="mt-1 flex gap-1">
                  {DAY_NAMES.map((name, i) => (
                    <button key={i} onClick={() => toggleDay(i)}
                      className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                        activeDays.has(i) ? "bg-blue-100 text-blue-700 border border-blue-300" : "bg-gray-100 text-gray-400 border border-gray-200"
                      }`}>
                      {name}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Recipients */}
          <label className="block">
            <span className="text-sm font-medium text-gray-700">Recipients (comma-separated emails)</span>
            <input type="text" value={(form.recipients as string) ?? ""}
              onChange={(e) => setForm({ ...form, recipients: e.target.value })}
              placeholder="alice@example.com, bob@example.com"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm" />
          </label>

          <label className="block">
            <span className="text-xs text-gray-500">CC (optional)</span>
            <input type="text" value={(form.cc as string) ?? ""}
              onChange={(e) => setForm({ ...form, cc: e.target.value })}
              placeholder="manager@example.com"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
          </label>

          {/* Email Customization */}
          <div>
            <span className="text-sm font-medium text-gray-700">Email Customization (optional)</span>
            <p className="text-xs text-gray-400 mb-2">
              Use variables: <code className="bg-gray-100 px-1 rounded">{"{rule_name}"}</code>{" "}
              <code className="bg-gray-100 px-1 rounded">{"{trigger_label}"}</code>{" "}
              <code className="bg-gray-100 px-1 rounded">{"{ticket_count}"}</code>
            </p>
            <label className="block">
              <span className="text-xs text-gray-500">Subject Line</span>
              <input type="text" value={(form.custom_subject as string) ?? ""}
                onChange={(e) => setForm({ ...form, custom_subject: e.target.value })}
                placeholder={`Default: [${branding.alertPrefix} Alert] {rule_name}: {ticket_count} {trigger_label}`}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
            </label>
            <label className="mt-2 block">
              <span className="text-xs text-gray-500">Message Body (appears above ticket table)</span>
              <textarea value={(form.custom_message as string) ?? ""}
                onChange={(e) => setForm({ ...form, custom_message: e.target.value })}
                placeholder="e.g. The following {ticket_count} tickets need attention..."
                rows={3}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
            </label>
          </div>

          {/* Filters */}
          <div>
            <span className="text-sm font-medium text-gray-700">Filters (optional)</span>
            <p className="text-xs text-gray-400 mb-2">Restrict which tickets trigger this alert.</p>
            <div className="grid grid-cols-2 gap-3">
              <MultiSelectDropdown
                label="Priorities"
                placeholder="Any priority"
                options={priorityOptions}
                selected={selectedPriorities}
                onChange={(values) => setFilterValues("priorities", values)}
              />
              <MultiSelectDropdown
                label="Assignees"
                placeholder="Any assignee"
                options={assigneeOptions}
                selected={selectedAssignees}
                onChange={(values) => setFilterValues("assignees", values)}
              />
              <div className="col-span-2">
                <MultiSelectDropdown
                  label="Request Types"
                  placeholder="Any request type"
                  options={requestTypeOptions}
                  selected={selectedRequestTypes}
                  onChange={(values) => setFilterValues("request_types", values)}
                />
              </div>
            </div>
          </div>

          {/* Enabled */}
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={(form.enabled as boolean) ?? true}
              onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              className="h-4 w-4 rounded border-gray-300" />
            <span className="text-sm text-gray-700">Enabled</span>
          </label>
        </div>

        {/* Actions */}
        <div className="mt-6 flex justify-end gap-3">
          <button onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={handleSubmit} disabled={saving}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving..." : isEdit ? "Save Changes" : "Create Rule"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

function TestResultModal({
  testResult,
  onClose,
  onSend,
}: {
  testResult: AlertTestResult;
  onClose: () => void;
  onSend: () => Promise<void>;
}) {
  const [sending, setSending] = useState(false);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-bold text-gray-900">Test Result</h3>
        <p className="mt-2 text-sm text-gray-600">
          <span className="text-2xl font-bold text-blue-600">{testResult.matching_count}</span> tickets would trigger this alert.
        </p>
        {testResult.sample_keys.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-medium text-gray-500 mb-1">Sample tickets:</p>
            <div className="flex flex-wrap gap-1">
              {testResult.sample_keys.map((k) => (
                <span key={k} className="rounded bg-gray-100 px-2 py-0.5 text-xs font-mono text-gray-700">{k}</span>
              ))}
            </div>
          </div>
        )}
        <div className="mt-4 flex gap-2">
          {testResult.matching_count > 0 && (
            <button
              onClick={async () => { setSending(true); await onSend(); setSending(false); }}
              disabled={sending}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
              {sending ? "Sending..." : "Send Now"}
            </button>
          )}
          <button onClick={onClose}
            className="flex-1 rounded-lg bg-gray-100 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}


export default function AlertsPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editRule, setEditRule] = useState<AlertRule | null>(null);
  const [testResult, setTestResult] = useState<AlertTestResult | null>(null);
  const [tab, setTab] = useState<"rules" | "history">("rules");

  const { data: rules = [], isLoading } = useQuery({
    queryKey: ["alert-rules"],
    queryFn: () => api.getAlertRules(),
  });

  const { data: triggerTypes = [] } = useQuery({
    queryKey: ["alert-trigger-types"],
    queryFn: () => api.getAlertTriggerTypes(),
  });

  const { data: history = [] } = useQuery({
    queryKey: ["alert-history"],
    queryFn: () => api.getAlertHistory(100),
    enabled: tab === "history",
  });

  const triggerLabel = (val: string) =>
    triggerTypes.find((t) => t.value === val)?.label ?? val;

  async function handleSave(data: Partial<AlertRule>) {
    if (editRule?.id) {
      await api.updateAlertRule(editRule.id, data);
    } else {
      await api.createAlertRule(data);
    }
    qc.invalidateQueries({ queryKey: ["alert-rules"] });
    setShowModal(false);
    setEditRule(null);
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this alert rule?")) return;
    await api.deleteAlertRule(id);
    qc.invalidateQueries({ queryKey: ["alert-rules"] });
  }

  async function handleToggle(id: number) {
    await api.toggleAlertRule(id);
    qc.invalidateQueries({ queryKey: ["alert-rules"] });
  }

  async function handleTest(id: number) {
    const result = await api.testAlertRule(id);
    setTestResult(result);
  }

  async function handleRunAll() {
    const result = await api.runAlerts();
    alert(`Sent ${result.sent_count} alert email(s).`);
    qc.invalidateQueries({ queryKey: ["alert-rules"] });
    qc.invalidateQueries({ queryKey: ["alert-history"] });
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Email Alerts</h1>
          <p className="mt-1 text-sm text-gray-500">
            Configure automated email alerts for new tickets, SLA breaches, stale tickets, and more.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={handleRunAll}
            className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 shadow-sm">
            Run All Now
          </button>
          <button onClick={() => { setEditRule(null); setShowModal(true); }}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 shadow-sm">
            + New Alert Rule
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-6 -mb-px">
          {(["rules", "history"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                tab === t ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
              }`}>
              {t === "rules" ? `Rules (${rules.length})` : "Send History"}
            </button>
          ))}
        </nav>
      </div>

      {/* Rules Tab */}
      {tab === "rules" && (
        <div className="space-y-3">
          {isLoading && <p className="text-sm text-gray-500">Loading...</p>}
          {!isLoading && rules.length === 0 && (
            <div className="rounded-lg border border-dashed border-gray-300 p-10 text-center">
              <p className="text-sm text-gray-500">No alert rules yet. Create one to get started.</p>
            </div>
          )}
          {rules.map((rule) => (
            <div key={rule.id}
              className={`rounded-lg border bg-white p-5 shadow-sm transition-colors ${
                rule.enabled ? "border-gray-200" : "border-gray-100 opacity-60"
              }`}>
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <h3 className="text-base font-semibold text-gray-900">{rule.name}</h3>
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      rule.enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                    }`}>
                      {rule.enabled ? "Active" : "Paused"}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                    <span>Trigger: <span className="font-medium text-gray-700">{triggerLabel(rule.trigger_type)}</span></span>
                    <span>Frequency: <span className="font-medium text-gray-700 capitalize">{rule.frequency}</span></span>
                    <span>To: <span className="font-medium text-gray-700">{rule.recipients}</span></span>
                    {rule.last_sent && <span>Last sent: <span className="font-medium text-gray-700">{new Date(rule.last_sent).toLocaleString()}</span></span>}
                  </div>
                  {rule.trigger_config && Object.keys(rule.trigger_config).length > 0 && (
                    <div className="mt-1 text-xs text-gray-400">
                      Config: {JSON.stringify(rule.trigger_config)}
                    </div>
                  )}
                  {rule.filters && Object.keys(rule.filters).length > 0 && (
                    <div className="mt-1 text-xs text-gray-400">
                      Filters: {Object.entries(rule.filters).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`).join(" | ")}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 ml-4">
                  <button onClick={() => handleTest(rule.id)}
                    className="rounded px-2.5 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50 border border-blue-200">
                    Test
                  </button>
                  <button onClick={() => handleToggle(rule.id)}
                    className="rounded px-2.5 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 border border-gray-200">
                    {rule.enabled ? "Pause" : "Enable"}
                  </button>
                  <button onClick={() => { setEditRule(rule); setShowModal(true); }}
                    className="rounded px-2.5 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 border border-gray-200">
                    Edit
                  </button>
                  <button onClick={() => handleDelete(rule.id)}
                    className="rounded px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 border border-red-200">
                    Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* History Tab */}
      {tab === "history" && (
        <div className="rounded-lg bg-white shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">Sent At</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">Rule</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">Trigger</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">Recipients</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600 uppercase">Tickets</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {history.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-400">No alerts sent yet.</td></tr>
              )}
              {history.map((h) => (
                <tr key={h.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-xs text-gray-600">{new Date(h.sent_at).toLocaleString()}</td>
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{h.rule_name}</td>
                  <td className="px-4 py-3 text-xs text-gray-600">{triggerLabel(h.trigger_type)}</td>
                  <td className="px-4 py-3 text-xs text-gray-600">{h.recipients}</td>
                  <td className="px-4 py-3 text-right text-sm font-medium text-gray-900">{h.ticket_count}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      h.status === "sent" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                    }`}>
                      {h.status}
                    </span>
                    {h.error && <span className="ml-2 text-xs text-red-500">{h.error}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Test Result Modal */}
      {testResult && (
        <TestResultModal
          testResult={testResult}
          onClose={() => setTestResult(null)}
          onSend={async () => {
            const result = await api.sendAlertRule(testResult.rule.id);
            if (result.sent) {
              alert(`Email sent successfully to ${testResult.rule.recipients} (${result.matching_count} tickets)`);
              qc.invalidateQueries({ queryKey: ["alert-rules"] });
              qc.invalidateQueries({ queryKey: ["alert-history"] });
            } else {
              alert(`Send failed: ${result.reason || "Email delivery failed"}`);
            }
            setTestResult(null);
          }}
        />
      )}

      {/* Create/Edit Modal */}
      {showModal && (
        <RuleModal
          rule={editRule}
          triggerTypes={triggerTypes}
          onSave={handleSave}
          onClose={() => { setShowModal(false); setEditRule(null); }}
        />
      )}
    </div>
  );
}
