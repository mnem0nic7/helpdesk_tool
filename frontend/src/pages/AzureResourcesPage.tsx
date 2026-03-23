import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";
import AzureSavingsHighlightsSection from "../components/AzureSavingsHighlightsSection.tsx";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type ResourceSortKey = "name" | "resource_type" | "subscription" | "resource_group" | "location" | "sku" | "state";

export default function AzureResourcesPage() {
  const [search, setSearch] = useState("");
  const [subscriptionId, setSubscriptionId] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [location, setLocation] = useState("");
  const [state, setState] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const { sortKey, sortDir, toggleSort } = useTableSort<ResourceSortKey>("name");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["azure", "resources", { deferredSearch, subscriptionId, resourceType, location, state }],
    queryFn: () => api.getAzureResources({
      search: deferredSearch,
      subscription_id: subscriptionId,
      resource_type: resourceType,
      location,
      state,
    }),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const networkSavingsQuery = useQuery({
    queryKey: ["azure", "savings", "resources-page"],
    queryFn: () => api.getAzureSavingsOpportunities({ category: "network" }),
    refetchInterval: 60_000,
  });
  const resources = data?.resources ?? [];
  const networkSavings = networkSavingsQuery.data ?? [];
  const unattachedPublicIps = networkSavings.filter((item) => item.opportunity_type === "unattached_public_ip");
  const networkReviewRows = networkSavings.filter((item) => item.opportunity_type !== "unattached_public_ip");
  const subscriptions = Array.from(new Set(resources.map((item) => item.subscription_name || item.subscription_id))).sort();
  const resourceTypes = Array.from(new Set(resources.map((item) => item.resource_type).filter(Boolean))).sort();
  const locations = Array.from(new Set(resources.map((item) => item.location).filter(Boolean))).sort();
  const states = Array.from(new Set(resources.map((item) => item.state).filter(Boolean))).sort();
  const filtered = resources;
  const sorted = sortRows(filtered, sortKey, sortDir, (item, key) => {
    if (key === "subscription") return item.subscription_name || item.subscription_id;
    if (key === "sku") return item.vm_size || item.sku_name;
    return (item as unknown as Record<string, unknown>)[key] as string;
  });
  const filterKey = [search, subscriptionId, resourceType, location, state, sortKey, sortDir].join("|");
  const { visibleCount, hasMore, sentinelRef } = useInfiniteScrollCount(sorted.length, 20, filterKey);
  const visibleResources = sorted.slice(0, visibleCount);

  if (isLoading) {
    return <div className="text-sm text-slate-500">Loading Azure resources...</div>;
  }

  if (isError || !data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure resources: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Resources</h1>
        <p className="mt-1 text-sm text-slate-500">
          Explore cached Azure resources across all subscriptions.
        </p>
      </div>

      <div className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-2 xl:grid-cols-5">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search name, group, tag..."
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
        />
        <select value={subscriptionId} onChange={(event) => setSubscriptionId(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All subscriptions</option>
          {subscriptions.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select value={resourceType} onChange={(event) => setResourceType(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All types</option>
          {resourceTypes.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select value={location} onChange={(event) => setLocation(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All locations</option>
          {locations.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select value={state} onChange={(event) => setState(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All states</option>
          {states.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <AzureSavingsHighlightsSection
          title="Network Cleanup"
          description="Directly actionable network savings items from the synthesized Azure savings feed."
          opportunities={unattachedPublicIps}
          emptyMessage="No unattached public IP cleanup actions are currently flagged."
          maxItems={6}
        />
        <AzureSavingsHighlightsSection
          title="Top Cost Network Review"
          description="Network-related savings items that still need human review before remediation."
          opportunities={networkReviewRows}
          emptyMessage="No additional network review items are currently flagged."
          maxItems={6}
        />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3 text-sm text-slate-500">
          Showing <span className="font-semibold text-slate-900">{visibleResources.length.toLocaleString()}</span> of {filtered.length.toLocaleString()} filtered resources
          <span className="text-slate-400"> | </span>
          {(data.total_count ?? resources.length).toLocaleString()} total resources
        </div>
        <div className="max-h-[70vh] overflow-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <SortHeader col="name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="resource_type" label="Type" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="subscription" label="Subscription" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="resource_group" label="Resource Group" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="location" label="Location" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="sku" label="SKU / Size" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="state" label="State" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              </tr>
            </thead>
            <tbody>
              {visibleResources.map((item, index) => (
                <tr key={item.id} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{item.name}</div>
                    <div className="mt-1 max-w-xl truncate text-xs text-slate-500">{item.id}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{item.resource_type}</td>
                  <td className="px-4 py-3 text-slate-700">{item.subscription_name || item.subscription_id}</td>
                  <td className="px-4 py-3 text-slate-700">{item.resource_group || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{item.location || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{item.vm_size || item.sku_name || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{item.state || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {hasMore ? (
            <div ref={sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
              Showing {visibleResources.length.toLocaleString()} of {filtered.length.toLocaleString()} resources — scroll for more
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
