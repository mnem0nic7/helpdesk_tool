import { useDeferredValue, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, type AzureResourceRow } from "../lib/api.ts";
import AzureSavingsHighlightsSection from "../components/AzureSavingsHighlightsSection.tsx";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type ResourceSortKey = "name" | "resource_type" | "subscription" | "resource_group" | "location" | "sku" | "state";

function buildAzurePortalUrl(resourceId: string): string {
  return `https://portal.azure.com/#resource${resourceId}`;
}

function ResourceDetailDrawer({
  resource,
  onClose,
}: {
  resource: AzureResourceRow;
  onClose: () => void;
}) {
  const tagEntries = Object.entries(resource.tags ?? {});

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-3xl flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-slate-200 px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Resource Detail</p>
              <h2 className="mt-1 truncate text-2xl font-bold text-slate-900">{resource.name || resource.id}</h2>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
                <span>{resource.resource_type || "Unknown type"}</span>
                <span>{resource.subscription_name || resource.subscription_id || "No subscription"}</span>
                <span>{resource.resource_group || "No resource group"}</span>
                <span>{resource.location || "Unknown region"}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <a
                href={buildAzurePortalUrl(resource.id)}
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
            {[
              ["Type", resource.resource_type || "—"],
              ["State", resource.state || "—"],
              ["Location", resource.location || "—"],
              ["Kind", resource.kind || "—"],
              ["SKU / Size", resource.vm_size || resource.sku_name || "—"],
              ["Created", resource.created_time || "—"],
              ["Subscription", resource.subscription_name || resource.subscription_id || "—"],
              ["Resource Group", resource.resource_group || "—"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
                <div className="mt-1 break-words text-sm text-slate-700">{value}</div>
              </div>
            ))}
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 md:col-span-2">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Resource ID</div>
              <div className="mt-1 break-words text-sm text-slate-700">{resource.id}</div>
            </div>
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

export default function AzureResourcesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState(() => searchParams.get("search") || "");
  const [subscriptionId, setSubscriptionId] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [location, setLocation] = useState("");
  const [state, setState] = useState("");
  const [selectedResource, setSelectedResource] = useState<AzureResourceRow | null>(null);
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
  const activeResource = selectedResource ? resources.find((resource) => resource.id === selectedResource.id) ?? selectedResource : null;

  useEffect(() => {
    const routeSearch = searchParams.get("search") || "";
    setSearch((current) => (current === routeSearch ? current : routeSearch));
  }, [searchParams]);

  useEffect(() => {
    const resourceId = searchParams.get("resourceId");
    if (!resourceId) {
      setSelectedResource((current) => (current ? null : current));
      return;
    }
    const matched = resources.find((item) => item.id === resourceId);
    if (matched && selectedResource?.id !== matched.id) {
      setSelectedResource(matched);
    }
  }, [resources, searchParams, selectedResource?.id]);

  function updateRouteParams(next: { search?: string | null; resourceId?: string | null }) {
    const params = new URLSearchParams(searchParams);
    if (next.search !== undefined) {
      const value = next.search?.trim();
      if (value) params.set("search", value);
      else params.delete("search");
    }
    if (next.resourceId !== undefined) {
      if (next.resourceId) params.set("resourceId", next.resourceId);
      else params.delete("resourceId");
    }
    setSearchParams(params, { replace: true });
  }

  if (isLoading) {
    return <AzurePageSkeleton titleWidth="w-40" subtitleWidth="w-72" statCount={0} sectionCount={2} />;
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

      <div className="grid gap-4 xl:grid-cols-2">
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 shadow-sm">
          <div className="font-semibold">Cleanup items are ready for action</div>
          <div className="mt-1 text-emerald-800">
            These recommendations already crossed the threshold for safe cleanup review, like unattached public IPs.
          </div>
        </div>
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 shadow-sm">
          <div className="font-semibold">Review items still need human confirmation</div>
          <div className="mt-1 text-amber-800">
            These rows are higher-context network opportunities that still need an operator to verify cost, ownership, or architecture impact.
          </div>
        </div>
      </div>

      <div className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-2 xl:grid-cols-5">
        <input
          value={search}
          onChange={(event) => {
            const value = event.target.value;
            setSearch(value);
            updateRouteParams({ search: value, resourceId: null });
          }}
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
                <tr
                  key={item.id}
                  className={[
                    index % 2 === 0 ? "bg-white" : "bg-slate-50/50",
                    "cursor-pointer transition hover:bg-sky-50/60",
                    activeResource?.id === item.id ? "bg-sky-50" : "",
                  ].join(" ")}
                  onClick={() => {
                    setSelectedResource(item);
                    updateRouteParams({ resourceId: item.id });
                  }}
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900" title={item.id}>{item.name}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {(item.subscription_name || item.subscription_id || "No subscription")}{item.resource_group ? ` / ${item.resource_group}` : ""}
                    </div>
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
              Showing {visibleResources.length.toLocaleString()} of {filtered.length.toLocaleString()} resources — scroll inside this table for more rows
            </div>
          ) : null}
        </div>
      </div>

      {activeResource ? (
        <ResourceDetailDrawer
          resource={activeResource}
          onClose={() => {
            setSelectedResource(null);
            updateRouteParams({ resourceId: null });
          }}
        />
      ) : null}
    </div>
  );
}
