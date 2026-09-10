import { useDeferredValue, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type RetentionChannel, type RetentionTeam } from "../lib/api.ts";

const TEAMS_LIMIT = 50;
const CHANNELS_LIMIT = 50;

export default function RetentionTeamsPage() {
  const queryClient = useQueryClient();
  const [expandedTeamId, setExpandedTeamId] = useState<string | null>(null);
  const [configuringChannel, setConfiguringChannel] = useState<{ team: RetentionTeam; channel: RetentionChannel } | null>(null);
  const [days, setDays] = useState(30);
  const [previewPolicyId, setPreviewPolicyId] = useState<string | null>(null);
  const [teamsOffset, setTeamsOffset] = useState(0);
  const [channelsOffset, setChannelsOffset] = useState(0);
  const [teamsSearch, setTeamsSearch] = useState("");
  const [channelsSearch, setChannelsSearch] = useState("");
  // Matching a channel name at the top level means Graph-fanning-out to every team's
  // channel list (see the backend route) — deferring the value keeps fast typing from
  // firing that expensive search on every keystroke while still needing no manual
  // debounce timer.
  const deferredTeamsSearch = useDeferredValue(teamsSearch);
  const deferredChannelsSearch = useDeferredValue(channelsSearch);

  const statusQuery = useQuery({
    queryKey: ["retention", "connection-status"],
    queryFn: () => api.getRetentionConnectionStatus(),
  });

  const teamsQuery = useQuery({
    queryKey: ["retention", "teams", teamsOffset, deferredTeamsSearch],
    queryFn: () => api.getRetentionTeams(TEAMS_LIMIT, teamsOffset, deferredTeamsSearch),
    enabled: statusQuery.data?.status === "connected",
  });
  // True while React is still rendering the stale list under the deferred value, and
  // while the (potentially slow, channel-fan-out) request for the new value is in
  // flight — covers the whole "user is waiting on a fresh result" window.
  const isSearchingTeams = teamsSearch !== deferredTeamsSearch || teamsQuery.isFetching;

  const channelsQuery = useQuery({
    queryKey: ["retention", "channels", expandedTeamId, channelsOffset, deferredChannelsSearch],
    queryFn: () => api.getRetentionChannels(expandedTeamId as string, CHANNELS_LIMIT, channelsOffset, deferredChannelsSearch),
    enabled: !!expandedTeamId,
  });

  useEffect(() => {
    setTeamsOffset(0);
  }, [deferredTeamsSearch]);

  useEffect(() => {
    setChannelsOffset(0);
  }, [deferredChannelsSearch]);

  function toggleTeam(teamId: string) {
    setExpandedTeamId((current) => (current === teamId ? null : teamId));
    setChannelsOffset(0);
    // Prefill with the top search term: a team that only matched via one of its
    // channels (not its own name) should open with that channel already filtered.
    setChannelsSearch(teamsSearch);
  }

  function handleTeamsSearchChange(value: string) {
    setTeamsSearch(value);
  }

  function handleChannelsSearchChange(value: string) {
    setChannelsSearch(value);
  }

  const createMutation = useMutation({
    mutationFn: (input: { team: RetentionTeam; channel: RetentionChannel; retentionDays: number }) => {
      const existingPolicy = input.channel.policy;
      if (existingPolicy) {
        return api.patchRetentionPolicy(existingPolicy.id, { retention_days: input.retentionDays });
      }
      return api.createRetentionPolicy({
        team_id: input.team.id,
        team_name: input.team.name,
        channel_id: input.channel.id,
        channel_name: input.channel.name,
        retention_days: input.retentionDays,
      });
    },
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
      queryClient.invalidateQueries({ queryKey: ["retention", "teams"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (policyId: string) => api.patchRetentionPolicy(policyId, { status: "disabled" }),
    onSuccess: () => {
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
      <div>
        <div className="flex max-w-sm items-center gap-2">
          <input
            type="search"
            value={teamsSearch}
            onChange={(e) => handleTeamsSearchChange(e.target.value)}
            placeholder="Search teams and channels..."
            aria-label="Search teams"
            className="block w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
          />
          {isSearchingTeams && <span className="whitespace-nowrap text-xs text-slate-500">Searching...</span>}
        </div>
        <p className="mt-1 text-xs text-slate-400">
          Team names are always live. Channel-name matches use a periodically refreshed cached snapshot, so a
          just-renamed or just-created channel may not show up immediately.
        </p>
      </div>
      {teamsQuery.isError && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {teamsQuery.error instanceof Error ? teamsQuery.error.message : "Failed to load teams"}
        </div>
      )}
      <div className="divide-y divide-slate-200 rounded-md border border-slate-200">
        {(teamsQuery.data?.items ?? []).map((team) => (
          <div key={team.id}>
            <button
              onClick={() => toggleTeam(team.id)}
              className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium hover:bg-slate-50"
            >
              <span>{team.name}</span>
              <span className="text-xs text-slate-500">
                {team.policy_count} active polic{team.policy_count === 1 ? "y" : "ies"}
              </span>
            </button>
            {expandedTeamId === team.id && (
              <div className="divide-y divide-slate-100 bg-slate-50 px-4">
                <input
                  type="search"
                  value={channelsSearch}
                  onChange={(e) => handleChannelsSearchChange(e.target.value)}
                  placeholder="Search channels..."
                  aria-label="Search channels"
                  className="mt-2 block w-full max-w-xs rounded border border-slate-300 px-2 py-1 text-sm"
                />
                {channelsQuery.isError ? (
                  <p className="py-2 text-sm text-red-700">
                    {channelsQuery.error instanceof Error ? channelsQuery.error.message : "Failed to load channels"}
                  </p>
                ) : null}
                {(channelsQuery.isError ? [] : channelsQuery.data?.items ?? []).map((channel) => (
                  <div key={channel.id} className="flex items-center justify-between py-2 text-sm">
                    <span>{channel.name}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-500">
                        {channel.policy ? `${channel.policy.status}, ${channel.policy.retention_days}d` : "No policy"}
                      </span>
                      {(!channel.policy || channel.policy.status === "disabled") && (
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
                {!channelsQuery.isError && (
                  <div className="flex items-center justify-end gap-2 py-2 text-xs text-slate-500">
                    <button
                      type="button"
                      onClick={() => setChannelsOffset((offset) => Math.max(0, offset - CHANNELS_LIMIT))}
                      disabled={channelsOffset === 0}
                      className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-100 disabled:opacity-50"
                    >
                      Previous
                    </button>
                    <button
                      type="button"
                      onClick={() => setChannelsOffset((offset) => offset + CHANNELS_LIMIT)}
                      disabled={channelsOffset + CHANNELS_LIMIT >= (channelsQuery.data?.total ?? 0)}
                      className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-100 disabled:opacity-50"
                    >
                      Next
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
      {teamsQuery.data && teamsQuery.data.total > 0 && (
        <div className="flex items-center justify-end gap-2 text-xs text-slate-500">
          <button
            type="button"
            onClick={() => setTeamsOffset((offset) => Math.max(0, offset - TEAMS_LIMIT))}
            disabled={teamsOffset === 0}
            className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
          >
            Previous
          </button>
          <button
            type="button"
            onClick={() => setTeamsOffset((offset) => offset + TEAMS_LIMIT)}
            disabled={teamsOffset + TEAMS_LIMIT >= teamsQuery.data.total}
            className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}

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
              {createMutation.isError && (
                <span className="text-sm text-red-700">
                  {createMutation.error instanceof Error ? createMutation.error.message : "Failed to save policy"}
                </span>
              )}
            </div>
          ) : (
            <div className="mt-3 space-y-2 text-sm">
              {previewQuery.isLoading ? (
                <p>Computing preview...</p>
              ) : previewQuery.isError ? (
                // Never fall through to the success branch on error: `data` would be
                // undefined, rendering a fabricated "0 messages / 0 attachments" next to
                // a live Confirm & Enable button, which would arm a policy that purges
                // the real backlog on the next hourly pass. Confirm is only reachable
                // from the success branch below.
                <div className="space-y-2">
                  <p className="text-red-700">
                    Unable to compute preview:{" "}
                    {previewQuery.error instanceof Error ? previewQuery.error.message : "Unknown error"}
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => previewQuery.refetch()}
                      className="rounded bg-blue-600 px-3 py-1.5 text-white"
                    >
                      Retry
                    </button>
                    <button
                      onClick={() => {
                        cancelMutation.mutate(previewPolicyId);
                        setConfiguringChannel(null);
                        setPreviewPolicyId(null);
                      }}
                      className="rounded border border-slate-300 px-3 py-1.5"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
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
                        cancelMutation.mutate(previewPolicyId);
                        setConfiguringChannel(null);
                        setPreviewPolicyId(null);
                      }}
                      className="rounded border border-slate-300 px-3 py-1.5"
                    >
                      Cancel
                    </button>
                  </div>
                  {confirmMutation.isError && (
                    <p className="text-red-700">
                      {confirmMutation.error instanceof Error
                        ? confirmMutation.error.message
                        : "Failed to enable policy"}
                    </p>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
