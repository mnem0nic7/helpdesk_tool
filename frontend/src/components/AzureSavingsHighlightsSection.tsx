import { Link } from "react-router-dom";
import { type AzureSavingsOpportunity } from "../lib/api.ts";

export function formatAzureCurrency(value: number | null, currency = "USD"): string {
  if (value === null) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

function badgeClass(value: string, tone: "effort" | "risk" | "confidence"): string {
  const normalized = value.toLowerCase();
  if (tone === "confidence") {
    if (normalized === "high") return "bg-emerald-100 text-emerald-700";
    if (normalized === "medium") return "bg-amber-100 text-amber-700";
    return "bg-slate-100 text-slate-600";
  }
  if (normalized === "low") return "bg-emerald-100 text-emerald-700";
  if (normalized === "medium") return "bg-amber-100 text-amber-700";
  return "bg-rose-100 text-rose-700";
}

function ToneBadge({ label, value, tone }: { label: string; value: string; tone: "effort" | "risk" | "confidence" }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${badgeClass(value, tone)}`}>
      {label}: {value}
    </span>
  );
}

export default function AzureSavingsHighlightsSection({
  title,
  description,
  opportunities,
  emptyMessage,
  maxItems = 5,
}: {
  title: string;
  description?: string;
  opportunities: AzureSavingsOpportunity[];
  emptyMessage: string;
  maxItems?: number;
}) {
  const visible = opportunities.slice(0, maxItems);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          {description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {opportunities.length.toLocaleString()}
        </span>
      </div>

      {visible.length === 0 ? (
        <p className="mt-5 text-sm text-slate-400">{emptyMessage}</p>
      ) : (
        <div className="mt-4 space-y-3">
          {visible.map((item) => (
            <div key={item.id} className="rounded-xl border border-slate-200 bg-slate-50/80 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-slate-900">{item.title}</div>
                  <div className="mt-1 text-sm text-slate-600">{item.summary}</div>
                </div>
                <div className="text-right">
                  <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Estimated Savings</div>
                  <div className="mt-1 text-lg font-semibold text-emerald-700">
                    {item.quantified ? formatAzureCurrency(item.estimated_monthly_savings, item.currency) : "Unquantified"}
                  </div>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <ToneBadge label="Effort" value={item.effort} tone="effort" />
                <ToneBadge label="Risk" value={item.risk} tone="risk" />
                <ToneBadge label="Confidence" value={item.confidence} tone="confidence" />
                {item.subscription_name || item.subscription_id ? (
                  <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] font-semibold text-sky-700">
                    {item.subscription_name || item.subscription_id}
                  </span>
                ) : null}
              </div>

              <div className="mt-3 flex flex-wrap gap-3 text-xs font-medium">
                <Link to={item.follow_up_route} className="text-sky-700 hover:text-sky-800">
                  Open follow-up page
                </Link>
                <a href={item.portal_url} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-slate-800">
                  Open in Azure Portal
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
