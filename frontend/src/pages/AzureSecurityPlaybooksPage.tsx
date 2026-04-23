import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { DefenderAgentPlaybook } from "../lib/api";

const ACTION_TYPES = [
  "revoke_sessions",
  "disable_sign_in",
  "account_lockout",
  "reset_password",
  "device_sync",
  "run_av_scan",
  "isolate_device",
  "unisolate_device",
  "device_wipe",
  "device_retire",
  "restrict_app_execution",
  "unrestrict_app_execution",
  "start_investigation",
  "collect_investigation_package",
  "stop_and_quarantine_file",
  "create_block_indicator",
];

const ACTION_LABELS: Record<string, string> = {
  revoke_sessions: "Revoke Sessions",
  disable_sign_in: "Disable Sign-In",
  account_lockout: "Account Lockout (revoke + disable)",
  reset_password: "Reset Password",
  device_sync: "Device Sync",
  run_av_scan: "Run AV Scan",
  isolate_device: "Isolate Device",
  unisolate_device: "Unisolate Device",
  device_wipe: "Device Wipe",
  device_retire: "Device Retire",
  restrict_app_execution: "Restrict App Execution",
  unrestrict_app_execution: "Unrestrict App Execution",
  start_investigation: "Start Investigation",
  collect_investigation_package: "Collect Investigation Package",
  stop_and_quarantine_file: "Stop & Quarantine File",
  create_block_indicator: "Create Block Indicator",
};

const TIER_SAFE: Record<string, string> = {
  revoke_sessions: "T1",
  disable_sign_in: "T2",
  account_lockout: "T2",
  reset_password: "T3",
  device_sync: "T1",
  run_av_scan: "T1",
  isolate_device: "T2",
  unisolate_device: "T2",
  device_wipe: "T3",
  device_retire: "T3",
  restrict_app_execution: "T3",
  unrestrict_app_execution: "T2",
  start_investigation: "T1",
  collect_investigation_package: "T2",
  stop_and_quarantine_file: "T1",
  create_block_indicator: "T2",
};

const TIER_COLOR: Record<string, string> = {
  T1: "bg-red-100 text-red-700",
  T2: "bg-amber-100 text-amber-700",
  T3: "bg-slate-100 text-slate-600",
};

function ActionBadge({ action }: { action: string }) {
  const tier = TIER_SAFE[action] || "";
  return (
    <span className="flex items-center gap-1.5">
      <span className="font-mono text-xs text-slate-700">{action}</span>
      {tier && (
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${TIER_COLOR[tier] || ""}`}>{tier}</span>
      )}
    </span>
  );
}

interface EditorProps {
  playbook: DefenderAgentPlaybook | null;
  onClose: () => void;
  isAdmin: boolean;
}

function PlaybookEditor({ playbook, onClose, isAdmin }: EditorProps) {
  const qc = useQueryClient();
  const isNew = playbook === null;

  const [name, setName] = useState(playbook?.name ?? "");
  const [description, setDescription] = useState(playbook?.description ?? "");
  const [actions, setActions] = useState<string[]>(playbook?.actions ?? []);
  const [addAction, setAddAction] = useState(ACTION_TYPES[0]);
  const [error, setError] = useState("");

  const rulesQuery = useQuery({
    queryKey: ["playbook-rules", playbook?.id],
    queryFn: () => api.listPlaybookRules(playbook!.id),
    enabled: !isNew,
  });

  const createMut = useMutation({
    mutationFn: () => api.createDefenderAgentPlaybook({ name: name.trim(), description: description.trim(), actions }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["defender-playbooks"] }); onClose(); },
    onError: (e: Error) => setError(e.message),
  });

  const updateMut = useMutation({
    mutationFn: () => api.updateDefenderAgentPlaybook(playbook!.id, { name: name.trim(), description: description.trim(), actions }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["defender-playbooks"] }); onClose(); },
    onError: (e: Error) => setError(e.message),
  });

  const deleteMut = useMutation({
    mutationFn: () => api.deleteDefenderAgentPlaybook(playbook!.id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["defender-playbooks"] }); onClose(); },
    onError: (e: Error) => setError(e.message),
  });

  const toggleMut = useMutation({
    mutationFn: () => api.updateDefenderAgentPlaybook(playbook!.id, { enabled: !playbook!.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["defender-playbooks"] }),
    onError: (e: Error) => setError(e.message),
  });

  function moveAction(idx: number, dir: -1 | 1) {
    const next = [...actions];
    const swap = idx + dir;
    if (swap < 0 || swap >= next.length) return;
    [next[idx], next[swap]] = [next[swap], next[idx]];
    setActions(next);
  }

  const saving = createMut.isPending || updateMut.isPending;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-800">
          {isNew ? "New Playbook" : name}
        </h3>
        {!isNew && isAdmin && (
          <div className="flex gap-2">
            <button
              onClick={() => toggleMut.mutate()}
              className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
            >
              {playbook!.enabled ? "Disable" : "Enable"}
            </button>
            <button
              onClick={() => { if (confirm("Delete this playbook?")) deleteMut.mutate(); }}
              className="rounded border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
            >
              Delete
            </button>
          </div>
        )}
      </div>

      {isAdmin ? (
        <>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Name</label>
            <input
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Account Lockout"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Description</label>
            <textarea
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              rows={2}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional — describe when to use this playbook"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Actions (in order)</label>
            {actions.length === 0 && (
              <p className="mb-2 text-xs text-slate-400">No actions yet — add at least one.</p>
            )}
            <div className="flex flex-col gap-1">
              {actions.map((a, i) => (
                <div key={i} className="flex items-center gap-2 rounded border border-slate-200 bg-slate-50 px-3 py-2">
                  <span className="w-5 text-center text-xs font-mono text-slate-400">{i + 1}</span>
                  <ActionBadge action={a} />
                  <span className="ml-auto flex gap-1">
                    <button onClick={() => moveAction(i, -1)} disabled={i === 0} className="rounded px-1 py-0.5 text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30">↑</button>
                    <button onClick={() => moveAction(i, 1)} disabled={i === actions.length - 1} className="rounded px-1 py-0.5 text-xs text-slate-400 hover:text-slate-700 disabled:opacity-30">↓</button>
                    <button onClick={() => setActions(actions.filter((_, j) => j !== i))} className="rounded px-1 py-0.5 text-xs text-red-400 hover:text-red-700">×</button>
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-2 flex gap-2">
              <select
                className="flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm"
                value={addAction}
                onChange={e => setAddAction(e.target.value)}
              >
                {ACTION_TYPES.map(a => (
                  <option key={a} value={a}>{ACTION_LABELS[a] || a} ({TIER_SAFE[a]})</option>
                ))}
              </select>
              <button
                onClick={() => setActions([...actions, addAction])}
                className="rounded bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-700"
              >
                + Add
              </button>
            </div>
          </div>

          {error && <p className="text-xs text-red-600">{error}</p>}

          <div className="flex gap-2 pt-1">
            <button
              onClick={() => isNew ? createMut.mutate() : updateMut.mutate()}
              disabled={saving || !name.trim() || actions.length === 0}
              className="rounded bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? "Saving…" : isNew ? "Create Playbook" : "Save Changes"}
            </button>
            <button onClick={onClose} className="rounded border border-slate-300 px-4 py-1.5 text-sm text-slate-600 hover:bg-slate-50">
              Cancel
            </button>
          </div>
        </>
      ) : (
        <div className="flex flex-col gap-3">
          {description && <p className="text-sm text-slate-600">{description}</p>}
          <div>
            <p className="mb-1 text-xs font-medium text-slate-500">Actions (in order)</p>
            <div className="flex flex-col gap-1">
              {actions.map((a, i) => (
                <div key={i} className="flex items-center gap-2 rounded border border-slate-200 bg-slate-50 px-3 py-2">
                  <span className="w-5 text-center text-xs font-mono text-slate-400">{i + 1}</span>
                  <ActionBadge action={a} />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {!isNew && (
        <div className="border-t border-slate-200 pt-3">
          <p className="mb-2 text-xs font-medium text-slate-500">Rules using this playbook</p>
          {rulesQuery.isLoading && <p className="text-xs text-slate-400">Loading…</p>}
          {rulesQuery.data && rulesQuery.data.length === 0 && (
            <p className="text-xs text-slate-400">No custom rules assigned yet.</p>
          )}
          {rulesQuery.data && rulesQuery.data.length > 0 && (
            <div className="flex flex-col gap-1">
              {rulesQuery.data.map(r => (
                <div key={r.id} className="flex items-center justify-between rounded border border-slate-200 px-3 py-1.5 text-xs">
                  <span className="font-medium text-slate-700">{r.name || r.id}</span>
                  <span className="text-slate-400">{r.match_field} {r.match_mode} "{r.match_value}"</span>
                  <span className={`rounded px-1.5 py-0.5 font-medium ${r.enabled ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-500"}`}>
                    {r.enabled ? "enabled" : "disabled"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AzureSecurityPlaybooksPage() {
  const { data: me } = useQuery({ queryKey: ["auth", "me"], queryFn: () => api.getMe(), staleTime: 5 * 60 * 1000 });
  const isAdmin = me?.is_admin ?? false;

  const [selected, setSelected] = useState<DefenderAgentPlaybook | null | "new">(null);

  const playbooksQuery = useQuery({
    queryKey: ["defender-playbooks"],
    queryFn: () => api.listDefenderAgentPlaybooks(),
    staleTime: 30_000,
  });

  const playbooks = playbooksQuery.data ?? [];

  function handleSelect(pb: DefenderAgentPlaybook) {
    setSelected(pb);
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Defender Agent Playbooks</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Named action sequences assigned to custom detection rules. Each playbook defines an ordered list of remediation actions.
          </p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setSelected("new")}
            className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            + New Playbook
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* List */}
        <div className="flex flex-col gap-2 lg:col-span-1">
          {playbooksQuery.isLoading && <p className="text-sm text-slate-400">Loading…</p>}
          {!playbooksQuery.isLoading && playbooks.length === 0 && (
            <div className="rounded-lg border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-400">
              No playbooks yet.{isAdmin && " Click \"+ New Playbook\" to create one."}
            </div>
          )}
          {playbooks.map(pb => (
            <button
              key={pb.id}
              onClick={() => handleSelect(pb)}
              className={`rounded-lg border p-3 text-left transition-colors ${
                selected !== "new" && (selected as DefenderAgentPlaybook)?.id === pb.id
                  ? "border-indigo-400 bg-indigo-50"
                  : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-medium text-slate-800 text-sm">{pb.name}</span>
                <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${pb.enabled ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-500"}`}>
                  {pb.enabled ? "enabled" : "disabled"}
                </span>
              </div>
              {pb.description && (
                <p className="mt-0.5 text-xs text-slate-500 line-clamp-1">{pb.description}</p>
              )}
              <p className="mt-1 text-xs text-slate-400">
                {pb.actions.length} action{pb.actions.length !== 1 ? "s" : ""}: {pb.actions.slice(0, 3).join(", ")}{pb.actions.length > 3 ? "…" : ""}
              </p>
            </button>
          ))}
        </div>

        {/* Editor / detail panel */}
        <div className="rounded-lg border border-slate-200 bg-white p-4 lg:col-span-2">
          {selected === null && (
            <p className="text-sm text-slate-400">Select a playbook to view or edit, or create a new one.</p>
          )}
          {selected === "new" && (
            <PlaybookEditor
              playbook={null}
              onClose={() => setSelected(null)}
              isAdmin={isAdmin}
            />
          )}
          {selected !== null && selected !== "new" && (
            <PlaybookEditor
              key={(selected as DefenderAgentPlaybook).id}
              playbook={selected as DefenderAgentPlaybook}
              onClose={() => setSelected(null)}
              isAdmin={isAdmin}
            />
          )}
        </div>
      </div>
    </div>
  );
}
