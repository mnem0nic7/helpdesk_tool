import { useDeferredValue, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero, AzureSecurityMetricCard, azureSecurityToneClasses } from "../components/AzureSecurityLane.tsx";
import { api, type SecurityBreakGlassValidationAccount } from "../lib/api.ts";
import { formatDateTime } from "../lib/azureSecurityUsers.ts";

type StatusFilter = "all" | "critical" | "warning" | "healthy";
type AccessFilter = "all" | "privileged" | "watchlist" | "cloud-only" | "on-prem";

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function matchesSearch(parts: Array<string | string[]>, search: string): boolean {
  if (!search) return true;
  const normalizedSearch = search.toLowerCase();
  return parts
    .flatMap((part) => (Array.isArray(part) ? part : [part]))
    .some((part) => String(part || "").toLowerCase().includes(normalizedSearch));
}

function accountStatusTone(status: SecurityBreakGlassValidationAccount["status"]): "rose" | "amber" | "emerald" {
  if (status === "critical") return "rose";
  if (status === "warning") return "amber";
  return "emerald";
}

function accountStatusLabel(status: SecurityBreakGlassValidationAccount["status"]): string {
  if (status === "critical") return "Action needed";
  if (status === "warning") return "Review soon";
  return "Healthy";
}

function directorySourceLabel(account: SecurityBreakGlassValidationAccount): string {
  if (account.on_prem_sync) return "On-prem synced";
  if (account.user_type === "Guest" || account.account_class === "guest_external") return "External guest";
  if (account.account_class === "shared_or_service") return "Shared / service";
  return "Cloud managed";
}

function passwordAgeLabel(account: SecurityBreakGlassValidationAccount): string {
  if (account.user_type === "Guest" || account.account_class === "guest_external") return "Home tenant credential";
  if (account.on_prem_sync) return "Managed in AD";
  if (account.days_since_password_change === null) return "No timestamp recorded";
  return `${account.days_since_password_change.toLocaleString()} days`;
}

function lastSuccessfulLabel(account: SecurityBreakGlassValidationAccount): string {
  if (!account.last_successful_utc) return "No sign-in recorded";
  return formatDateTime(account.last_successful_utc);
}

function buildUserRoute(userId: string): string {
  return `/users?userId=${encodeURIComponent(userId)}`;
}

function AccountCard({ account }: { account: SecurityBreakGlassValidationAccount }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-lg font-semibold text-slate-900">{account.display_name}</h3>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(accountStatusTone(account.status))}`}>
              {accountStatusLabel(account.status)}
            </span>
            <span className={`rounded-full px-3 py-1 text-xs font-semibold ${account.has_privileged_access ? "bg-rose-50 text-rose-700" : "bg-slate-100 text-slate-600"}`}>
              {account.has_privileged_access ? "Privileged candidate" : "Watchlist candidate"}
            </span>
          </div>
          <div className="mt-1 text-sm text-slate-500">{account.principal_name || account.user_id}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {account.has_privileged_access ? (
            <Link
              to="/security/access-review"
              className="inline-flex items-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Open access review
            </Link>
          ) : null}
          <Link
            to={buildUserRoute(account.user_id)}
            className="inline-flex items-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            Open source record
          </Link>
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Last successful sign-in</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{lastSuccessfulLabel(account)}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Password age</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{passwordAgeLabel(account)}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Licenses</div>
          <div className="mt-1 text-sm font-medium text-slate-900">
            {account.is_licensed ? `${account.license_count.toLocaleString()} assigned` : account.is_licensed === false ? "None assigned" : "Unknown"}
          </div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Directory source</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{directorySourceLabel(account)}</div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {account.matched_terms.map((term) => (
          <span key={`${account.user_id}-${term}`} className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-800">
            {term}
          </span>
        ))}
      </div>

      <div className="mt-4 space-y-2">
        {account.flags.length > 0 ? (
          account.flags.map((flag) => (
            <div
              key={`${account.user_id}-${flag}`}
              className={`rounded-xl px-4 py-3 text-sm ${
                account.status === "critical"
                  ? "bg-rose-50 text-rose-800"
                  : account.status === "warning"
                    ? "bg-amber-50 text-amber-800"
                    : "bg-emerald-50 text-emerald-800"
              }`}
            >
              {flag}
            </div>
          ))
        ) : (
          <div className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            Current cached signals look healthy for this candidate account.
          </div>
        )}
      </div>
    </section>
  );
}

export default function AzureSecurityBreakGlassValidationPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [accessFilter, setAccessFilter] = useState<AccessFilter>("all");
  const deferredSearch = useDeferredValue(search);

  const query = useQuery({
    queryKey: ["azure", "security", "break-glass-validation"],
    queryFn: () => api.getAzureSecurityBreakGlassValidation(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const filteredAccounts = useMemo(() => {
    const rows = query.data?.accounts ?? [];
    return rows.filter((account) => {
      if (statusFilter !== "all" && account.status !== statusFilter) {
        return false;
      }
      if (accessFilter === "privileged" && !account.has_privileged_access) return false;
      if (accessFilter === "watchlist" && account.has_privileged_access) return false;
      if (accessFilter === "cloud-only" && (account.on_prem_sync || account.user_type === "Guest" || account.account_class === "guest_external")) return false;
      if (accessFilter === "on-prem" && !account.on_prem_sync) return false;
      return matchesSearch(
        [account.display_name, account.principal_name, account.account_class, account.matched_terms, account.flags],
        deferredSearch,
      );
    });
  }, [accessFilter, deferredSearch, query.data?.accounts, statusFilter]);

  if (query.isLoading) {
    return <AzurePageSkeleton titleWidth="w-72" subtitleWidth="w-[44rem]" statCount={6} sectionCount={4} />;
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load break-glass account validation: {query.error instanceof Error ? query.error.message : "Unknown error"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <AzureSecurityLaneHero
        title="Break-glass Account Validation"
        accent="violet"
        description="Validate likely emergency accounts against recent sign-in evidence, sync source, password age, licensing, and Azure RBAC exposure. This lane keeps the validation queue separate from broader privileged-access review so emergency-account hygiene has a home of its own."
        refreshLabel="Refresh windows"
        refreshValue={`RBAC inventory: ${formatTimestamp(query.data.inventory_last_refresh)} • Directory: ${formatTimestamp(query.data.directory_last_refresh)}`}
        actions={[
          { label: "Back to Security workspace", to: "/security", tone: "secondary" },
          { label: "Open Access Review", to: "/security/access-review" },
          { label: "Open Security Copilot", to: "/security/copilot", tone: "secondary" },
        ]}
      />

      <section className="grid gap-4 xl:grid-cols-3 md:grid-cols-2">
        {query.data.metrics.map((metric) => (
          <AzureSecurityMetricCard key={metric.key} label={metric.label} value={metric.value} detail={metric.detail} tone={metric.tone} />
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
            <h2 className="text-lg font-semibold text-slate-900">Validation queue</h2>
            <div className="mt-1 text-sm text-slate-500">Filter likely emergency accounts by risk state, privileged exposure, and naming markers.</div>
          </div>
          <div className="text-sm text-slate-500">{filteredAccounts.length.toLocaleString()} candidate account(s)</div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search names, UPNs, matched terms, or flags..."
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
          />
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
          >
            <option value="all">All risk states</option>
            <option value="critical">Action needed</option>
            <option value="warning">Review soon</option>
            <option value="healthy">Healthy only</option>
          </select>
          <select
            value={accessFilter}
            onChange={(event) => setAccessFilter(event.target.value as AccessFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
          >
            <option value="all">All candidates</option>
            <option value="privileged">Privileged only</option>
            <option value="watchlist">Watchlist only</option>
            <option value="cloud-only">Cloud-only</option>
            <option value="on-prem">On-prem synced</option>
          </select>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        {filteredAccounts.length > 0 ? (
          filteredAccounts.map((account) => <AccountCard key={account.user_id} account={account} />)
        ) : (
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-6 text-sm text-slate-500 shadow-sm">
            No break-glass candidates matched the current filters.
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Scope notes</h2>
        <div className="mt-4 space-y-2">
          {query.data.scope_notes.map((note) => (
            <div key={note} className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
              {note}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
