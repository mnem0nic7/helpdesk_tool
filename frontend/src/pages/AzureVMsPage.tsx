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

function coverageTone(status: "needed" | "excess" | "balanced" | "unavailable"): string {
  switch (status) {
    case "needed":
      return "text-amber-700";
    case "excess":
      return "text-sky-700";
    case "balanced":
      return "text-emerald-700";
    default:
      return "text-slate-400";
  }
}

function coverageLabel(delta: number | null): string {
  if (delta === null) return "Unavailable";
  if (delta > 0) return `${delta.toLocaleString()} needed`;
  if (delta < 0) return `${Math.abs(delta).toLocaleString()} excess`;
  return "Balanced";
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
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Size Footprint vs Reserved Instances</h2>
              <p className="mt-1 text-xs text-slate-500">Tenant-wide exact-SKU comparison.</p>
            </div>
            <div
              className={[
                "rounded-full px-3 py-1 text-xs font-semibold",
                data.reservation_data_available
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-amber-50 text-amber-700",
              ].join(" ")}
            >
              {data.reservation_data_available ? "RI data connected" : "RI data unavailable"}
            </div>
          </div>
          {!data.reservation_data_available ? (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              Reserved-instance counts are unavailable with the current Azure permissions. VM counts are still shown.
            </div>
          ) : null}
          <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
            <div className="grid grid-cols-[minmax(0,1.8fr),0.8fr,0.9fr,1fr] bg-slate-50 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <div>SKU</div>
              <div className="text-right">VMs</div>
              <div className="text-right">Reserved</div>
              <div className="text-right">Needed / Excess</div>
            </div>
            <div className="divide-y divide-slate-200">
              {data.by_size.length === 0 ? (
                <div className="px-4 py-8 text-center text-sm text-slate-500">
                  No VM size footprint data is available yet.
                </div>
              ) : null}
              {data.by_size.slice(0, 12).map((item) => (
                <div
                  key={item.label}
                  className="grid grid-cols-[minmax(0,1.8fr),0.8fr,0.9fr,1fr] items-center gap-3 px-4 py-3 text-sm"
                >
                  <div className="truncate font-medium text-slate-800">{item.label}</div>
                  <div className="text-right font-semibold text-slate-900">{item.vm_count.toLocaleString()}</div>
                  <div className="text-right font-semibold text-slate-900">
                    {item.reserved_instance_count === null ? "—" : item.reserved_instance_count.toLocaleString()}
                  </div>
                  <div className={`text-right font-semibold ${coverageTone(item.coverage_status)}`}>
                    {coverageLabel(item.delta)}
                  </div>
                </div>
              ))}
            </div>
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
