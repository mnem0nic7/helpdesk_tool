import { useDeferredValue, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import {
  api,
  type SecurityAppHygieneApp,
  type SecurityAppHygieneCredential,
  type SecurityAppHygieneMetric,
} from "../lib/api.ts";

type AppStatusFilter = "all" | "critical" | "warning" | "healthy";
type CredentialStatusFilter = "all" | "expired" | "expiring" | "active";

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No timestamp recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function toneClasses(tone: "slate" | "sky" | "emerald" | "amber" | "rose"): string {
  if (tone === "sky") return "bg-sky-50 text-sky-700";
  if (tone === "emerald") return "bg-emerald-50 text-emerald-700";
  if (tone === "amber") return "bg-amber-50 text-amber-700";
  if (tone === "rose") return "bg-rose-50 text-rose-700";
  return "bg-slate-100 text-slate-600";
}

function appTone(status: SecurityAppHygieneApp["status"]): "rose" | "amber" | "emerald" | "slate" {
  if (status === "critical") return "rose";
  if (status === "warning") return "amber";
  if (status === "healthy") return "emerald";
  return "slate";
}

function credentialTone(status: SecurityAppHygieneCredential["status"]): "rose" | "amber" | "emerald" | "slate" {
  if (status === "expired") return "rose";
  if (status === "expiring") return "amber";
  if (status === "active") return "emerald";
  return "slate";
}

function matchesSearch(parts: Array<string | string[]>, search: string): boolean {
  if (!search) return true;
  const normalizedSearch = search.toLowerCase();
  return parts
    .flatMap((part) => (Array.isArray(part) ? part : [part]))
    .some((part) => String(part || "").toLowerCase().includes(normalizedSearch));
}

function MetricCard({ metric }: { metric: SecurityAppHygieneMetric }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{metric.label}</div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${toneClasses(metric.tone)}`}>{metric.label}</span>
      </div>
      <div className="mt-3 text-3xl font-semibold text-slate-900">{metric.value.toLocaleString()}</div>
      <p className="mt-2 text-sm leading-6 text-slate-600">{metric.detail}</p>
    </section>
  );
}

function AppCard({ app }: { app: SecurityAppHygieneApp }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">{app.display_name}</h3>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${toneClasses(appTone(app.status))}`}>
              {app.status === "critical" ? "Critical" : app.status === "warning" ? "Needs review" : "Healthy"}
            </span>
          </div>
          <div className="mt-2 text-sm text-slate-500">{app.app_id || app.application_id}</div>
        </div>
        <Link
          to={`/identity?tab=app-registrations&objectId=${encodeURIComponent(app.application_id)}`}
          className="inline-flex items-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
        >
          Open app registration
        </Link>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Owners</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{app.owner_count.toLocaleString()}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Credentials</div>
          <div className="mt-1 text-lg font-semibold text-slate-900">{app.credential_count.toLocaleString()}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Next expiry</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{formatTimestamp(app.next_credential_expiry)}</div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">{app.sign_in_audience || "Audience unknown"}</span>
        {app.publisher_domain ? (
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">{app.publisher_domain}</span>
        ) : null}
        {app.verified_publisher_name ? (
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
            Verified: {app.verified_publisher_name}
          </span>
        ) : null}
      </div>

      {app.owners.length > 0 ? (
        <div className="mt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Owners</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {app.owners.map((owner) => (
              <span key={`${app.application_id}-${owner}`} className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-800">
                {owner}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-4 space-y-2">
        {app.flags.map((flag) => (
          <div key={`${app.application_id}-${flag}`} className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {flag}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function AzureSecurityAppHygienePage() {
  const [search, setSearch] = useState("");
  const [appStatusFilter, setAppStatusFilter] = useState<AppStatusFilter>("all");
  const [credentialStatusFilter, setCredentialStatusFilter] = useState<CredentialStatusFilter>("all");
  const deferredSearch = useDeferredValue(search);

  const query = useQuery({
    queryKey: ["azure", "security", "app-hygiene"],
    queryFn: () => api.getAzureSecurityAppHygiene(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const filteredApps = useMemo(() => {
    const rows = query.data?.flagged_apps ?? [];
    return rows.filter((app) => {
      if (appStatusFilter !== "all" && app.status !== appStatusFilter) {
        return false;
      }
      return matchesSearch(
        [app.display_name, app.app_id, app.publisher_domain, app.sign_in_audience, app.owners, app.flags],
        deferredSearch,
      );
    });
  }, [appStatusFilter, deferredSearch, query.data?.flagged_apps]);

  const filteredCredentials = useMemo(() => {
    const rows = query.data?.credentials ?? [];
    return rows.filter((credential) => {
      if (credentialStatusFilter !== "all" && credential.status !== credentialStatusFilter) {
        return false;
      }
      return matchesSearch(
        [credential.application_display_name, credential.app_id, credential.display_name, credential.owners, credential.flags],
        deferredSearch,
      );
    });
  }, [credentialStatusFilter, deferredSearch, query.data?.credentials]);

  if (query.isLoading) {
    return <AzurePageSkeleton titleWidth="w-64" subtitleWidth="w-[44rem]" statCount={6} sectionCount={4} />;
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load application hygiene: {query.error instanceof Error ? query.error.message : "Unknown error"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-amber-50 p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-[0.24em] text-amber-700">Azure Security</div>
            <h1 className="mt-3 text-3xl font-bold text-slate-900">Application Hygiene</h1>
            <p className="mt-3 text-sm leading-7 text-slate-600">
              Track app registration credential expiry, owner coverage, external audience exposure, and publisher trust signals from the cached
              Microsoft Graph directory dataset.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              to="/security"
              className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Back to Security workspace
            </Link>
            <Link
              to="/identity?tab=app-registrations"
              className="inline-flex items-center rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-amber-700"
            >
              Open app inventory
            </Link>
          </div>
        </div>

        <div className="mt-5 rounded-2xl border border-white/70 bg-white/80 px-4 py-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Directory refresh</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{formatTimestamp(query.data.directory_last_refresh)}</div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-3 md:grid-cols-2">
        {query.data.metrics.map((metric) => (
          <MetricCard key={metric.key} metric={metric} />
        ))}
      </section>

      {query.data.warnings.length > 0 ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-amber-900">Coverage warnings</h2>
          <div className="mt-3 space-y-2">
            {query.data.warnings.map((warning) => (
              <div key={warning} className="rounded-xl bg-white/70 px-4 py-3 text-sm text-amber-900">
                {warning}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Scope and filters</h2>
            <div className="mt-1 text-sm text-slate-500">Search by app name, app ID, owner, or risk flag to focus the review.</div>
          </div>
          <div className="text-sm text-slate-500">{filteredApps.length.toLocaleString()} flagged app(s)</div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search app names, IDs, owners, publishers, or flags..."
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
          />
          <select
            value={appStatusFilter}
            onChange={(event) => setAppStatusFilter(event.target.value as AppStatusFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
          >
            <option value="all">All app statuses</option>
            <option value="critical">Critical only</option>
            <option value="warning">Needs review</option>
            <option value="healthy">Healthy only</option>
          </select>
          <select
            value={credentialStatusFilter}
            onChange={(event) => setCredentialStatusFilter(event.target.value as CredentialStatusFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-amber-400 focus:ring-2 focus:ring-amber-100"
          >
            <option value="all">All credential states</option>
            <option value="expired">Expired</option>
            <option value="expiring">Expiring soon</option>
            <option value="active">Active</option>
          </select>
        </div>

        <div className="mt-4 grid gap-2">
          {query.data.scope_notes.map((note) => (
            <div key={note} className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
              {note}
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Flagged app registrations</h2>
            <div className="mt-1 text-sm text-slate-500">High-signal app registrations that need credential rotation, owner cleanup, or trust review.</div>
          </div>
          <div className="text-sm text-slate-500">{filteredApps.length.toLocaleString()} app(s) in view</div>
        </div>

        {filteredApps.length === 0 ? (
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-10 text-center text-sm text-slate-500 shadow-sm">
            No flagged app registrations match the current filters.
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {filteredApps.map((app) => (
              <AppCard key={app.application_id} app={app} />
            ))}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-slate-900">Credential watch table</h2>
          <div className="mt-1 text-sm text-slate-500">Credential-level view for expired and expiring app secrets and certificates.</div>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">Application</th>
                <th className="px-4 py-3">Credential</th>
                <th className="px-4 py-3">Expiry</th>
                <th className="px-4 py-3">Owners</th>
                <th className="px-4 py-3">Flags</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {filteredCredentials.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-sm text-slate-500">
                    No credentials match the current filters.
                  </td>
                </tr>
              ) : null}
              {filteredCredentials.map((credential) => (
                <tr key={`${credential.application_id}-${credential.key_id || credential.display_name}`}>
                  <td className="px-4 py-4 align-top">
                    <div className="font-medium text-slate-900">{credential.application_display_name}</div>
                    <div className="mt-1 text-xs text-slate-500">{credential.app_id || credential.application_id}</div>
                    <Link
                      to={`/identity?tab=app-registrations&objectId=${encodeURIComponent(credential.application_id)}`}
                      className="mt-2 inline-flex text-xs font-medium text-amber-700 hover:text-amber-800"
                    >
                      Open app registration
                    </Link>
                  </td>
                  <td className="px-4 py-4 align-top">
                    <div className="font-medium text-slate-900">{credential.display_name || "Unnamed credential"}</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                        {credential.credential_type === "secret" ? "Client secret" : "Certificate"}
                      </span>
                      <span className={`rounded-full px-3 py-1 text-xs font-medium ${toneClasses(credentialTone(credential.status))}`}>
                        {credential.status === "expired"
                          ? "Expired"
                          : credential.status === "expiring"
                            ? "Expiring"
                            : credential.status === "active"
                              ? "Active"
                              : "Unknown"}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-4 align-top">
                    <div className="font-medium text-slate-900">{formatTimestamp(credential.end_date_time)}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {credential.days_until_expiry === null
                        ? "Expiry unknown"
                        : `${credential.days_until_expiry} day(s) from now`}
                    </div>
                  </td>
                  <td className="px-4 py-4 align-top">
                    {credential.owners.length === 0 ? (
                      <span className="text-xs text-slate-400">No owners recorded</span>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {credential.owners.map((owner) => (
                          <span key={`${credential.application_id}-${credential.key_id}-${owner}`} className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-800">
                            {owner}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-4 align-top">
                    {credential.flags.length === 0 ? (
                      <span className="text-xs text-slate-400">No extra flags</span>
                    ) : (
                      <div className="space-y-2">
                        {credential.flags.map((flag) => (
                          <div key={`${credential.application_id}-${credential.key_id}-${flag}`} className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
                            {flag}
                          </div>
                        ))}
                      </div>
                    )}
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
