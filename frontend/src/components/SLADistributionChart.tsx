import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import type { SLATimerStats } from "../lib/api.ts";

const DIST_COLORS = ["#10b981", "#34d399", "#6ee7b7", "#fbbf24", "#f97316", "#ef4444", "#dc2626"];

export default function SLADistributionChart({
  title,
  stats,
}: {
  title: string;
  stats: SLATimerStats;
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
            <Bar dataKey="count" radius={[4, 4, 0, 0]}>
              {data.map((_entry, i) => (
                <Cell key={i} fill={DIST_COLORS[i % DIST_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
