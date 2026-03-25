import type { JiraAuthStatus } from "../lib/api.ts";
import { api } from "../lib/api.ts";

interface JiraWriteIdentityNoticeProps {
  jiraAuth?: JiraAuthStatus;
  className?: string;
  returnTo?: string;
}

export default function JiraWriteIdentityNotice({
  jiraAuth,
  className = "",
  returnTo,
}: JiraWriteIdentityNoticeProps) {
  const connected = !!jiraAuth?.connected;
  const configured = jiraAuth?.configured ?? false;
  const resolvedReturnTo =
    returnTo ||
    (typeof window !== "undefined"
      ? `${window.location.pathname}${window.location.search}${window.location.hash}`
      : "/");

  return (
    <div className={`rounded-lg border px-3 py-2 text-xs ${connected ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"} ${className}`.trim()}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold uppercase tracking-wide">
          {connected ? "Jira Write Identity" : "Jira Write Fallback"}
        </span>
        <span>
          {connected
            ? `Writes go to Jira as ${jiraAuth?.account_name || "your Jira account"}.`
            : "Writes go to Jira as it-app until you connect Atlassian."}
        </span>
        {configured && !connected ? (
          <button
            type="button"
            onClick={() => {
              window.location.href = api.getAtlassianConnectUrl(resolvedReturnTo);
            }}
            className="rounded-md border border-amber-300 bg-white px-2 py-1 text-[11px] font-semibold text-amber-900 hover:bg-amber-100"
          >
            Connect Atlassian
          </button>
        ) : null}
      </div>
      {!connected ? (
        <div className="mt-1 text-[11px] text-amber-800">
          Fallback writes are still allowed. Comments include your MoveDocs identity, and non-comment updates add an internal Jira audit note.
        </div>
      ) : jiraAuth?.site_url ? (
        <div className="mt-1 text-[11px] text-emerald-800">Connected site: {jiraAuth.site_url}</div>
      ) : null}
    </div>
  );
}
