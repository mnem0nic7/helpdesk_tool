import { useEffect, useRef, useState } from "react";

export interface TicketFilterValues {
  search: string;
  status: string;
  priority: string;
  open_only: boolean;
  stale_only: boolean;
}

export const emptyFilters: TicketFilterValues = {
  search: "",
  status: "",
  priority: "",
  open_only: false,
  stale_only: false,
};

const STATUSES = [
  "Acknowledged",
  "In Progress",
  "Waiting for support",
  "Waiting for customer",
  "Resolved",
  "Closed",
];

const PRIORITIES = ["Highest", "High", "Medium", "Low", "Lowest"];

interface TicketFiltersProps {
  filters: TicketFilterValues;
  onFilterChange: (filters: TicketFilterValues) => void;
}

export default function TicketFilters({
  filters,
  onFilterChange,
}: TicketFiltersProps) {
  const [searchInput, setSearchInput] = useState(filters.search);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync local search input when filters reset externally
  useEffect(() => {
    setSearchInput(filters.search);
  }, [filters.search]);

  function handleSearchChange(value: string) {
    setSearchInput(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onFilterChange({ ...filters, search: value });
    }, 300);
  }

  function handleChange(field: keyof TicketFilterValues, value: string | boolean) {
    onFilterChange({ ...filters, [field]: value });
  }

  function handleClear() {
    setSearchInput("");
    onFilterChange({ ...emptyFilters });
  }

  const hasActiveFilters =
    filters.search !== "" ||
    filters.status !== "" ||
    filters.priority !== "" ||
    filters.open_only ||
    filters.stale_only;

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Search */}
      <input
        type="text"
        placeholder="Search tickets..."
        value={searchInput}
        onChange={(e) => handleSearchChange(e.target.value)}
        className="h-9 w-56 rounded-md border border-gray-300 bg-white px-3 text-sm
                   text-gray-700 placeholder-gray-400 shadow-sm
                   focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      />

      {/* Status dropdown */}
      <select
        value={filters.status}
        onChange={(e) => handleChange("status", e.target.value)}
        className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm
                   text-gray-700 shadow-sm
                   focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        <option value="">All Statuses</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      {/* Priority dropdown */}
      <select
        value={filters.priority}
        onChange={(e) => handleChange("priority", e.target.value)}
        className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm
                   text-gray-700 shadow-sm
                   focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        <option value="">All Priorities</option>
        {PRIORITIES.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </select>

      {/* Toggle: Open Only */}
      <button
        type="button"
        onClick={() => handleChange("open_only", !filters.open_only)}
        className={[
          "h-9 rounded-md border px-3 text-sm font-medium shadow-sm transition-colors",
          filters.open_only
            ? "border-blue-600 bg-blue-600 text-white"
            : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
        ].join(" ")}
      >
        Open Only
      </button>

      {/* Toggle: Stale Only */}
      <button
        type="button"
        onClick={() => handleChange("stale_only", !filters.stale_only)}
        className={[
          "h-9 rounded-md border px-3 text-sm font-medium shadow-sm transition-colors",
          filters.stale_only
            ? "border-amber-600 bg-amber-600 text-white"
            : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50",
        ].join(" ")}
      >
        Stale Only
      </button>

      {/* Clear Filters */}
      {hasActiveFilters && (
        <button
          type="button"
          onClick={handleClear}
          className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm
                     font-medium text-red-600 shadow-sm transition-colors
                     hover:bg-red-50"
        >
          Clear Filters
        </button>
      )}
    </div>
  );
}
