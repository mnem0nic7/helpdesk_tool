import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type RetentionChannel, type RetentionTeam } from "../lib/api.ts";

export default function RetentionTeamsPage() {
  const queryClient = useQueryClient();
  const [expandedTeamId, setExpandedTeamId] = useState<string | null>(null);
  const [configuringChannel, setConfiguringChannel] = useState<{ team: RetentionTeam; channel: RetentionChannel } | null>(null);
  const [days, setDays] = useState(30);
  const [previewPolicyId, setPreviewPolicyId] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ["retention", "connection-status"],
    queryFn: () => api.getRetentionConnectionStatus(),
  });

  const teamsQuery = useQuery({
    queryKey: ["retention", "teams"],
    queryFn: () => api.getRetentionTeams(100, 0),
    enabled: statusQuery.data?.status === "connected",
  });

  const channelsQuery = useQuery({
    queryKey: ["retention", "channels", expandedTeamId],
    queryFn: () => api.getRetentionChannels(expandedTeamId as string, 100, 0),
    enabled: !!expandedTeamId,
  });

  const createMutation = useMutation({
    mutationFn: (input: { team: RetentionTeam; channel: RetentionChannel; retentionDays: number }) =>
      api.createRetentionPolicy({
        team_id: input.team.id,
        team_name: input.team.name,
        channel_id: input.channel.id,
        channel_name: input.channel.name,
        retention_days: input.retentionDays,
      }),
    onSuccess: (policy) => {
      setPreviewPolicyId(policy.id);
      queryClient.invalidateQueries({ queryKey: ["retention", "channels", expandedTeamId] });
    },
  });

  const previewQuery = useQuery({
    queryKey: ["retention", "preview", previewPolicyId],
    queryFn: () => api.getRetentionPolicyPreview(previewPolicyId as string),
    enabled: !!previewPolicyId,
  });

  const confirmMutation = useMutation({
    mutationFn: (policyId: string) => api.confirmRetentionPolicy(policyId),
    onSuccess: () => {
      setConfiguringChannel(null);
      setPreviewPolicyId(null);
      queryClient.invalidateQueries({ queryKey: ["retention", "channels", expandedTeamId] });
    },
  });

  if (statusQuery.data && statusQuery.data.status !== "connected") {
    return (
      <div className="rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
        <p className="font-medium">Service account not connected</p>
        <p className="mt-1">
          {statusQuery.data.last_error || "Connect the retention service account to browse Teams and channels."}
        </p>
        <a href="/api/retention/connection/connect" className="mt-2 inline-block rounded bg-amber-600 px-3 py-1.5 text-white">
          Connect service account
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Teams &amp; Channels</h1>
      <div className="divide-y divide-slate-200 rounded-md border border-slate-200">
        {(teamsQuery.data?.items ?? []).map((team) => (
          <div key={team.id}>
            <button
              onClick={() => setExpandedTeamId(expandedTeamId === team.id ? null : team.id)}
              className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium hover:bg-slate-50"
            >
              <span>{team.name}</span>
              <span className="text-xs text-slate-500">
                {team.policy_count} active polic{team.policy_count === 1 ? "y" : "ies"}
              </span>
            </button>
            {expandedTeamId === team.id && (
              <div className="divide-y divide-slate-100 bg-slate-50 px-4">
                {(channelsQuery.data?.items ?? []).map((channel) => (
                  <div key={channel.id} className="flex items-center justify-between py-2 text-sm">
                    <span>{channel.name}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-500">
                        {channel.policy ? `${channel.policy.status}, ${channel.policy.retention_days}d` : "No policy"}
                      </span>
                      {!channel.policy && (
                        <button
                          onClick={() => setConfiguringChannel({ team, channel })}
                          className="rounded bg-blue-600 px-2 py-1 text-xs text-white"
                        >
                          Configure retention
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {configuringChannel && (
        <div className="rounded-md border border-slate-300 bg-white p-4 shadow-sm">
          <h2 className="text-sm font-semibold">
            Configure retention for {configuringChannel.channel.name} ({configuringChannel.team.name})
          </h2>
          {!previewPolicyId ? (
            <div className="mt-3 flex items-center gap-2">
              <label className="text-sm">Retain messages for</label>
              <input
                type="number"
                min={1}
                max={365}
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="w-20 rounded border border-slate-300 px-2 py-1 text-sm"
              />
              <span className="text-sm">days</span>
              <button
                onClick={() =>
                  createMutation.mutate({ team: configuringChannel.team, channel: configuringChannel.channel, retentionDays: days })
                }
                disabled={createMutation.isPending}
                className="rounded bg-blue-600 px-3 py-1.5 text-sm text-white"
              >
                Preview
              </button>
            </div>
          ) : (
            <div className="mt-3 space-y-2 text-sm">
              {previewQuery.isLoading ? (
                <p>Computing preview...</p>
              ) : (
                <>
                  <p>
                    This will delete approximately <strong>{previewQuery.data?.messages_count ?? 0}</strong> message(s) and{" "}
                    <strong>{previewQuery.data?.attachments_count ?? 0}</strong> attachment(s) older than {days} days
                    {previewQuery.data?.oldest_message_at ? `, oldest dated ${previewQuery.data.oldest_message_at}` : ""}.
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => confirmMutation.mutate(previewPolicyId)}
                      disabled={confirmMutation.isPending}
                      className="rounded bg-red-600 px-3 py-1.5 text-white"
                    >
                      Confirm &amp; Enable
                    </button>
                    <button
                      onClick={() => {
                        setConfiguringChannel(null);
                        setPreviewPolicyId(null);
                      }}
                      className="rounded border border-slate-300 px-3 py-1.5"
                    >
                      Cancel
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
