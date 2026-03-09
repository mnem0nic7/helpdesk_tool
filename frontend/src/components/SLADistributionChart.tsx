import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import type { SLATimerStats } from "../lib/api.ts";

const DIST_COLORS = ["#10b981", "#34d399", "#6ee7b7", "#fbbf24", "#f97316", "#ef4444", "#dc2626"];

export default function SLADistributionChart({
  title,
  stats,
  selectedBucket,
  onSelectBucket,
}: {
  title: string;
  stats: SLATimerStats;
  selectedBucket?: string | null;
  onSelectBucket?: (bucketLabel: string) => void;
}) {
  const data = stats.distribution ?? [];
  if (!data.length) return null;

  return (
    <div className="rounded-lg bg-white px-5 py-5 shadow">
      <h3 className="text-sm font-semibold tracking-wide text-gray-700 uppercase">{title}</h3>
      <div className="mt-3 h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
            <Tooltip formatter={(v) => [String(v), "Tickets"]} />
            <Bar
              dataKey="count"
              radius={[4, 4, 0, 0]}
              cursor={onSelectBucket ? "pointer" : undefined}
              onClick={(entry) => {
                const bucketLabel = entry && typeof entry === "object"
                  ? ("label" in entry && typeof entry.label === "string"
                    ? entry.label
                    : "payload" in entry && entry.payload && typeof entry.payload === "object" && "label" in entry.payload && typeof entry.payload.label === "string"
                      ? entry.payload.label
                      : null)
                  : null;
                if (typeof bucketLabel === "string") {
                  onSelectBucket?.(bucketLabel);
                }
              }}
            >
              {data.map((entry, i) => {
                const isSelected = selectedBucket === entry.label;
                return (
                  <Cell
                    key={entry.label}
                    fill={DIST_COLORS[i % DIST_COLORS.length]}
                    stroke={isSelected ? "#1d4ed8" : undefined}
                    strokeWidth={isSelected ? 2 : 0}
                  />
                );
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {data.map((entry, i) => {
          const isSelected = selectedBucket === entry.label;
          return (
            <button
              key={entry.label}
              type="button"
              onClick={() => onSelectBucket?.(entry.label)}
              className={[
                "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                isSelected
                  ? "border-blue-300 bg-blue-50 text-blue-700"
                  : "border-slate-200 bg-slate-50 text-slate-600 hover:border-slate-300 hover:bg-slate-100",
              ].join(" ")}
              aria-label={`Filter ${title} bucket ${entry.label}`}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: DIST_COLORS[i % DIST_COLORS.length] }}
              />
              {entry.label}
            </button>
          );
        })}
        {selectedBucket && (
          <button
            type="button"
            onClick={() => onSelectBucket?.(selectedBucket)}
            className="inline-flex items-center rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-500 hover:bg-slate-50"
          >
            Clear bucket
          </button>
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Click a bar or bucket to filter the ticket list.
      </p>
    </div>
  );
}
