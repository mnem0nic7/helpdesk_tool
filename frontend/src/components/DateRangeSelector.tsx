import { useState } from "react";

export interface DateRange {
  date_from?: string;
  date_to?: string;
}

interface Props {
  value: DateRange;
  onChange: (range: DateRange) => void;
}

type Preset = "all" | "7d" | "30d" | "90d" | "12mo" | "custom";

const PRESET_LABELS: { key: Preset; label: string }[] = [
  { key: "all", label: "All Time" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
  { key: "90d", label: "90d" },
  { key: "12mo", label: "12mo" },
  { key: "custom", label: "Custom" },
];

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function monthsAgo(n: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return d.toISOString().slice(0, 10);
}

function detectPreset(range: DateRange): Preset {
  if (!range.date_from && !range.date_to) return "all";
  if (range.date_from && !range.date_to) {
    const from = range.date_from;
    if (from === daysAgo(7) || from === daysAgo(6)) return "7d";
    if (from === daysAgo(30) || from === daysAgo(29)) return "30d";
    if (from === daysAgo(90) || from === daysAgo(89)) return "90d";
    const m12 = monthsAgo(12);
    if ((from >= daysAgo(367) && from <= daysAgo(363)) || from === m12) return "12mo";
  }
  return "custom";
}

export default function DateRangeSelector({ value, onChange }: Props) {
  const activePreset = detectPreset(value);
  const [showCustom, setShowCustom] = useState(activePreset === "custom");

  function handlePreset(preset: Preset) {
    if (preset === "custom") {
      setShowCustom(true);
      return;
    }
    setShowCustom(false);
    switch (preset) {
      case "all":
        onChange({});
        break;
      case "7d":
        onChange({ date_from: daysAgo(7) });
        break;
      case "30d":
        onChange({ date_from: daysAgo(30) });
        break;
      case "90d":
        onChange({ date_from: daysAgo(90) });
        break;
      case "12mo":
        onChange({ date_from: monthsAgo(12) });
        break;
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {PRESET_LABELS.map(({ key, label }) => {
        const isActive =
          key === "custom" ? showCustom : !showCustom && activePreset === key;
        return (
          <button
            key={key}
            type="button"
            onClick={() => handlePreset(key)}
            className={[
              "h-8 rounded-md border px-3 text-sm font-medium shadow-sm transition-colors",
              isActive
                ? "border-blue-600 bg-blue-600 text-white"
                : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
            ].join(" ")}
          >
            {label}
          </button>
        );
      })}

      {showCustom && (
        <>
          <input
            type="date"
            value={value.date_from ?? ""}
            onChange={(e) =>
              onChange({ ...value, date_from: e.target.value || undefined })
            }
            className="h-8 rounded-md border border-gray-300 bg-white px-2 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-400">to</span>
          <input
            type="date"
            value={value.date_to ?? ""}
            onChange={(e) =>
              onChange({ ...value, date_to: e.target.value || undefined })
            }
            className="h-8 rounded-md border border-gray-300 bg-white px-2 text-sm text-gray-700 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </>
      )}
    </div>
  );
}
