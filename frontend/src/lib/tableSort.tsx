/**
 * Shared table sorting utilities for Azure portal data tables.
 * Provides a hook for sort state and a SortHeader <th> component.
 */
import { useState } from "react";

export type SortDir = "asc" | "desc";

/** Hook that manages sort key + direction with toggle behaviour. */
export function useTableSort<K extends string>(defaultKey: K, defaultDir: SortDir = "asc") {
  const [sortKey, setSortKey] = useState<K>(defaultKey);
  const [sortDir, setSortDir] = useState<SortDir>(defaultDir);

  function toggleSort(key: K) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  return { sortKey, sortDir, toggleSort };
}

/**
 * Sort an array of rows by a key. Nulls and empty strings always sort last.
 * Pass `accessor` to compute the sort value for computed/derived fields.
 */
export function sortRows<T>(
  rows: T[],
  key: string,
  dir: SortDir,
  accessor?: (item: T, key: string) => string | number | null | undefined,
): T[] {
  const get = accessor ?? ((item: T, k: string) => (item as Record<string, unknown>)[k] as string | number | null | undefined);
  return [...rows].sort((a, b) => {
    const av = get(a, key);
    const bv = get(b, key);
    // nulls / empty always last
    const aNull = av === null || av === undefined || av === "";
    const bNull = bv === null || bv === undefined || bv === "";
    if (aNull && bNull) return 0;
    if (aNull) return 1;
    if (bNull) return -1;
    let cmp: number;
    if (typeof av === "number" && typeof bv === "number") {
      cmp = av - bv;
    } else {
      cmp = String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" });
    }
    return dir === "asc" ? cmp : -cmp;
  });
}

/** Clickable <th> element that shows the active sort direction indicator. */
export function SortHeader<K extends string>({
  col,
  label,
  sortKey,
  sortDir,
  onSort,
  className = "",
  right = false,
}: {
  col: K;
  label: string;
  sortKey: K;
  sortDir: SortDir;
  onSort: (k: K) => void;
  className?: string;
  right?: boolean;
}) {
  const active = col === sortKey;
  return (
    <th
      className={[
        "px-4 py-3 cursor-pointer select-none whitespace-nowrap transition-colors hover:text-slate-800",
        right ? "text-right" : "",
        className,
      ].join(" ")}
      onClick={() => onSort(col)}
    >
      {label}{" "}
      <span className={active ? "text-sky-600" : "text-slate-300"}>
        {active ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
      </span>
    </th>
  );
}
