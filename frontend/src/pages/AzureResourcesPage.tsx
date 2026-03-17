import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";

export default function AzureResourcesPage() {
  const [search, setSearch] = useState("");
  const [subscriptionId, setSubscriptionId] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [location, setLocation] = useState("");
  const [state, setState] = useState("");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["azure", "resources"],
    queryFn: () => api.getAzureResources(),
    refetchInterval: 30_000,
  });

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

  const subscriptions = Array.from(new Set(data.resources.map((item) => item.subscription_name || item.subscription_id))).sort();
  const resourceTypes = Array.from(new Set(data.resources.map((item) => item.resource_type).filter(Boolean))).sort();
  const locations = Array.from(new Set(data.resources.map((item) => item.location).filter(Boolean))).sort();
  const states = Array.from(new Set(data.resources.map((item) => item.state).filter(Boolean))).sort();

  const filtered = data.resources.filter((item) => {
    const searchLower = search.trim().toLowerCase();
    if (searchLower) {
      const haystack = [
        item.name,
        item.resource_type,
        item.subscription_name,
        item.resource_group,
        item.location,
        item.sku_name,
        item.vm_size,
        item.state,
        ...Object.entries(item.tags || {}).map(([key, value]) => `${key}:${value}`),
      ].join(" ").toLowerCase();
      if (!haystack.includes(searchLower)) return false;
    }
    if (subscriptionId && (item.subscription_name || item.subscription_id) !== subscriptionId) return false;
    if (resourceType && item.resource_type !== resourceType) return false;
    if (location && item.location !== location) return false;
    if (state && item.state !== state) return false;
    return true;
  });

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

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3 text-sm text-slate-500">
          Showing <span className="font-semibold text-slate-900">{filtered.length.toLocaleString()}</span> of {data.total_count.toLocaleString()} resources
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Type</th>
                <th className="px-4 py-3">Subscription</th>
                <th className="px-4 py-3">Resource Group</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">SKU / Size</th>
                <th className="px-4 py-3">State</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item, index) => (
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
        </div>
      </div>
    </div>
  );
}
