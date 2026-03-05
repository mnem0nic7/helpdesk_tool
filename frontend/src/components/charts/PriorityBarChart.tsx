import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import type { PriorityCount } from "../../lib/api.ts";

interface Props {
  data: PriorityCount[];
  onBarClick?: (priority: string) => void;
}

export default function PriorityBarChart({ data, onBarClick }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-[250px] items-center justify-center text-sm text-gray-400">
        No priority data available
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-white p-4 shadow">
      <h3 className="mb-3 text-sm font-semibold text-gray-700">
        Tickets by Priority
      </h3>
      <ResponsiveContainer width="100%" height={250}>
        <BarChart data={data} layout="vertical">
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            type="number"
            tick={{ fontSize: 11, fill: "#6b7280" }}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="priority"
            tick={{ fontSize: 11, fill: "#6b7280" }}
            tickLine={false}
            width={80}
          />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              borderRadius: 8,
              border: "1px solid #e5e7eb",
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar
            dataKey="total"
            name="Total"
            fill="#3b82f6"
            radius={[0, 4, 4, 0]}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            onClick={onBarClick ? (entry: any) => onBarClick(entry.priority) : undefined}
            style={onBarClick ? { cursor: "pointer" } : undefined}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
