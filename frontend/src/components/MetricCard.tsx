interface MetricCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  trend?: "up" | "down" | "neutral";
  color?: "blue" | "green" | "red" | "yellow";
  onClick?: () => void;
}

const colorMap = {
  blue: "text-blue-600",
  green: "text-green-600",
  red: "text-red-600",
  yellow: "text-yellow-600",
} as const;

const trendIcons: Record<string, { symbol: string; className: string }> = {
  up: { symbol: "\u25B2", className: "text-green-500" },
  down: { symbol: "\u25BC", className: "text-red-500" },
  neutral: { symbol: "\u25C6", className: "text-gray-400" },
};

export default function MetricCard({
  label,
  value,
  subtitle,
  trend,
  color = "blue",
  onClick,
}: MetricCardProps) {
  const clickable = !!onClick;
  return (
    <div
      className={[
        "rounded-lg bg-white px-5 py-4 shadow",
        clickable
          ? "cursor-pointer transition-shadow hover:shadow-md hover:ring-1 hover:ring-blue-200"
          : "",
      ].join(" ")}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } : undefined}
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
    >
      <p className="text-xs font-medium tracking-wide text-gray-500 uppercase">
        {label}
      </p>
      <div className="mt-2 flex items-baseline gap-2">
        <span className={`text-2xl font-bold ${colorMap[color]}`}>
          {value}
        </span>
        {trend && (
          <span className={`text-sm ${trendIcons[trend].className}`}>
            {trendIcons[trend].symbol}
          </span>
        )}
      </div>
      {subtitle && (
        <p className="mt-1 text-xs text-gray-400">{subtitle}</p>
      )}
    </div>
  );
}
