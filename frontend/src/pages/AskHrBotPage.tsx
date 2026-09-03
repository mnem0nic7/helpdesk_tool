import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AskHrBotMessage } from "../lib/api.ts";
import { getPollingQueryOptions } from "../lib/queryPolling.ts";

const RUNS_LIMIT = 30;
const MESSAGES_LIMIT = 50;

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

export default function AskHrBotPage() {
  const queryClient = useQueryClient();
  const [runsOffset, setRunsOffset] = useState(0);
  const [messagesOffset, setMessagesOffset] = useState(0);

  const statusQuery = useQuery({
    queryKey: ["askhr-bot", "status"],
    queryFn: () => api.getAskHrBotStatus(),
    ...getPollingQueryOptions("slow_5m"),
  });

  const runsQuery = useQuery({
    queryKey: ["askhr-bot", "runs", runsOffset],
    queryFn: () => api.getAskHrBotRuns(undefined, RUNS_LIMIT, runsOffset),
    ...getPollingQueryOptions("slow_5m"),
  });

  const messagesQuery = useQuery({
    queryKey: ["askhr-bot", "messages", messagesOffset],
    queryFn: () => api.getAskHrBotMessages(undefined, undefined, MESSAGES_LIMIT, messagesOffset),
    ...getPollingQueryOptions("slow_5m"),
  });

  const settingsMutation = useMutation({
    mutationFn: (body: { enabled?: boolean }) => api.patchAskHrBotSettings(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["askhr-bot", "status"] }),
  });

  const reporterModeResetMutation = useMutation({
    mutationFn: () => api.resetAskHrBotReporterMode(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["askhr-bot", "status"] }),
  });

  const retryMutation = useMutation({
    // Both parts of the message identity are required: the same email can be
    // addressed to both AskHR@ and Benefits@, each with its own ticket.
    mutationFn: (target: { internetMessageId: string; mailbox: string }) =>
      api.retryAskHrBotMessage(target.internetMessageId, target.mailbox),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["askhr-bot", "messages"] }),
  });

  const status = statusQuery.data;
  const enabled = status?.enabled ?? false;

  return (
    <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">HR</div>
        <h1 className="mt-1 text-2xl font-semibold text-slate-900">AskHR / Benefits Bot</h1>
        <p className="mt-1 text-sm text-slate-500">
          Polls the AskHR and Benefits mailboxes and creates HRD Jira tickets with AskHR/Benefits as reporter.
        </p>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-600">Bot enabled</span>
          <button
            role="switch"
            aria-checked={enabled}
            aria-label="Enable AskHR bot"
            disabled={settingsMutation.isPending}
            onClick={() => settingsMutation.mutate({ enabled: !enabled })}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
              enabled ? "bg-emerald-500" : "bg-slate-300"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                enabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
        </div>
        <div className="h-4 w-px bg-slate-200" />
        <div className="text-sm text-slate-600">
          Reporter mode: <strong>{status?.reporter_mode ?? "unset"}</strong>{" "}
          <button
            type="button"
            onClick={() => reporterModeResetMutation.mutate()}
            className="ml-2 rounded border border-slate-200 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
          >
            Re-test
          </button>
        </div>
        <div className="h-4 w-px bg-slate-200" />
        <div className="text-sm text-slate-600">
          Trusted domains: <strong>{status?.trusted_domains.length ?? 0}</strong> (refreshed{" "}
          {formatDateTime(status?.trusted_domains_refreshed_at)})
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-600">
        <div>AskHR checkpoint: {formatDateTime(status?.askhr_checkpoint_at)}</div>
        <div>Benefits checkpoint: {formatDateTime(status?.benefits_checkpoint_at)}</div>
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-700">Run history</h2>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Mailbox</th>
                <th className="px-3 py-2 text-left">Started</th>
                <th className="px-3 py-2 text-left">Scanned</th>
                <th className="px-3 py-2 text-left">Created</th>
                <th className="px-3 py-2 text-left">Skipped</th>
                <th className="px-3 py-2 text-left">Failed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(runsQuery.data?.items ?? []).map((run) => (
                <tr key={run.id}>
                  <td className="px-3 py-2">{run.mailbox}</td>
                  <td className="px-3 py-2">{formatDateTime(run.run_started_at)}</td>
                  <td className="px-3 py-2">{run.messages_scanned}</td>
                  <td className="px-3 py-2">{run.created_count}</td>
                  <td className="px-3 py-2">{run.skipped_count}</td>
                  <td className="px-3 py-2">{run.failed_count}</td>
                </tr>
              ))}
              {(runsQuery.data?.items ?? []).length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-center text-slate-500" colSpan={6}>
                    No runs yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <div className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-500">
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
      </div>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-700">Messages</h2>
        <div className="mt-2 overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200 text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Mailbox</th>
                <th className="px-3 py-2 text-left">Subject</th>
                <th className="px-3 py-2 text-left">Sender</th>
                <th className="px-3 py-2 text-left">Received</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">Jira</th>
                <th className="px-3 py-2 text-left">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(messagesQuery.data?.items ?? []).map((message: AskHrBotMessage) => (
                <tr
                  key={`${message.mailbox}:${message.internet_message_id}`}
                  title={message.error ?? undefined}
                >
                  <td className="px-3 py-2">{message.mailbox}</td>
                  <td className="px-3 py-2">{message.subject}</td>
                  <td className="px-3 py-2">{message.sender_email}</td>
                  <td className="px-3 py-2">{formatDateTime(message.received_at)}</td>
                  <td className={`px-3 py-2 ${message.status === "failed" ? "text-red-600" : "text-emerald-600"}`}>
                    {message.status}
                  </td>
                  <td className="px-3 py-2">{message.jira_issue_key ?? "—"}</td>
                  <td className="px-3 py-2">
                    {message.status === "failed" ? (
                      <button
                        type="button"
                        onClick={() =>
                          retryMutation.mutate({
                            internetMessageId: message.internet_message_id,
                            mailbox: message.mailbox,
                          })
                        }
                        disabled={retryMutation.isPending}
                        className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                      >
                        Retry
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
              {(messagesQuery.data?.items ?? []).length === 0 ? (
                <tr>
                  <td className="px-3 py-4 text-center text-slate-500" colSpan={7}>
                    No messages processed yet.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <div className="mt-2 flex items-center justify-end gap-2 text-xs text-slate-500">
          <button
            type="button"
            onClick={() => setMessagesOffset((offset) => Math.max(0, offset - MESSAGES_LIMIT))}
            disabled={messagesOffset === 0}
            className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
          >
            Previous
          </button>
          <button
            type="button"
            onClick={() => setMessagesOffset((offset) => offset + MESSAGES_LIMIT)}
            disabled={messagesOffset + MESSAGES_LIMIT >= (messagesQuery.data?.total ?? 0)}
            className="rounded border border-slate-200 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>
    </section>
  );
}
