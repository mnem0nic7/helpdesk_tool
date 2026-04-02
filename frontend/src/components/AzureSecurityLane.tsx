import type { ReactNode } from "react";
import { Link } from "react-router-dom";

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
