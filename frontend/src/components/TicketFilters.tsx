import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import type { Assignee } from "../lib/api.ts";

export interface TicketFilterValues {
  search: string;
  status: string;
  priority: string;
  issue_type: string;
  label: string;
  open_only: boolean;
  stale_only: boolean;
  created_after: string;
  created_before: string;
  assignee: string;
}

export const emptyFilters: TicketFilterValues = {
  search: "",
  status: "",
  priority: "",
  issue_type: "",
  label: "",
  open_only: true,
  stale_only: false,
  created_after: "",
  created_before: "",
  assignee: "",
};

const FALLBACK_STATUSES = [
  "Acknowledged",
  "In Progress",
  "Waiting for support",
  "Waiting for customer",
  "Resolved",
  "Closed",
];

const FALLBACK_PRIORITIES = ["Highest", "High", "Medium", "Low", "Lowest"];

const FALLBACK_ISSUE_TYPES = ["[System] Service request", "[System] Change"];
const FALLBACK_LABELS: string[] = [];

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

  const { data: filterOptions } = useQuery({
    queryKey: ["filter-options"],
    queryFn: () => api.getFilterOptions(),
    staleTime: 5 * 60 * 1000,
  });
  const STATUSES = filterOptions?.statuses ?? FALLBACK_STATUSES;
  const PRIORITIES = filterOptions?.priorities ?? FALLBACK_PRIORITIES;
  const ISSUE_TYPES = filterOptions?.issue_types ?? FALLBACK_ISSUE_TYPES;
  const LABELS = filterOptions?.labels ?? FALLBACK_LABELS;

  const { data: assignees } = useQuery({
    queryKey: ["assignees"],
    queryFn: () => api.getAssignees(),
    staleTime: Infinity,
  });
  const sortedAssignees = (assignees ?? [])
    .filter((a: Assignee) => a.display_name)
    .slice()
    .sort((a: Assignee, b: Assignee) =>
      a.display_name.localeCompare(b.display_name)
    );

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

  const hasActiveFilters = (Object.keys(emptyFilters) as (keyof TicketFilterValues)[])
    .some((key) => filters[key] !== emptyFilters[key]);

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

      {/* Issue Type dropdown */}
      <select
        value={filters.issue_type}
        onChange={(e) => handleChange("issue_type", e.target.value)}
        className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm
                   text-gray-700 shadow-sm
                   focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        <option value="">All Types</option>
        {ISSUE_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      {/* Label dropdown */}
      <select
        value={filters.label}
        onChange={(e) => handleChange("label", e.target.value)}
        className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm
                   text-gray-700 shadow-sm
                   focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        <option value="">All Tags</option>
        {LABELS.map((label) => (
          <option key={label} value={label}>
            {label}
          </option>
        ))}
      </select>

      {/* Assignee dropdown */}
      <select
        value={filters.assignee}
        onChange={(e) => handleChange("assignee", e.target.value)}
        className="h-9 rounded-md border border-gray-300 bg-white px-3 text-sm
                   text-gray-700 shadow-sm
                   focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        <option value="">All Assignees</option>
        {sortedAssignees.map((a: Assignee) => (
          <option key={a.account_id} value={a.display_name}>
            {a.display_name}
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

      {/* Created After */}
      <input
        type="date"
        value={filters.created_after}
        onChange={(e) => handleChange("created_after", e.target.value)}
        title="Created after"
        placeholder="From date"
        className="h-9 rounded-md border border-gray-300 bg-white px-2 text-sm
                   text-gray-700 shadow-sm
                   focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      />

      {/* Created Before */}
      <input
        type="date"
        value={filters.created_before}
        onChange={(e) => handleChange("created_before", e.target.value)}
        title="Created before"
        placeholder="To date"
        className="h-9 rounded-md border border-gray-300 bg-white px-2 text-sm
                   text-gray-700 shadow-sm
                   focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      />

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
