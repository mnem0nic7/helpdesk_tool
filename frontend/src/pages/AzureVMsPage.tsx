import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.ts";

function buildAzurePortalUrl(resourceId: string): string {
  return `https://portal.azure.com/#resource${resourceId}`;
}

function StatCard({ label, value, tone = "text-slate-900" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

export default function AzureVMsPage() {
  const [search, setSearch] = useState("");
  const [subscriptionId, setSubscriptionId] = useState("");
  const [size, setSize] = useState("");
  const [location, setLocation] = useState("");
  const [state, setState] = useState("");

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["azure", "vms", { search, subscriptionId, size, location, state }],
    queryFn: () =>
      api.getAzureVMs({
        search,
        subscription_id: subscriptionId,
        size,
        location,
        state,
      }),
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return <div className="text-sm text-slate-500">Loading Azure virtual machines...</div>;
  }

  if (isError || !data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load Azure VMs: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }

  const subscriptions = Array.from(new Set(data.vms.map((item) => item.subscription_name || item.subscription_id))).sort();
  const sizes = Array.from(new Set(data.vms.map((item) => item.size).filter(Boolean))).sort();
  const locations = Array.from(new Set(data.vms.map((item) => item.location).filter(Boolean))).sort();
  const states = Array.from(new Set(data.vms.map((item) => item.power_state).filter(Boolean))).sort();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">VMs</h1>
        <p className="mt-1 text-sm text-slate-500">
          Review VM inventory here, then jump straight into Azure Portal for hands-on management.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total VMs" value={data.summary.total_vms.toLocaleString()} />
        <StatCard label="Running" value={data.summary.running_vms.toLocaleString()} tone="text-emerald-700" />
        <StatCard label="Deallocated" value={data.summary.deallocated_vms.toLocaleString()} tone="text-amber-700" />
        <StatCard label="Distinct Sizes" value={data.summary.distinct_sizes.toLocaleString()} tone="text-sky-700" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.4fr,1fr]">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Size Footprint</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {data.by_size.slice(0, 12).map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-800">{item.label}</span>
                <span className="text-sm font-semibold text-slate-900">{item.count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Power States</h2>
          <div className="mt-4 space-y-3">
            {data.by_state.map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-xl bg-slate-50 px-4 py-3">
                <span className="text-sm font-medium text-slate-800">{item.label}</span>
                <span className="text-sm font-semibold text-slate-900">{item.count.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm md:grid-cols-2 xl:grid-cols-5">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search VM name, size, tag..."
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
        />
        <select value={subscriptionId} onChange={(event) => setSubscriptionId(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All subscriptions</option>
          {subscriptions.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <select value={size} onChange={(event) => setSize(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">
          <option value="">All sizes</option>
          {sizes.map((value) => <option key={value} value={value}>{value}</option>)}
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

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3 text-sm text-slate-500">
          Showing <span className="font-semibold text-slate-900">{data.matched_count.toLocaleString()}</span> of {data.total_count.toLocaleString()} VMs
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">VM</th>
                <th className="px-4 py-3">Size</th>
                <th className="px-4 py-3">State</th>
                <th className="px-4 py-3">Subscription</th>
                <th className="px-4 py-3">Resource Group</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">Manage</th>
              </tr>
            </thead>
            <tbody>
              {data.vms.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-slate-500">
                    No virtual machines matched the current filters.
                  </td>
                </tr>
              ) : null}
              {data.vms.map((item, index) => (
                <tr key={item.id} className={index % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
                  <td className="px-4 py-3">
                    <div className="font-medium text-slate-900">{item.name}</div>
                    <div className="mt-1 max-w-xl truncate text-xs text-slate-500">{item.id}</div>
                  </td>
                  <td className="px-4 py-3 text-slate-700">{item.size}</td>
                  <td className="px-4 py-3 text-slate-700">{item.power_state}</td>
                  <td className="px-4 py-3 text-slate-700">{item.subscription_name || item.subscription_id}</td>
                  <td className="px-4 py-3 text-slate-700">{item.resource_group || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{item.location || "—"}</td>
                  <td className="px-4 py-3">
                    <a
                      href={buildAzurePortalUrl(item.id)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 transition hover:bg-sky-100"
                    >
                      Manage in Azure
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
