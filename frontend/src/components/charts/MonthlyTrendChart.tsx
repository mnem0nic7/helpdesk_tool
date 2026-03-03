import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { WeeklyVolume } from "../../lib/api.ts";

interface Props {
  data: WeeklyVolume[];
}

/** Format a week-start date (YYYY-MM-DD) as a short label like "Jan 20". */
function formatWeekLabel(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function MonthlyTrendChart({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-gray-400">
        No weekly data available
      </div>
    );
  }

  const chartData = data.map((d) => ({
    ...d,
    label: formatWeekLabel(d.week),
  }));

  return (
    <div className="rounded-lg bg-white p-4 shadow">
      <h3 className="mb-3 text-sm font-semibold text-gray-700">
        Weekly Ticket Trend (Last 8 Weeks)
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: "#6b7280" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#6b7280" }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            labelFormatter={(_label, payload) => {
              if (payload?.[0]?.payload?.week) {
                return `Week of ${payload[0].payload.week}`;
              }
              return String(_label);
            }}
            contentStyle={{
              fontSize: 12,
              borderRadius: 8,
              border: "1px solid #e5e7eb",
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone"
            dataKey="created"
            name="Created"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
          />
          <Line
            type="monotone"
            dataKey="resolved"
            name="Resolved"
            stroke="#22c55e"
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
