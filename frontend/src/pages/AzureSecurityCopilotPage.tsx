import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  api,
  type SecurityCopilotAnswer,
  type SecurityCopilotChatMessage,
  type SecurityCopilotChatRequest,
  type SecurityCopilotChatResponse,
  type SecurityCopilotIncident,
  type SecurityCopilotJobRef,
  type SecurityCopilotSourceResult,
} from "../lib/api.ts";

const starterPrompts = [
  "User ada@example.com reported impossible travel alerts and repeated MFA prompts since 2 AM UTC.",
  "Shared mailbox payroll@example.com is forwarding mail externally and we need to check rules and delegation.",
  "Suspicious service principal activity is tied to app id 11111111-2222-3333-4444-555555555555 from this morning.",
];

const laneLabels: Record<string, string> = {
  identity_compromise: "Identity compromise",
  mailbox_abuse: "Mailbox abuse",
  app_or_service_principal: "App or service principal",
  azure_alert_or_resource: "Azure alert or resource",
  unknown: "Unknown",
};

const emptyIncident: SecurityCopilotIncident = {
  lane: "unknown",
  summary: "",
  timeframe: "",
  affected_users: [],
  affected_mailboxes: [],
  affected_apps: [],
  affected_resources: [],
  alert_names: [],
  observed_artifacts: [],
  confidence: 0,
  missing_fields: [],
};

type SecurityTurn = {
  id: string;
  question: string;
  response: SecurityCopilotChatResponse;
};

function StatusPill({
  label,
  tone = "slate",
}: {
  label: string;
  tone?: "slate" | "sky" | "emerald" | "amber" | "rose";
}) {
  const className =
    tone === "emerald"
      ? "bg-emerald-50 text-emerald-700"
      : tone === "amber"
        ? "bg-amber-50 text-amber-700"
        : tone === "rose"
          ? "bg-rose-50 text-rose-700"
          : tone === "sky"
            ? "bg-sky-50 text-sky-700"
            : "bg-slate-100 text-slate-600";
  return <span className={`rounded-full px-3 py-1 text-xs font-semibold ${className}`}>{label}</span>;
}

function phaseTone(phase: SecurityCopilotChatResponse["phase"]): "sky" | "amber" | "emerald" {
  if (phase === "running_jobs") return "amber";
  if (phase === "complete") return "emerald";
  return "sky";
}

function sourceTone(status: SecurityCopilotSourceResult["status"]): "emerald" | "amber" | "rose" | "slate" {
  if (status === "completed") return "emerald";
  if (status === "running") return "amber";
  if (status === "error") return "rose";
  return "slate";
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function buildHistory(turns: SecurityTurn[]): SecurityCopilotChatMessage[] {
  return turns.flatMap((turn) => [
    { role: "user" as const, content: turn.question },
    { role: "assistant" as const, content: turn.response.assistant_message },
  ]);
}

function formatExportList(values: string[], emptyLabel = "None captured"): string {
  return values.length > 0 ? values.join(", ") : emptyLabel;
}

function slugifyFilePart(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
}

function buildExportFileStem(response: SecurityCopilotChatResponse): string {
  const timestamp = response.generated_at
    ? new Date(response.generated_at).toISOString().slice(0, 19).replace(/[:T]/g, "-")
    : "investigation";
  const lane = slugifyFilePart(response.incident.lane || "security-incident") || "security-incident";
  return `azure-security-${lane}-${timestamp}`;
}

function previewRowLine(row: Record<string, unknown>): string {
  const parts = Object.entries(row)
    .slice(0, 4)
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${String(value ?? "").trim() || "n/a"}`);
  return parts.join(" | ");
}

function buildInvestigationMarkdown(response: SecurityCopilotChatResponse, turns: SecurityTurn[]): string {
  const incident = response.incident;
  const answer = response.answer;
  const lines: string[] = [
    "# Azure Security Investigation Export",
    "",
    `Generated: ${response.generated_at}`,
    `Phase: ${response.phase}`,
    `Model: ${response.model_used}`,
    "",
    "## Incident Profile",
    `- Lane: ${laneLabels[incident.lane] || incident.lane}`,
    `- Summary: ${incident.summary || "Not captured"}`,
    `- Timeframe: ${incident.timeframe || "Not captured"}`,
    `- Affected users: ${formatExportList(incident.affected_users)}`,
    `- Affected mailboxes: ${formatExportList(incident.affected_mailboxes)}`,
    `- Affected apps: ${formatExportList(incident.affected_apps)}`,
    `- Affected resources: ${formatExportList(incident.affected_resources)}`,
    `- Alert names: ${formatExportList(incident.alert_names)}`,
    `- Observed artifacts: ${formatExportList(incident.observed_artifacts)}`,
    "",
    "## Copilot Summary",
    answer.summary || response.assistant_message || "No final summary available yet.",
  ];

  if (answer.findings.length > 0) {
    lines.push("", "## Findings", ...answer.findings.map((item) => `- ${item}`));
  }
  if (answer.next_steps.length > 0) {
    lines.push("", "## Next Steps", ...answer.next_steps.map((item) => `- ${item}`));
  }
  if (answer.warnings.length > 0) {
    lines.push("", "## Warnings", ...answer.warnings.map((item) => `- ${item}`));
  }
  if (response.jobs.length > 0) {
    lines.push(
      "",
      "## Safe Jobs",
      ...response.jobs.map(
        (job) =>
          `- ${job.label}: ${job.status} for ${job.target || "current target"}${job.phase ? ` (${job.phase.replace(/_/g, " ")})` : ""}`,
      ),
    );
  }
  if (response.source_results.length > 0) {
    lines.push("", "## Source Results");
    response.source_results.forEach((result) => {
      lines.push(
        "",
        `### ${result.label}`,
        `- Status: ${result.status}`,
        `- Query: ${result.query_summary || "Not recorded"}`,
        `- Item count: ${result.item_count}`,
      );
      if (result.reason) {
        lines.push(`- Reason: ${result.reason}`);
      }
      if (result.highlights.length > 0) {
        lines.push(...result.highlights.map((item) => `- Highlight: ${item}`));
      }
      if (result.preview.length > 0) {
        lines.push(...result.preview.slice(0, 4).map((row) => `- Preview: ${previewRowLine(row)}`));
      }
      if (result.citations.length > 0) {
        lines.push(...result.citations.map((citation) => `- Citation: ${citation.label} (${citation.detail})`));
      }
    });
  }
  if (response.citations.length > 0) {
    lines.push("", "## Citations", ...response.citations.map((citation) => `- ${citation.label}: ${citation.detail}`));
  }
  if (turns.length > 0) {
    lines.push("", "## Transcript");
    turns.forEach((turn, index) => {
      lines.push(
        "",
        `### Turn ${index + 1}`,
        `User: ${turn.question}`,
        `Assistant: ${turn.response.assistant_message}`,
        `Phase: ${turn.response.phase}`,
      );
    });
  }
  return `${lines.join("\n").trim()}\n`;
}

function buildInvestigationJson(response: SecurityCopilotChatResponse, turns: SecurityTurn[]): string {
  return JSON.stringify(
    {
      exported_at: new Date().toISOString(),
      export_type: "azure_security_investigation",
      investigation: response,
      transcript: turns.map((turn, index) => ({
        turn: index + 1,
        user: turn.question,
        assistant: turn.response.assistant_message,
        phase: turn.response.phase,
        generated_at: turn.response.generated_at,
      })),
    },
    null,
    2,
  );
}

async function copyText(text: string) {
  if (!text) return;
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.focus();
  area.select();
  document.execCommand("copy");
  document.body.removeChild(area);
}

function downloadTextFile(filename: string, text: string, mimeType: string) {
  if (!text) return;
  const blob = new Blob([text], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function PreviewTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200 text-left text-xs">
        <tbody className="divide-y divide-slate-200 bg-white">
          {rows.slice(0, 4).map((row, index) => (
            <tr key={index}>
              <td className="px-3 py-2 align-top text-slate-500">
                {Object.entries(row)
                  .slice(0, 4)
                  .map(([key]) => key.replace(/_/g, " "))
                  .join(" / ")}
              </td>
              <td className="px-3 py-2 text-slate-700">
                {Object.entries(row)
                  .slice(0, 4)
                  .map(([, value]) => String(value ?? ""))
                  .join(" | ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnswerBlock({ answer }: { answer: SecurityCopilotAnswer }) {
  if (!answer.summary && answer.findings.length === 0 && answer.next_steps.length === 0 && answer.warnings.length === 0) {
    return null;
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold text-slate-900">Investigation Summary</h2>
        <StatusPill label="Final synthesis" tone="emerald" />
      </div>
      <p className="mt-3 text-sm leading-7 text-slate-700">{answer.summary}</p>

      {answer.findings.length > 0 ? (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Findings</div>
          <div className="mt-2 space-y-2">
            {answer.findings.map((item) => (
              <div key={item} className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
                {item}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {answer.next_steps.length > 0 ? (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Next steps</div>
          <div className="mt-2 space-y-2">
            {answer.next_steps.map((item) => (
              <div key={item} className="rounded-xl bg-sky-50 px-4 py-3 text-sm text-sky-800">
                {item}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {answer.warnings.length > 0 ? (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Warnings</div>
          <div className="mt-2 space-y-2">
            {answer.warnings.map((item) => (
              <div key={item} className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {item}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

export default function AzureSecurityCopilotPage() {
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState("");
  const [turns, setTurns] = useState<SecurityTurn[]>([]);
  const [latestResponse, setLatestResponse] = useState<SecurityCopilotChatResponse | null>(null);
  const [exportNotice, setExportNotice] = useState("");

  const { data: models = [] } = useQuery({
    queryKey: ["azure", "ai", "models", "security-copilot"],
    queryFn: () => api.getAzureAIModels(),
    staleTime: 5 * 60 * 1000,
  });
  const statusQuery = useQuery({
    queryKey: ["azure", "status", "security-copilot"],
    queryFn: () => api.getAzureStatus(),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  const chatMutation = useMutation({
    mutationFn: (body: SecurityCopilotChatRequest) => api.chatAzureSecurityCopilot(body),
    onSuccess: (response, variables) => {
      setLatestResponse(response);
      if (variables.message.trim()) {
        setTurns((current) => [
          ...current,
          {
            id: `${response.generated_at}-${current.length}`,
            question: variables.message.trim(),
            response,
          },
        ]);
        setDraft("");
        return;
      }
      setTurns((current) => {
        if (current.length === 0) return current;
        const previous = current[current.length - 1];
        return [...current.slice(0, -1), { ...previous, response }];
      });
    },
  });

  useEffect(() => {
    if (!latestResponse || latestResponse.phase !== "running_jobs" || chatMutation.isPending || turns.length === 0) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => {
      chatMutation.mutate({
        message: "",
        history: buildHistory(turns),
        incident: latestResponse.incident,
        jobs: latestResponse.jobs,
        model: model || undefined,
      });
    }, 4000);
    return () => window.clearTimeout(timeoutId);
  }, [chatMutation, latestResponse, model, turns]);

  const activeIncident = latestResponse?.incident ?? emptyIncident;
  const activeJobs = latestResponse?.jobs ?? [];
  const canSubmit = draft.trim().length > 0 && !chatMutation.isPending;
  const exportFileStem = latestResponse ? buildExportFileStem(latestResponse) : "";
  const investigationMarkdown = latestResponse ? buildInvestigationMarkdown(latestResponse, turns) : "";
  const investigationJson = latestResponse ? buildInvestigationJson(latestResponse, turns) : "";

  const submitInvestigation = () => {
    const message = draft.trim();
    if (!message) return;
    chatMutation.mutate({
      message,
      history: buildHistory(turns),
      incident: activeIncident,
      jobs: activeJobs,
      model: model || undefined,
    });
  };

  const copyMarkdownExport = async () => {
    if (!latestResponse) return;
    try {
      await copyText(investigationMarkdown);
      setExportNotice("Copied investigation handoff markdown to the clipboard.");
    } catch {
      setExportNotice("Clipboard copy failed. Download the markdown export instead.");
    }
  };

  const downloadMarkdownExport = () => {
    if (!latestResponse) return;
    downloadTextFile(`${exportFileStem}.md`, investigationMarkdown, "text/markdown;charset=utf-8");
    setExportNotice(`Downloaded ${exportFileStem}.md`);
  };

  const downloadJsonExport = () => {
    if (!latestResponse) return;
    downloadTextFile(`${exportFileStem}.json`, investigationJson, "application/json;charset=utf-8");
    setExportNotice(`Downloaded ${exportFileStem}.json`);
  };

  const statusLabel = latestResponse?.phase
    ? latestResponse.phase === "needs_input"
      ? "Needs more intake"
      : latestResponse.phase === "running_jobs"
        ? "Running safe jobs"
        : "Investigation complete"
    : "Ready for intake";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold text-slate-900">Security Copilot</h1>
            <StatusPill label={statusLabel} tone={latestResponse ? phaseTone(latestResponse.phase) : "sky"} />
          </div>
          <p className="mt-2 max-w-4xl text-sm text-slate-500">
            Ollama-backed incident workbench for Azure security investigations. It asks follow-up questions until it has enough context, queries
            the relevant Azure and local sources your session can use, and auto-starts safe mailbox delegate scans when the case needs them.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
            <span className="rounded-full bg-slate-100 px-3 py-1">
              Azure cache refreshed {formatTimestamp(statusQuery.data?.last_refresh)}
            </span>
            <span className="rounded-full bg-slate-100 px-3 py-1">
              {models.length} local model{models.length === 1 ? "" : "s"} available through Ollama
            </span>
            <Link to="/security" className="rounded-full bg-sky-50 px-3 py-1 font-semibold text-sky-700 hover:bg-sky-100">
              Back to Security workspace
            </Link>
          </div>
        </div>
      </div>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-3 md:grid-cols-[1fr,260px,auto]">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={5}
            placeholder={starterPrompts[0]}
            className="w-full rounded-xl border border-slate-300 px-3 py-3 text-sm outline-none transition focus:border-sky-500"
          />
          <select
            value={model}
            onChange={(event) => setModel(event.target.value)}
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="">Default Ollama model</option>
            {models.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name === item.id ? item.id : `${item.name} (${item.id})`}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={submitInvestigation}
            disabled={!canSubmit}
            className="rounded-xl bg-sky-700 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {chatMutation.isPending ? "Investigating..." : "Start Investigation"}
          </button>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          {starterPrompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => setDraft(prompt)}
              className="rounded-full border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              {prompt}
            </button>
          ))}
        </div>
      </section>

      {chatMutation.isError ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {chatMutation.error instanceof Error ? chatMutation.error.message : "Security copilot request failed"}
        </div>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Normalized Incident</h2>
            <p className="mt-1 text-sm text-slate-500">
              The copilot keeps this structured profile in the browser and sends it back on each turn so the backend stays stateless.
            </p>
          </div>
          <StatusPill label={laneLabels[activeIncident.lane] || "Unknown"} tone="sky" />
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl bg-slate-50 px-4 py-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Summary</div>
            <div className="mt-2 text-sm leading-6 text-slate-700">
              {activeIncident.summary || "The copilot will build this after the first incident description."}
            </div>
          </div>
          <div className="rounded-xl bg-slate-50 px-4 py-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Timeframe</div>
            <div className="mt-2 text-sm leading-6 text-slate-700">{activeIncident.timeframe || "Still needed"}</div>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2 text-xs">
          {[
            ...activeIncident.affected_users.map((item) => `User: ${item}`),
            ...activeIncident.affected_mailboxes.map((item) => `Mailbox: ${item}`),
            ...activeIncident.affected_apps.map((item) => `App: ${item}`),
            ...activeIncident.affected_resources.map((item) => `Resource: ${item}`),
            ...activeIncident.alert_names.map((item) => `Alert: ${item}`),
            ...activeIncident.observed_artifacts.map((item) => `Artifact: ${item}`),
          ].map((item) => (
            <span key={item} className="rounded-full bg-slate-100 px-3 py-1 text-slate-700">
              {item}
            </span>
          ))}
          {activeIncident.summary || activeIncident.timeframe || activeIncident.affected_users.length > 0 || activeIncident.affected_mailboxes.length > 0 || activeIncident.affected_apps.length > 0 || activeIncident.affected_resources.length > 0 || activeIncident.alert_names.length > 0 || activeIncident.observed_artifacts.length > 0 ? null : (
            <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-500">No incident details captured yet</span>
          )}
        </div>
      </section>

      {latestResponse ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="text-lg font-semibold text-slate-900">Current Copilot Status</h2>
            <StatusPill label={statusLabel} tone={phaseTone(latestResponse.phase)} />
            <span className="text-xs text-slate-500">{latestResponse.model_used}</span>
            <span className="text-xs text-slate-500">{formatTimestamp(latestResponse.generated_at)}</span>
          </div>
          <div className="mt-4 rounded-xl bg-slate-50 px-4 py-4 text-sm leading-7 text-slate-800">
            {latestResponse.assistant_message}
          </div>

          {latestResponse.follow_up_questions.length > 0 ? (
            <div className="mt-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Follow-up questions</div>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                {latestResponse.follow_up_questions.map((question) => (
                  <div key={question.key} className="rounded-xl border border-slate-200 bg-white px-4 py-4">
                    <div className="text-sm font-semibold text-slate-900">{question.label}</div>
                    <div className="mt-2 text-sm leading-6 text-slate-600">{question.prompt}</div>
                    <div className="mt-2 text-xs text-slate-500">{question.placeholder}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {latestResponse?.planned_sources.length ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Source Plan</h2>
          <p className="mt-1 text-sm text-slate-500">
            These are the Azure and local source groups the copilot has planned for the current incident profile.
          </p>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {latestResponse.planned_sources.map((source) => (
              <div key={source.key} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-900">{source.label}</div>
                  <StatusPill label={source.status.replace(/_/g, " ")} tone={sourceTone(source.status === "planned" ? "skipped" : source.status)} />
                </div>
                <div className="mt-2 text-sm leading-6 text-slate-600">{source.query_summary}</div>
                {source.reason ? <div className="mt-2 text-xs text-rose-700">{source.reason}</div> : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {latestResponse?.source_results.length ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Source Results</h2>
          <div className="mt-4 space-y-4">
            {latestResponse.source_results.map((result) => (
              <article key={result.key} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="text-sm font-semibold text-slate-900">{result.label}</div>
                  <StatusPill label={result.status.replace(/_/g, " ")} tone={sourceTone(result.status)} />
                  <span className="text-xs text-slate-500">{result.item_count} item(s)</span>
                </div>
                <div className="mt-2 text-sm leading-6 text-slate-600">{result.query_summary}</div>
                {result.highlights.length > 0 ? (
                  <div className="mt-3 space-y-2">
                    {result.highlights.map((highlight) => (
                      <div key={highlight} className="rounded-lg bg-white px-3 py-2 text-sm text-slate-700">
                        {highlight}
                      </div>
                    ))}
                  </div>
                ) : null}
                {result.reason ? <div className="mt-3 text-xs text-rose-700">{result.reason}</div> : null}
                <PreviewTable rows={result.preview} />
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {latestResponse?.jobs.length ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Safe Jobs</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {latestResponse.jobs.map((job: SecurityCopilotJobRef) => (
              <div key={job.job_id} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-semibold text-slate-900">{job.label}</div>
                  <StatusPill label={job.status} tone={job.status === "completed" ? "emerald" : job.status === "failed" ? "rose" : "amber"} />
                </div>
                <div className="mt-2 text-sm text-slate-600">{job.target}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {job.phase ? job.phase.replace(/_/g, " ") : job.summary || "Queued"}
                </div>
                <div className="mt-2 text-xs text-slate-500">Job ID: {job.job_id}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {latestResponse ? <AnswerBlock answer={latestResponse.answer} /> : null}

      {latestResponse ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Investigation Export</h2>
              <p className="mt-1 max-w-3xl text-sm text-slate-500">
                Bundle the current incident profile, grounded source evidence, citations, job status, and transcript into a repeatable handoff for escalation or post-incident review.
              </p>
            </div>
            <StatusPill label={latestResponse.phase === "complete" ? "Ready to share" : "Partial handoff"} tone={phaseTone(latestResponse.phase)} />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={copyMarkdownExport}
              className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
            >
              Copy Markdown
            </button>
            <button
              type="button"
              onClick={downloadMarkdownExport}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Download Markdown
            </button>
            <button
              type="button"
              onClick={downloadJsonExport}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Download JSON
            </button>
          </div>
          <div className="mt-4 rounded-xl bg-slate-50 px-4 py-4 text-sm text-slate-700">
            <div className="font-semibold text-slate-900">Export bundle</div>
            <div className="mt-1">Filename stem: {exportFileStem}</div>
            <div className="mt-1">Includes incident details, findings, source highlights, citations, safe-job state, and transcript turns.</div>
          </div>
          {exportNotice ? <div className="mt-3 text-sm text-sky-700">{exportNotice}</div> : null}
        </section>
      ) : null}

      {latestResponse?.citations.length ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Citations</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {latestResponse.citations.map((citation) => (
              <span
                key={`${citation.source_type}-${citation.label}-${citation.detail}`}
                className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700"
              >
                {citation.label}: {citation.detail}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      {turns.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Transcript</h2>
          <div className="mt-4 space-y-4">
            {turns
              .slice()
              .reverse()
              .map((turn, index) => (
                <article key={turn.id} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <div className="text-sm font-semibold text-slate-900">{index === 0 ? "Latest Turn" : "Earlier Turn"}</div>
                    <span className="text-xs text-slate-500">{formatTimestamp(turn.response.generated_at)}</span>
                  </div>
                  <div className="mt-3 rounded-lg bg-white px-3 py-3 text-sm text-slate-800">{turn.question}</div>
                  <div className="mt-3 rounded-lg bg-sky-50 px-3 py-3 text-sm leading-6 text-sky-900">
                    {turn.response.assistant_message}
                  </div>
                </article>
              ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
