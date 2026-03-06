import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { PieLabelRenderProps } from "recharts";
import type { AgeBucket } from "../../lib/api.ts";

interface Props {
  data: AgeBucket[];
  onSliceClick?: (bucket: string) => void;
}

/** Gradient from green (newest) to red (oldest) based on position. */
const GRADIENT_COLORS = ["#22c55e", "#84cc16", "#eab308", "#f97316", "#ef4444", "#dc2626", "#991b1b"];

function getColor(_bucket: string, index: number, total: number): string {
  const i = Math.round((index / Math.max(total - 1, 1)) * (GRADIENT_COLORS.length - 1));
  return GRADIENT_COLORS[i];
}

function renderLabel(props: PieLabelRenderProps): string {
  const name = String(props.name ?? "");
  const pct =
    typeof props.percent === "number"
      ? (props.percent * 100).toFixed(1)
      : "0";
  return `${name} (${pct}%)`;
}

export default function AgingPieChart({ data, onSliceClick }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-gray-400">
        No aging data available
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-white p-4 shadow">
      <h3 className="mb-3 text-sm font-semibold text-gray-700">
        Open Ticket Age Distribution
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={data}
            dataKey="count"
            nameKey="bucket"
            cx="50%"
            cy="50%"
            outerRadius={100}
            label={renderLabel}
            onClick={onSliceClick ? (_, idx) => onSliceClick(data[idx].bucket) : undefined}
            style={onSliceClick ? { cursor: "pointer" } : undefined}
          >
            {data.map((entry, idx) => (
              <Cell key={entry.bucket} fill={getColor(entry.bucket, idx, data.length)} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value: unknown, name: unknown) => [
              `${String(value ?? 0)} tickets`,
              String(name ?? ""),
            ]}
            contentStyle={{
              fontSize: 12,
              borderRadius: 8,
              border: "1px solid #e5e7eb",
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
