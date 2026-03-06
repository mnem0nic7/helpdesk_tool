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
  onPointClick?: (weekStart: string) => void;
}

function formatLabel(iso: string, grouping?: string): string {
  const d = new Date(iso + "T00:00:00");
  if (grouping === "monthly") {
    return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  }
  if (grouping === "daily") {
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function trendTitle(grouping?: string): string {
  if (grouping === "daily") return "Daily Ticket Trend";
  if (grouping === "monthly") return "Monthly Ticket Trend";
  return "Weekly Ticket Trend";
}

export default function MonthlyTrendChart({ data, onPointClick }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-gray-400">
        No trend data available
      </div>
    );
  }

  const grouping = data[0]?.grouping;

  const chartData = data.map((d) => ({
    ...d,
    label: formatLabel(d.week, grouping),
  }));

  return (
    <div className="rounded-lg bg-white p-4 shadow">
      <h3 className="mb-3 text-sm font-semibold text-gray-700">
        {trendTitle(grouping)}
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart
          data={chartData}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onClick={onPointClick ? (state: any) => {
            const week = state?.activePayload?.[0]?.payload?.week;
            if (week) onPointClick(week);
          } : undefined}
          style={onPointClick ? { cursor: "pointer" } : undefined}
        >
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
              const w = payload?.[0]?.payload?.week;
              if (!w) return String(_label);
              const g = payload?.[0]?.payload?.grouping;
              if (g === "daily") return w;
              if (g === "monthly") return w.slice(0, 7);
              return `Week of ${w}`;
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
            activeDot={{ r: 5, style: onPointClick ? { cursor: "pointer" } : undefined }}
          />
          <Line
            type="monotone"
            dataKey="resolved"
            name="Resolved"
            stroke="#22c55e"
            strokeWidth={2}
            dot={{ r: 3 }}
            activeDot={{ r: 5, style: onPointClick ? { cursor: "pointer" } : undefined }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
