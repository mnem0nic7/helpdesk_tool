import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SecurityLaneAISummary } from "../lib/api.ts";

export type AzureSecurityLaneTone = "slate" | "sky" | "emerald" | "amber" | "rose" | "violet";

export type AzureSecurityLaneAction = {
  label: string;
  to: string;
  external?: boolean;
  tone?: "primary" | "secondary";
};

function laneGradient(accent: AzureSecurityLaneTone): string {
  if (accent === "amber") return "from-white via-amber-50 to-orange-50";
  if (accent === "rose") return "from-white via-rose-50 to-slate-50";
  if (accent === "violet") return "from-white via-violet-50 to-slate-50";
  if (accent === "emerald") return "from-white via-emerald-50 to-slate-50";
  return "from-white via-slate-50 to-sky-50";
}

function eyebrowTone(accent: AzureSecurityLaneTone): string {
  if (accent === "amber") return "text-amber-700";
  if (accent === "rose") return "text-rose-700";
  if (accent === "violet") return "text-violet-700";
  if (accent === "emerald") return "text-emerald-700";
  return "text-sky-700";
}

export function azureSecurityToneClasses(tone: AzureSecurityLaneTone): string {
  if (tone === "sky") return "bg-sky-50 text-sky-700";
  if (tone === "emerald") return "bg-emerald-50 text-emerald-700";
  if (tone === "amber") return "bg-amber-50 text-amber-700";
  if (tone === "rose") return "bg-rose-50 text-rose-700";
  if (tone === "violet") return "bg-violet-50 text-violet-700";
  return "bg-slate-100 text-slate-600";
}

function actionClasses(tone: AzureSecurityLaneAction["tone"]): string {
  return [
    "inline-flex items-center rounded-lg px-3 py-2 text-sm font-medium transition",
    tone === "secondary"
      ? "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
      : "bg-sky-700 text-white hover:bg-sky-800",
  ].join(" ");
}

export function AzureSecurityLaneActionButton({ action }: { action: AzureSecurityLaneAction }) {
  if (action.external) {
    return (
      <a href={action.to} target="_blank" rel="noreferrer" className={actionClasses(action.tone)}>
        {action.label}
      </a>
    );
  }

  return (
    <Link to={action.to} className={actionClasses(action.tone)}>
      {action.label}
    </Link>
  );
}

export function AzureSecurityLaneHero({
  title,
  description,
  actions,
  refreshLabel,
  refreshValue,
  accent = "sky",
  eyebrow = "Azure Security",
}: {
  title: string;
  description: ReactNode;
  actions: AzureSecurityLaneAction[];
  refreshLabel?: string;
  refreshValue?: string;
  accent?: AzureSecurityLaneTone;
  eyebrow?: string;
}) {
  return (
    <section className={`rounded-3xl border border-slate-200 bg-gradient-to-br ${laneGradient(accent)} p-6 shadow-sm`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-3xl">
          <div className={`text-xs font-semibold uppercase tracking-[0.24em] ${eyebrowTone(accent)}`}>{eyebrow}</div>
          <h1 className="mt-3 text-3xl font-bold text-slate-900">{title}</h1>
          <div className="mt-3 text-sm leading-7 text-slate-600">{description}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {actions.map((action) => (
            <AzureSecurityLaneActionButton key={`${title}-${action.label}`} action={action} />
          ))}
        </div>
      </div>

      {refreshLabel && refreshValue ? (
        <div className="mt-5 rounded-2xl border border-white/70 bg-white/80 px-4 py-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{refreshLabel}</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{refreshValue}</div>
        </div>
      ) : null}
    </section>
  );
}

function formatRelativeTime(isoString: string): string {
  if (!isoString) return "";
  try {
    const diffMs = Date.now() - new Date(isoString).getTime();
    const diffMin = Math.round(diffMs / 60_000);
    if (diffMin < 2) return "just now";
    if (diffMin < 60) return `${diffMin} min ago`;
    const diffH = Math.round(diffMin / 60);
    if (diffH < 24) return `${diffH}h ago`;
    return `${Math.round(diffH / 24)}d ago`;
  } catch {
    return isoString;
  }
}

export function LaneSummaryPanel({ laneKey }: { laneKey: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(true);

  const summaryQuery = useQuery({
    queryKey: ["azure", "security", "lane-summaries"],
    queryFn: () => api.getLaneSummaries(),
    staleTime: 5 * 60_000,
  });

  const regenMut = useMutation({
    mutationFn: () => api.regenerateLaneSummary(laneKey),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["azure", "security", "lane-summaries"] });
    },
  });

  const summary: SecurityLaneAISummary | undefined = summaryQuery.data?.find(
    (s) => s.lane_key === laneKey
  );

  if (summaryQuery.isLoading) return null;

  return (
    <section className="rounded-2xl border border-indigo-200 bg-indigo-50/60 p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 text-sm font-semibold text-indigo-800 hover:text-indigo-900"
        >
          <span className="text-xs">{open ? "▾" : "▸"}</span>
          AI Triage Summary
        </button>
        <div className="flex items-center gap-3">
          {summary?.generated_at && (
            <span className="text-xs text-indigo-500">
              Generated {formatRelativeTime(summary.generated_at)}
            </span>
          )}
          <button
            type="button"
            onClick={() => regenMut.mutate()}
            disabled={regenMut.isPending}
            className="rounded-md border border-indigo-300 bg-white px-2 py-0.5 text-xs font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50"
          >
            {regenMut.isPending ? "Queued…" : "Regenerate"}
          </button>
        </div>
      </div>

      {open && (
        <div className="mt-3">
          {summary ? (
            <>
              <p className="text-sm leading-relaxed text-indigo-900">{summary.narrative}</p>
              {summary.bullets.length > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {summary.bullets.map((b, i) => (
                    <li key={i} className="flex gap-2 text-sm text-indigo-800">
                      <span className="mt-0.5 text-indigo-400">•</span>
                      <span>{b}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <p className="text-sm text-indigo-600 italic">
              AI summary generates hourly — not yet available.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

export function AzureSecurityMetricCard({
  label,
  value,
  detail,
  tone = "slate",
}: {
  label: string;
  value: number | string;
  detail: string;
  tone?: AzureSecurityLaneTone;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(tone)}`}>{label}</span>
      </div>
      <div className="mt-3 text-3xl font-semibold text-slate-900">
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-600">{detail}</p>
    </section>
  );
}
