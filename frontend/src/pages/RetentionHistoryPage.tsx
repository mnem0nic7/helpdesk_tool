import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";

const RUNS_LIMIT = 50;
const DELETIONS_LIMIT = 100;

export default function RetentionHistoryPage() {
  const [selectedPolicyId, setSelectedPolicyId] = useState<string | undefined>(undefined);
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(undefined);
  const [runsOffset, setRunsOffset] = useState(0);
  const [deletionsOffset, setDeletionsOffset] = useState(0);

  const policiesQuery = useQuery({
    queryKey: ["retention", "policies"],
    queryFn: () => api.getRetentionPolicies(100, 0),
  });

  const runsQuery = useQuery({
    queryKey: ["retention", "runs", selectedPolicyId, runsOffset],
    queryFn: () => api.getRetentionRuns(selectedPolicyId, RUNS_LIMIT, runsOffset),
  });

  const deletionsQuery = useQuery({
    queryKey: ["retention", "deletions", selectedRunId, deletionsOffset],
    queryFn: () => api.getRetentionDeletions(selectedRunId, DELETIONS_LIMIT, deletionsOffset),
    enabled: !!selectedRunId,
  });

  function selectPolicy(policyId: string | undefined) {
    setSelectedPolicyId(policyId);
    setRunsOffset(0);
    setSelectedRunId(undefined);
    setDeletionsOffset(0);
  }

  function selectRun(runId: string) {
    setSelectedRunId(runId);
    setDeletionsOffset(0);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Policy History</h1>

      <div>
        <label className="text-sm font-medium">Filter by policy</label>
        <select
          value={selectedPolicyId ?? ""}
          onChange={(e) => selectPolicy(e.target.value || undefined)}
          className="mt-1 block rounded border border-slate-300 px-2 py-1 text-sm"
        >
          <option value="">All policies</option>
          {(policiesQuery.data?.items ?? []).map((policy) => (
            <option key={policy.id} value={policy.id}>
              {policy.team_name} / {policy.channel_name} ({policy.retention_days}d)
            </option>
          ))}
        </select>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-slate-500">
            <th className="py-1 pr-4">Started</th>
            <th className="pr-4">Outcome</th>
            <th className="pr-4">Messages</th>
            <th className="pr-4">Attachments</th>
            <th className="pr-4">Error</th>
          </tr>
        </thead>
        <tbody>
          {(runsQuery.data?.items ?? []).map((run) => (
            <tr
              key={run.id}
              onClick={() => selectRun(run.id)}
              className={`cursor-pointer border-t border-slate-100 ${selectedRunId === run.id ? "bg-blue-50" : ""}`}
            >
              <td className="py-1 pr-4">{run.started_at}</td>
              <td className="pr-4">{run.outcome}</td>
              <td className="pr-4">{run.messages_deleted}</td>
              <td className="pr-4">{run.attachments_deleted}</td>
              <td className="pr-4 text-red-600">{run.error ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center justify-end gap-2 text-xs text-slate-500">
        <button
          type="button"
          onClick={() => setRunsOffset((offset) => Math.max(0, offset - RUNS_LIMIT))}
          disabled={runsOffset === 0}
          className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
        >
          Previous
        </button>
        <button
          type="button"
          onClick={() => setRunsOffset((offset) => offset + RUNS_LIMIT)}
          disabled={runsOffset + RUNS_LIMIT >= (runsQuery.data?.total ?? 0)}
          className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
        >
          Next
        </button>
      </div>

      {selectedRunId && (
        <div>
          <h2 className="text-sm font-semibold">Deletions for run {selectedRunId}</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="py-1 pr-4">Type</th>
                <th className="pr-4">Sender/Author</th>
                <th className="pr-4">Original Date</th>
                <th className="pr-4">Deleted At</th>
                <th className="pr-4">Status</th>
              </tr>
            </thead>
            <tbody>
              {(deletionsQuery.data?.items ?? []).map((deletion) => (
                <tr key={deletion.id} className="border-t border-slate-100">
                  <td className="py-1 pr-4">{deletion.item_type}</td>
                  <td className="pr-4">{deletion.sender_or_author}</td>
                  <td className="pr-4">{deletion.original_created_at}</td>
                  <td className="pr-4">{deletion.deleted_at}</td>
                  <td className="pr-4">{deletion.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex items-center justify-end gap-2 text-xs text-slate-500">
            <button
              type="button"
              onClick={() => setDeletionsOffset((offset) => Math.max(0, offset - DELETIONS_LIMIT))}
              disabled={deletionsOffset === 0}
              className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
            >
              Previous
            </button>
            <button
              type="button"
              onClick={() => setDeletionsOffset((offset) => offset + DELETIONS_LIMIT)}
              disabled={deletionsOffset + DELETIONS_LIMIT >= (deletionsQuery.data?.total ?? 0)}
              className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
