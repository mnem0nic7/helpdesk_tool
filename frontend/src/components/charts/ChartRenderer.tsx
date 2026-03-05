import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  AreaChart,
  Area,
  Legend,
} from "recharts";
import type { PieLabelRenderProps } from "recharts";
import type { ChartDataPoint, ChartTimeseriesPoint } from "../../lib/api.ts";

const COLORS = [
  "#3b82f6", "#22c55e", "#f97316", "#ef4444", "#8b5cf6",
  "#eab308", "#06b6d4", "#ec4899", "#14b8a6", "#f43f5e",
];

function renderPieLabel(props: PieLabelRenderProps): string {
  const name = String(props.name ?? "");
  const pct = typeof props.percent === "number" ? (props.percent * 100).toFixed(0) : "0";
  return `${name} (${pct}%)`;
}

const axisStyle = { fontSize: 11, fill: "#6b7280" };

const tooltipStyle = {
  contentStyle: {
    borderRadius: 8,
    border: "1px solid #e5e7eb",
    fontSize: 12,
    boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
  },
};

export type GroupedChartType = "bar" | "horizontal_bar" | "pie" | "donut";
export type TimeseriesChartType = "line" | "area";
export type ChartType = GroupedChartType | TimeseriesChartType;

interface GroupedProps {
  type: GroupedChartType;
  data: ChartDataPoint[];
  metricLabel?: string;
}

interface TimeseriesProps {
  type: TimeseriesChartType;
  data: ChartTimeseriesPoint[];
}

type Props = GroupedProps | TimeseriesProps;

function isTimeseries(props: Props): props is TimeseriesProps {
  return props.type === "line" || props.type === "area";
}

function GroupedChart({ type, data, metricLabel }: GroupedProps) {
  if (!data.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        No data to display
      </div>
    );
  }

  if (type === "pie" || type === "donut") {
    const innerRadius = type === "donut" ? 60 : 0;
    return (
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            cx="50%"
            cy="50%"
            innerRadius={innerRadius}
            outerRadius={120}
            paddingAngle={1}
            label={renderPieLabel}
            labelLine={{ strokeWidth: 1, stroke: "#9ca3af" }}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip {...tooltipStyle} />
        </PieChart>
      </ResponsiveContainer>
    );
  }

  if (type === "horizontal_bar") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 20, right: 20, top: 10, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tick={axisStyle} axisLine={false} />
          <YAxis
            type="category"
            dataKey="label"
            tick={axisStyle}
            axisLine={false}
            width={100}
          />
          <Tooltip {...tooltipStyle} />
          <Bar dataKey="value" name={metricLabel ?? "Value"} radius={[0, 4, 4, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  }

  // Default: vertical bar
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ left: 10, right: 10, top: 10, bottom: 10 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="label" tick={axisStyle} axisLine={false} />
        <YAxis tick={axisStyle} axisLine={false} />
        <Tooltip {...tooltipStyle} />
        <Bar dataKey="value" name={metricLabel ?? "Value"} radius={[4, 4, 0, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function TimeseriesChart({ type, data }: TimeseriesProps) {
  if (!data.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        No data to display
      </div>
    );
  }

  if (type === "area") {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ left: 10, right: 10, top: 10, bottom: 10 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="period" tick={axisStyle} axisLine={false} />
          <YAxis tick={axisStyle} axisLine={false} />
          <Tooltip {...tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area
            type="monotone"
            dataKey="created"
            stackId="1"
            stroke="#3b82f6"
            fill="#3b82f6"
            fillOpacity={0.3}
            name="Created"
          />
          <Area
            type="monotone"
            dataKey="resolved"
            stackId="1"
            stroke="#22c55e"
            fill="#22c55e"
            fillOpacity={0.3}
            name="Resolved"
          />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  // Default: line chart
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ left: 10, right: 10, top: 10, bottom: 10 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="period" tick={axisStyle} axisLine={false} />
        <YAxis tick={axisStyle} axisLine={false} />
        <Tooltip {...tooltipStyle} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line
          type="monotone"
          dataKey="created"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={{ r: 3 }}
          name="Created"
        />
        <Line
          type="monotone"
          dataKey="resolved"
          stroke="#22c55e"
          strokeWidth={2}
          dot={{ r: 3 }}
          name="Resolved"
        />
        <Line
          type="monotone"
          dataKey="net_flow"
          stroke="#f97316"
          strokeWidth={2}
          strokeDasharray="5 5"
          dot={{ r: 3 }}
          name="Net Flow"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export default function ChartRenderer(props: Props) {
  if (isTimeseries(props)) {
    return <TimeseriesChart {...props} />;
  }
  return <GroupedChart {...props} />;
}
