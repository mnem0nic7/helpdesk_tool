import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";

export default function RetentionHistoryPage() {
  const [selectedPolicyId, setSelectedPolicyId] = useState<string | undefined>(undefined);
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>(undefined);

  const policiesQuery = useQuery({
    queryKey: ["retention", "policies"],
    queryFn: () => api.getRetentionPolicies(100, 0),
  });

  const runsQuery = useQuery({
    queryKey: ["retention", "runs", selectedPolicyId],
    queryFn: () => api.getRetentionRuns(selectedPolicyId, 50, 0),
  });

  const deletionsQuery = useQuery({
    queryKey: ["retention", "deletions", selectedRunId],
    queryFn: () => api.getRetentionDeletions(selectedRunId, 100, 0),
    enabled: !!selectedRunId,
  });

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Policy History</h1>

      <div>
        <label className="text-sm font-medium">Filter by policy</label>
        <select
          value={selectedPolicyId ?? ""}
          onChange={(e) => setSelectedPolicyId(e.target.value || undefined)}
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
            <th className="py-1">Started</th>
            <th>Outcome</th>
            <th>Messages</th>
            <th>Attachments</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {(runsQuery.data?.items ?? []).map((run) => (
            <tr
              key={run.id}
              onClick={() => setSelectedRunId(run.id)}
              className={`cursor-pointer border-t border-slate-100 ${selectedRunId === run.id ? "bg-blue-50" : ""}`}
            >
              <td className="py-1">{run.started_at}</td>
              <td>{run.outcome}</td>
              <td>{run.messages_deleted}</td>
              <td>{run.attachments_deleted}</td>
              <td className="text-red-600">{run.error ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {selectedRunId && (
        <div>
          <h2 className="text-sm font-semibold">Deletions for run {selectedRunId}</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase text-slate-500">
                <th className="py-1">Type</th>
                <th>Sender/Author</th>
                <th>Original Date</th>
                <th>Deleted At</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(deletionsQuery.data?.items ?? []).map((deletion) => (
                <tr key={deletion.id} className="border-t border-slate-100">
                  <td className="py-1">{deletion.item_type}</td>
                  <td>{deletion.sender_or_author}</td>
                  <td>{deletion.original_created_at}</td>
                  <td>{deletion.deleted_at}</td>
                  <td>{deletion.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
