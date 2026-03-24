import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type AzureManagedDisk, type AzureSavingsOpportunity, type AzureStorageAccount } from "../lib/api.ts";
import AzureSourceBadge from "../components/AzureSourceBadge.tsx";
import AzureSavingsHighlightsSection from "../components/AzureSavingsHighlightsSection.tsx";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type AccountSortKey = "name" | "kind" | "sku_name" | "access_tier" | "location" | "subscription" | "resource_group" | "cost";
type DiskSortKey = "name" | "sku_name" | "disk_size_gb" | "location" | "subscription" | "resource_group" | "cost";
type SnapshotSortKey = "name" | "sku_name" | "disk_size_gb" | "location" | "subscription" | "resource_group" | "cost";

type StorageTab = "accounts" | "disks" | "snapshots";

type StorageDetailItem =
  | { kind: "accounts"; item: AzureStorageAccount }
  | { kind: "disks"; item: AzureManagedDisk }
  | { kind: "snapshots"; item: AzureManagedDisk };

function formatCurrency(value: number | null, currency = "USD"): string {
  if (value === null) return "—";
  return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
}

function tooltipCurrency(value: number | string | undefined): string {
  const n = typeof value === "number" ? value : Number(value || 0);
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatCoverageWindow(start?: string | null, end?: string | null): string {
  if (!start || !end) return "";
  if (start === end) return start;
  return `${start} to ${end}`;
}

function buildAzurePortalUrl(resourceId: string): string {
  return `https://portal.azure.com/#resource${resourceId}`;
}

function formatAgeDays(iso: string): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  const days = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 86_400_000));
  return `${days.toLocaleString()}d`;
}

function StorageDetailDrawer({
  detail,
  onClose,
}: {
  detail: StorageDetailItem;
  onClose: () => void;
}) {
  const { kind, item } = detail;
  const tagEntries = Object.entries(item.tags ?? {});
  const title = kind === "accounts" ? "Storage Account Detail" : kind === "disks" ? "Managed Disk Detail" : "Snapshot Detail";

  const fields = [
    ["Name", item.name || "—"],
    ["Subscription", item.subscription_name || item.subscription_id || "—"],
    ["Resource Group", item.resource_group || "—"],
    ["Location", item.location || "—"],
    ["Created", item.created_time || "—"],
  ];

  if (kind === "accounts") {
    fields.push(
      ["Kind", item.kind || "—"],
      ["Tier / SKU", item.sku_name || "—"],
      ["Access Tier", item.access_tier || "—"],
      ["State", item.state || "—"],
    );
  } else {
    fields.push(
      ["SKU", item.sku_name || "—"],
      ["Size", item.disk_size_gb !== null ? `${item.disk_size_gb.toLocaleString()} GB` : "—"],
      ["State", item.disk_state || item.state || "—"],
    );
    if (kind === "disks") {
      fields.push(["Managed By", item.managed_by || "Unattached"]);
    }
    if (kind === "snapshots") {
      fields.push(["Source Disk", item.source_resource_id ? item.source_resource_id.split("/").pop() || item.source_resource_id : "—"]);
      fields.push(["Snapshot Age", formatAgeDays(item.created_time)]);
    }
  }
  fields.push(["Resource ID", item.id]);

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-3xl flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-slate-200 px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
              <h2 className="mt-1 truncate text-2xl font-bold text-slate-900">{item.name || item.id}</h2>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
                <span>{item.subscription_name || item.subscription_id || "No subscription"}</span>
                <span>{item.resource_group || "No resource group"}</span>
                <span>{item.location || "Unknown region"}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <a
                href={buildAzurePortalUrl(item.id)}
                target="_blank"
                rel="noreferrer"
                className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 transition hover:bg-sky-100"
              >
                Open in Azure
              </a>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
              >
                Close
              </button>
            </div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="grid gap-4 md:grid-cols-2">
            {fields.map(([label, value]) => (
              <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
                <div className="mt-1 break-words text-sm text-slate-700">{value}</div>
              </div>
            ))}
          </div>
          {tagEntries.length > 0 ? (
            <section className="mt-6 rounded-2xl border border-slate-200 p-5">
              <h3 className="text-lg font-semibold text-slate-900">Tags</h3>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {tagEntries.map(([key, value]) => (
                  <div key={key} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                    <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{key}</div>
                    <div className="mt-1 break-words text-sm text-slate-700">{String(value)}</div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function CollapsibleEmptySavingsPanel({
  title,
  description,
  emptyMessage,
  opportunities,
  open,
  onToggle,
}: {
  title: string;
  description: string;
  emptyMessage: string;
  opportunities: AzureSavingsOpportunity[];
  open: boolean;
  onToggle: () => void;
}) {
  if (opportunities.length > 0) {
    return (
      <AzureSavingsHighlightsSection
        title={title}
        description={description}
        opportunities={opportunities}
        emptyMessage={emptyMessage}
        maxItems={6}
      />
    );
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <p className="mt-1 text-sm text-slate-500">{description}</p>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
        >
          {open ? "Hide empty panel" : "Show empty panel"}
        </button>
      </div>
      {open ? <p className="mt-5 text-sm text-slate-400">{emptyMessage}</p> : null}
    </section>
  );
}

function StatCard({
  label,
  value,
  sub,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</div>
      {sub ? <div className="mt-1 text-xs text-slate-400">{sub}</div> : null}
    </div>
  );
}

function AccountsTable({
  accounts,
  costAvailable,
  search,
  onSearchChange,
  selectedId,
  onSelect,
}: {
  accounts: AzureStorageAccount[];
  costAvailable: boolean;
  search: string;
  onSearchChange: (value: string) => void;
  selectedId?: string | null;
  onSelect: (item: AzureStorageAccount) => void;
}) {
  const { sortKey, sortDir, toggleSort } = useTableSort<AccountSortKey>("name");
  const sorted = sortRows(accounts, sortKey, sortDir, (a, key) => {
    if (key === "subscription") return a.subscription_name || a.subscription_id;
    if (key === "cost") return a.cost;
    return (a as unknown as Record<string, unknown>)[key] as string;
  });
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(sorted.length, 100, `${search}|${sortKey}|${sortDir}`);
  const visible = sorted.slice(0, visibleCount);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-900">Storage Accounts</h2>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {accounts.length.toLocaleString()} accounts
        </span>
      </div>
      <input
        className="mt-3 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm placeholder-slate-400 focus:border-blue-500 focus:outline-none"
        placeholder="Search by name, kind, SKU, location, subscription…"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
      />
      <div className="mt-4 max-h-[60vh] overflow-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <SortHeader col="name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="kind" label="Kind" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="sku_name" label="Tier / SKU" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="access_tier" label="Access Tier" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="location" label="Location" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="subscription" label="Subscription" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="resource_group" label="Resource Group" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              {costAvailable ? <SortHeader col="cost" label="Cost" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} /> : null}
            </tr>
          </thead>
          <tbody>
            {visible.map((item, idx) => (
              <tr
                key={item.id}
                className={[
                  idx % 2 === 0 ? "bg-white" : "bg-slate-50/50",
                  "cursor-pointer transition hover:bg-sky-50/60",
                  selectedId === item.id ? "bg-sky-50" : "",
                ].join(" ")}
                onClick={() => onSelect(item)}
              >
                <td className="px-4 py-3 font-medium text-slate-900">{item.name}</td>
                <td className="px-4 py-3 text-slate-600">{item.kind || "—"}</td>
                <td className="px-4 py-3 text-slate-600">{item.sku_name || "—"}</td>
                <td className="px-4 py-3 text-slate-600">{item.access_tier || "—"}</td>
                <td className="px-4 py-3 text-slate-600">{item.location}</td>
                <td className="px-4 py-3 text-slate-600">{item.subscription_name || item.subscription_id}</td>
                <td className="px-4 py-3 text-slate-600">{item.resource_group}</td>
                {costAvailable ? (
                  <td className="px-4 py-3 text-right font-semibold text-slate-900">
                    {formatCurrency(item.cost, item.currency)}
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
        {hasMore ? (
          <div ref={sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
            Showing {visible.length.toLocaleString()} of {accounts.length.toLocaleString()} — scroll for more
          </div>
        ) : null}
      </div>
    </section>
  );
}

function DisksTable({
  disks,
  costAvailable,
  search,
  onSearchChange,
  showUnattached,
  onToggleUnattached,
  selectedId,
  onSelect,
}: {
  disks: AzureManagedDisk[];
  costAvailable: boolean;
  search: string;
  onSearchChange: (value: string) => void;
  showUnattached: boolean;
  onToggleUnattached: () => void;
  selectedId?: string | null;
  onSelect: (item: AzureManagedDisk) => void;
}) {
  const { sortKey, sortDir, toggleSort } = useTableSort<DiskSortKey>("name");
  const sorted = sortRows(disks, sortKey, sortDir, (d, key) => {
    if (key === "subscription") return d.subscription_name || d.subscription_id;
    if (key === "cost") return d.cost;
    return (d as unknown as Record<string, unknown>)[key] as string | number;
  });
  const filterKey = [search, String(showUnattached), sortKey, sortDir].join("|");
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(sorted.length, 100, filterKey);
  const visible = sorted.slice(0, visibleCount);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-900">Managed Disks</h2>
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleUnattached}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
              showUnattached
                ? "bg-amber-100 text-amber-800"
                : "bg-slate-100 text-slate-600 hover:bg-slate-200"
            }`}
          >
            Unattached only
          </button>
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
            {disks.length.toLocaleString()} disks
          </span>
        </div>
      </div>
      <input
        className="mt-3 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm placeholder-slate-400 focus:border-blue-500 focus:outline-none"
        placeholder="Search by name, SKU, location, subscription…"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
      />
      <div className="mt-4 max-h-[60vh] overflow-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <SortHeader col="name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="sku_name" label="SKU" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="disk_size_gb" label="Size" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="location" label="Location" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="subscription" label="Subscription" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="resource_group" label="Resource Group" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <th className="px-4 py-3">State</th>
              {costAvailable ? <SortHeader col="cost" label="Cost" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} /> : null}
              {costAvailable ? <th className="px-4 py-3 text-right">Cost/GB</th> : null}
            </tr>
          </thead>
          <tbody>
            {visible.map((item, idx) => {
              const diskState = item.disk_state || (item.managed_by ? "Attached" : "Unattached");
              const stateBadge: Record<string, string> = {
                Attached: "bg-emerald-100 text-emerald-700",
                Unattached: "bg-amber-100 text-amber-700",
                Reserved: "bg-sky-100 text-sky-700",
              };
              const badgeClass = stateBadge[diskState] ?? "bg-slate-100 text-slate-600";
              return (
                <tr
                  key={item.id}
                  className={[
                    idx % 2 === 0 ? "bg-white" : "bg-slate-50/50",
                    "cursor-pointer transition hover:bg-sky-50/60",
                    selectedId === item.id ? "bg-sky-50" : "",
                  ].join(" ")}
                  onClick={() => onSelect(item)}
                >
                  <td className="px-4 py-3 font-medium text-slate-900">{item.name}</td>
                  <td className="px-4 py-3 text-slate-600">{item.sku_name || "—"}</td>
                  <td className="px-4 py-3 text-right text-slate-600">
                    {item.disk_size_gb !== null ? item.disk_size_gb.toLocaleString() + " GB" : "—"}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{item.location}</td>
                  <td className="px-4 py-3 text-slate-600">{item.subscription_name || item.subscription_id}</td>
                  <td className="px-4 py-3 text-slate-600">{item.resource_group}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${badgeClass}`}>
                      {diskState}
                    </span>
                  </td>
                  {costAvailable ? (
                    <td className="px-4 py-3 text-right font-semibold text-slate-900">
                      {formatCurrency(item.cost, item.currency)}
                    </td>
                  ) : null}
                  {costAvailable ? (
                    <td className="px-4 py-3 text-right text-slate-600">
                      {item.cost !== null && item.disk_size_gb
                        ? formatCurrency(item.cost / item.disk_size_gb) + "/GB"
                        : "—"}
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
        {hasMore ? (
          <div ref={sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
            Showing {visible.length.toLocaleString()} of {disks.length.toLocaleString()} — scroll for more
          </div>
        ) : null}
      </div>
    </section>
  );
}

function SnapshotsTable({
  snapshots,
  costAvailable,
  search,
  onSearchChange,
  selectedId,
  onSelect,
}: {
  snapshots: AzureManagedDisk[];
  costAvailable: boolean;
  search: string;
  onSearchChange: (value: string) => void;
  selectedId?: string | null;
  onSelect: (item: AzureManagedDisk) => void;
}) {
  const { sortKey, sortDir, toggleSort } = useTableSort<SnapshotSortKey>("name");
  const sorted = sortRows(snapshots, sortKey, sortDir, (s, key) => {
    if (key === "subscription") return s.subscription_name || s.subscription_id;
    if (key === "cost") return s.cost;
    return (s as unknown as Record<string, unknown>)[key] as string | number;
  });
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(sorted.length, 100, `${search}|${sortKey}|${sortDir}`);
  const visible = sorted.slice(0, visibleCount);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-900">Snapshots</h2>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {snapshots.length.toLocaleString()} snapshots
        </span>
      </div>
      <input
        className="mt-3 w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm placeholder-slate-400 focus:border-blue-500 focus:outline-none"
        placeholder="Search by name, SKU, location, subscription…"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
      />
      <div className="mt-4 max-h-[60vh] overflow-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <SortHeader col="name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="sku_name" label="SKU" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="disk_size_gb" label="Size" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <th className="px-4 py-3 text-right">Age</th>
              <th className="px-4 py-3">Source Disk</th>
              <SortHeader col="location" label="Location" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="subscription" label="Subscription" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              <SortHeader col="resource_group" label="Resource Group" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              {costAvailable ? <SortHeader col="cost" label="Cost" right sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} /> : null}
            </tr>
          </thead>
          <tbody>
            {visible.map((item, idx) => (
              <tr
                key={item.id}
                className={[
                  idx % 2 === 0 ? "bg-white" : "bg-slate-50/50",
                  "cursor-pointer transition hover:bg-sky-50/60",
                  selectedId === item.id ? "bg-sky-50" : "",
                ].join(" ")}
                onClick={() => onSelect(item)}
              >
                <td className="px-4 py-3 font-medium text-slate-900">{item.name}</td>
                <td className="px-4 py-3 text-slate-600">{item.sku_name || "—"}</td>
                <td className="px-4 py-3 text-right text-slate-600">
                  {item.disk_size_gb !== null ? item.disk_size_gb.toLocaleString() + " GB" : "—"}
                </td>
                <td className="px-4 py-3 text-right text-slate-600">{formatAgeDays(item.created_time)}</td>
                <td className="px-4 py-3 text-slate-600">
                  {item.source_resource_id ? item.source_resource_id.split("/").pop() : "—"}
                </td>
                <td className="px-4 py-3 text-slate-600">{item.location}</td>
                <td className="px-4 py-3 text-slate-600">{item.subscription_name || item.subscription_id}</td>
                <td className="px-4 py-3 text-slate-600">{item.resource_group}</td>
                {costAvailable ? (
                  <td className="px-4 py-3 text-right font-semibold text-slate-900">
                    {formatCurrency(item.cost, item.currency)}
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
        {hasMore ? (
          <div ref={sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
            Showing {visible.length.toLocaleString()} of {snapshots.length.toLocaleString()} — scroll for more
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default function AzureStoragePage() {
  const [activeTab, setActiveTab] = useState<StorageTab>("accounts");
  const [accountSearch, setAccountSearch] = useState("");
  const [diskSearch, setDiskSearch] = useState("");
  const [snapshotSearch, setSnapshotSearch] = useState("");
  const [showUnattachedOnly, setShowUnattachedOnly] = useState(false);
  const [showEmptyUnattachedPanel, setShowEmptyUnattachedPanel] = useState(false);
  const [showEmptySnapshotPanel, setShowEmptySnapshotPanel] = useState(false);
  const [selectedItem, setSelectedItem] = useState<StorageDetailItem | null>(null);
  const deferredAccountSearch = useDeferredValue(accountSearch.trim());
  const deferredDiskSearch = useDeferredValue(diskSearch.trim());
  const deferredSnapshotSearch = useDeferredValue(snapshotSearch.trim());

  const { data, isLoading, isError, error } = useQuery({
    queryKey: [
      "azure",
      "storage",
      {
        deferredAccountSearch,
        deferredDiskSearch,
        deferredSnapshotSearch,
        showUnattachedOnly,
      },
    ],
    queryFn: () => api.getAzureStorage({
      account_search: deferredAccountSearch,
      disk_search: deferredDiskSearch,
      snapshot_search: deferredSnapshotSearch,
      disk_unattached_only: showUnattachedOnly,
    }),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });
  const storageSavingsQuery = useQuery({
    queryKey: ["azure", "savings", "storage-page"],
    queryFn: () => api.getAzureSavingsOpportunities({ category: "storage" }),
    refetchInterval: 60_000,
  });

  if (isLoading) return <AzurePageSkeleton titleWidth="w-36" subtitleWidth="w-72" statCount={6} sectionCount={2} />;

  if (isError || !data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load storage data: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }

  const { summary, storage_services_cost, disk_by_sku, accounts_by_kind, cost_available, cost_context } = data;
  const storageSavings = storageSavingsQuery.data ?? [];
  const unattachedDiskSavings = storageSavings.filter((item) => item.opportunity_type === "unattached_managed_disk");
  const staleSnapshotSavings = storageSavings.filter((item) => item.opportunity_type === "stale_snapshot");
  const coverageWindow = formatCoverageWindow(cost_context?.window_start, cost_context?.window_end);

  const diskSkuChartData = Object.entries(disk_by_sku).map(([label, count]) => ({ label, count }));
  const kindChartData = Object.entries(accounts_by_kind).map(([label, count]) => ({ label, count }));

  const tabs: { id: StorageTab; label: string; count: number }[] = [
    { id: "accounts", label: "Storage Accounts", count: summary.total_storage_accounts },
    { id: "disks", label: "Managed Disks", count: summary.total_managed_disks },
    { id: "snapshots", label: "Snapshots", count: summary.total_snapshots },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Storage</h1>
        <p className="mt-1 text-sm text-slate-500">
          Storage accounts, managed disks, and snapshots — inventory and associated costs from cached Azure data.
          {!cost_available && (
            <span className="ml-2 text-amber-600">Per-resource cost data unavailable — showing service-level cost breakdown only.</span>
          )}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <AzureSourceBadge
            label="Cache-backed storage drill-in"
            description="Storage inventory, per-resource costs, and stale object drill-in on this page still come from cached Azure snapshots."
            tone="amber"
          />
          {cost_context && (
            <AzureSourceBadge
              label={cost_context.source_label}
              description={
                cost_context.export_backed
                  ? "Shared cost context is available from local export-backed analytics, even though storage drill-in on this page remains cache-backed."
                  : cost_context.source_description
              }
            />
          )}
        </div>
        {coverageWindow ? (
          <div className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
            Shared cost coverage window: {coverageWindow}
          </div>
        ) : null}
      </div>

      {/* Summary cards */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-7">
        <StatCard label="Storage Accounts" value={summary.total_storage_accounts.toLocaleString()} />
        <StatCard label="Managed Disks" value={summary.total_managed_disks.toLocaleString()} />
        <StatCard label="Snapshots" value={summary.total_snapshots.toLocaleString()} />
        <StatCard
          label="Unattached Disks"
          value={summary.unattached_disks.toLocaleString()}
          sub="Incurring cost with no VM"
          tone={summary.unattached_disks > 0 ? "text-amber-700" : "text-emerald-700"}
        />
        <StatCard
          label="Provisioned Storage"
          value={summary.total_provisioned_gb.toLocaleString() + " GB"}
          sub="Disks + snapshots"
        />
        {cost_available ? (
          <StatCard
            label="Avg Cost / GB"
            value={summary.avg_cost_per_gb !== null ? formatCurrency(summary.avg_cost_per_gb) + "/GB" : "—"}
            sub="Disks + snapshots"
          />
        ) : null}
        <StatCard
          label="Total Storage Cost"
          value={cost_available ? formatCurrency(summary.total_storage_cost) : "Unavailable"}
          sub={cost_available ? "Storage accounts + disks + snapshots" : undefined}
          tone="text-slate-900"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <CollapsibleEmptySavingsPanel
          title="Unattached Disk Savings"
          description="Disks with no current attachment, prioritized by monthly cost where direct cost rows are available."
          opportunities={unattachedDiskSavings}
          emptyMessage="No unattached managed disk savings opportunities are currently flagged."
          open={showEmptyUnattachedPanel}
          onToggle={() => setShowEmptyUnattachedPanel((value) => !value)}
        />
        <CollapsibleEmptySavingsPanel
          title="Stale Snapshot Savings"
          description="Snapshots older than the current 60-day stale threshold, ready for retention review."
          opportunities={staleSnapshotSavings}
          emptyMessage="No stale snapshot savings opportunities are currently flagged."
          open={showEmptySnapshotPanel}
          onToggle={() => setShowEmptySnapshotPanel((value) => !value)}
        />
      </div>

      {/* Charts row */}
      <div className="grid gap-4 xl:grid-cols-2">
        {storage_services_cost.length > 0 && (
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">Storage Cost by Service</h2>
            <div className="mt-4 h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={storage_services_cost} layout="vertical" margin={{ left: 32 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis type="number" tick={{ fontSize: 12 }} />
                  <YAxis dataKey="label" type="category" width={140} tick={{ fontSize: 11 }} />
                  <Tooltip formatter={tooltipCurrency} />
                  <Bar dataKey="amount" fill="#0284c7" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}

        {diskSkuChartData.length > 0 && (
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">Disk SKU Distribution</h2>
            <div className="mt-4 h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={diskSkuChartData} layout="vertical" margin={{ left: 32 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis type="number" tick={{ fontSize: 12 }} allowDecimals={false} />
                  <YAxis dataKey="label" type="category" width={160} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#7c3aed" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}

        {kindChartData.length > 0 && (
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">Storage Account Kinds</h2>
            <div className="mt-4 space-y-3">
              {kindChartData.map(({ label, count }) => (
                <div key={label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                  <span className="text-sm font-medium text-slate-800">{label}</span>
                  <span className="text-sm font-semibold text-slate-900">{count.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      {/* Tab picker */}
      <div className="flex gap-2 border-b border-slate-200">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? "border-b-2 border-blue-600 text-blue-700"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            {tab.label}
            <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
              {tab.count.toLocaleString()}
            </span>
          </button>
        ))}
      </div>

      {activeTab === "accounts" && (
        <AccountsTable
          accounts={data.storage_accounts}
          costAvailable={cost_available}
          search={accountSearch}
          onSearchChange={setAccountSearch}
          selectedId={selectedItem?.item.id}
          onSelect={(item) => setSelectedItem({ kind: "accounts", item })}
        />
      )}
      {activeTab === "disks" && (
        <DisksTable
          disks={data.managed_disks}
          costAvailable={cost_available}
          search={diskSearch}
          onSearchChange={setDiskSearch}
          showUnattached={showUnattachedOnly}
          onToggleUnattached={() => setShowUnattachedOnly((value) => !value)}
          selectedId={selectedItem?.item.id}
          onSelect={(item) => setSelectedItem({ kind: "disks", item })}
        />
      )}
      {activeTab === "snapshots" && (
        <SnapshotsTable
          snapshots={data.snapshots}
          costAvailable={cost_available}
          search={snapshotSearch}
          onSearchChange={setSnapshotSearch}
          selectedId={selectedItem?.item.id}
          onSelect={(item) => setSelectedItem({ kind: "snapshots", item })}
        />
      )}

      {selectedItem ? <StorageDetailDrawer detail={selectedItem} onClose={() => setSelectedItem(null)} /> : null}
    </div>
  );
}
