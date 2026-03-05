import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { TTRBucket } from "../../lib/api.ts";

interface Props {
  data: TTRBucket[];
  onBarClick?: (bucket: string) => void;
}

export default function TTRDistributionChart({ data, onBarClick }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-gray-400">
        No resolution time data available
      </div>
    );
  }

  const total = data.reduce((sum, d) => sum + d.count, 0);

  const dataWithPercent = data.map((d) => ({
    ...d,
    percent: total > 0 ? ((d.count / total) * 100).toFixed(1) : "0",
  }));

  return (
    <div className="rounded-lg bg-white p-4 shadow">
      <h3 className="mb-3 text-sm font-semibold text-gray-700">
        Time-to-Resolution Distribution
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={dataWithPercent}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="bucket"
            tick={{ fontSize: 11, fill: "#6b7280" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#6b7280" }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            formatter={(value: unknown, _name: unknown, props: unknown) => {
              const p = props as { payload?: { percent?: string } };
              const pct = p?.payload?.percent ?? "0";
              return [`${String(value ?? 0)} tickets (${pct}%)`, "Count"];
            }}
            contentStyle={{
              fontSize: 12,
              borderRadius: 8,
              border: "1px solid #e5e7eb",
            }}
          />
          <Bar
            dataKey="count"
            fill="#3b82f6"
            radius={[4, 4, 0, 0]}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            onClick={onBarClick ? (entry: any) => onBarClick(entry.bucket) : undefined}
            style={onBarClick ? { cursor: "pointer" } : undefined}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
