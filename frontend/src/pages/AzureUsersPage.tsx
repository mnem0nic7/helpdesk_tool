import { useEffect, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type AzureDirectoryObject } from "../lib/api.ts";
import useInfiniteScrollCount from "../hooks/useInfiniteScrollCount.ts";
import { SortHeader, sortRows, useTableSort } from "../lib/tableSort.tsx";

type UserColKey = "display_name" | "principal_name" | "mail" | "department" | "job_title" | "created_datetime" | "on_prem_domain";

function getDirectoryLabel(user: AzureDirectoryObject): string {
  if (user.extra.on_prem_domain) return user.extra.on_prem_domain;
  if (user.extra.user_type === "Guest") return "External";
  return "Cloud";
}

const DEFAULT_DRAWER_WIDTH = 720;
const DRAWER_MIN_WIDTH = 520;
const DRAWER_VIEWPORT_MARGIN = 32;

function clampDrawerWidth(width: number): number {
  if (typeof window === "undefined") return DEFAULT_DRAWER_WIDTH;
  const maxWidth = Math.max(360, window.innerWidth - DRAWER_VIEWPORT_MARGIN);
  const minWidth = Math.min(DRAWER_MIN_WIDTH, maxWidth);
  return Math.min(Math.max(width, minWidth), maxWidth);
}

function getExpandedDrawerWidth(): number {
  if (typeof window === "undefined") return DEFAULT_DRAWER_WIDTH;
  return clampDrawerWidth(window.innerWidth - DRAWER_VIEWPORT_MARGIN);
}

function StatCard({ label, value, tone = "text-slate-900" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 text-3xl font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

function StatusChip({ enabled }: { enabled: boolean | null }) {
  if (enabled === true) {
    return <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-700">Enabled</span>;
  }
  if (enabled === false) {
    return <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">Disabled</span>;
  }
  return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500">Unknown</span>;
}

function TypeChip({ userType }: { userType: string }) {
  if (userType === "Guest") {
    return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700">Guest</span>;
  }
  return <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs font-semibold text-sky-700">Member</span>;
}

function DetailRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-0.5">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-sm text-slate-900 break-all">{value}</div>
    </div>
  );
}

function UserDetailDrawer({
  user,
  onClose,
}: {
  user: AzureDirectoryObject;
  onClose: () => void;
}) {
  const [drawerWidth, setDrawerWidth] = useState(() => clampDrawerWidth(DEFAULT_DRAWER_WIDTH));
  const [isResizing, setIsResizing] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleResize = () => {
      setDrawerWidth((current) => (isExpanded ? getExpandedDrawerWidth() : clampDrawerWidth(current)));
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [isExpanded]);

  useEffect(() => {
    if (!isResizing) return undefined;

    const previousUserSelect = document.body.style.userSelect;
    const previousCursor = document.body.style.cursor;
    const updateWidth = (clientX: number) => {
      setDrawerWidth(clampDrawerWidth(window.innerWidth - clientX));
    };

    const handlePointerMove = (event: PointerEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const handleMouseMove = (event: MouseEvent) => {
      event.preventDefault();
      updateWidth(event.clientX);
    };

    const stopResizing = () => setIsResizing(false);

    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("pointerup", stopResizing);
    window.addEventListener("mouseup", stopResizing);

    return () => {
      document.body.style.userSelect = previousUserSelect;
      document.body.style.cursor = previousCursor;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("pointerup", stopResizing);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [isResizing]);

  function handleResizeStart(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    setIsExpanded(false);
    setIsResizing(true);
  }

  function toggleExpanded() {
    setIsExpanded((current) => {
      const next = !current;
      setDrawerWidth(next ? getExpandedDrawerWidth() : clampDrawerWidth(DEFAULT_DRAWER_WIDTH));
      return next;
    });
  }

  const { extra } = user;
  const portalUrl = `https://portal.azure.com/#view/Microsoft_AAD_IAM/UserDetailsMenuBlade/~/Profile/userId/${user.id}`;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/35" onClick={onClose}>
      <aside
        className="relative flex h-full max-w-full flex-col overflow-hidden bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
        style={{ width: `${drawerWidth}px` }}
      >
        {/* Resize handle */}
        <div
          role="separator"
          aria-label="Resize user detail drawer"
          aria-orientation="vertical"
          className={[
            "absolute inset-y-0 left-0 z-10 w-3 -translate-x-1/2 cursor-col-resize touch-none",
            isResizing ? "bg-blue-200/70" : "bg-transparent hover:bg-slate-200/60",
          ].join(" ")}
          onPointerDown={handleResizeStart}
          onDoubleClick={() => {
            setIsExpanded(false);
            setDrawerWidth(clampDrawerWidth(DEFAULT_DRAWER_WIDTH));
          }}
        >
          <div className="absolute left-1/2 top-1/2 h-14 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-slate-300" />
        </div>

        {/* Header */}
        <div className="border-b border-slate-200 px-6 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="flex min-w-0 items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-sky-100 text-base font-bold text-sky-700">
                {initials(user.display_name) || "?"}
              </div>
              <div className="min-w-0">
                <h2 className="truncate text-xl font-bold text-slate-900">{user.display_name || "—"}</h2>
                <div className="mt-0.5 truncate text-sm text-slate-500">{user.principal_name}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  <StatusChip enabled={user.enabled} />
                  <TypeChip userType={extra.user_type || "Member"} />
                </div>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <a
                href={portalUrl}
                target="_blank"
                rel="noreferrer"
                onClick={(event) => event.stopPropagation()}
                className="rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700 transition hover:bg-sky-100"
              >
                Azure Portal
              </a>
              <button
                type="button"
                onClick={toggleExpanded}
                className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50"
              >
                {isExpanded ? "Restore" : "Expand"}
              </button>
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

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* Contact */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Contact</h3>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
              <DetailRow label="Email" value={user.mail} />
              <DetailRow label="Mobile Phone" value={extra.mobile_phone} />
              <DetailRow label="Business Phones" value={extra.business_phones} />
              <DetailRow label="City" value={extra.city} />
              <DetailRow label="Country" value={extra.country} />
            </div>
          </section>

          {/* Organization */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Organization</h3>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
              <DetailRow label="Job Title" value={extra.job_title} />
              <DetailRow label="Department" value={extra.department} />
              <DetailRow label="Company" value={extra.company_name} />
              <DetailRow label="Office Location" value={extra.office_location} />
            </div>
          </section>

          {/* Account */}
          <section className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Account</h3>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-3">
              <DetailRow label="User Type" value={extra.user_type} />
              <DetailRow label="Source Directory" value={getDirectoryLabel(user)} />
              {extra.on_prem_domain ? <DetailRow label="On-Prem Domain" value={extra.on_prem_domain} /> : null}
              {extra.on_prem_netbios ? <DetailRow label="NetBIOS Name" value={extra.on_prem_netbios} /> : null}
              <DetailRow label="Created" value={formatDate(extra.created_datetime)} />
              <DetailRow label="Last Password Change" value={formatDate(extra.last_password_change)} />
              <DetailRow label="Proxy Addresses" value={extra.proxy_addresses} />
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}

type StatusFilter = "all" | "enabled" | "disabled";
type TypeFilter = "all" | "member" | "guest";

export default function AzureUsersPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [directoryFilter, setDirectoryFilter] = useState("");
  const { sortKey, sortDir, toggleSort } = useTableSort<UserColKey>("display_name");
  const [selectedUser, setSelectedUser] = useState<AzureDirectoryObject | null>(null);

  const { data: users = [], isLoading, isError, error } = useQuery({
    queryKey: ["azure", "users", { search }],
    queryFn: () => api.getAzureUsers(search),
    refetchInterval: 60_000,
  });

  const totalCount = users.length;
  const enabledCount = users.filter((u) => u.enabled === true).length;
  const disabledCount = users.filter((u) => u.enabled === false).length;
  const memberCount = users.filter((u) => u.extra.user_type !== "Guest").length;
  const guestCount = users.filter((u) => u.extra.user_type === "Guest").length;
  const onPremCount = users.filter((u) => u.extra.on_prem_sync === "true").length;

  const directoryOptions = Array.from(new Set(users.map(getDirectoryLabel))).sort();

  const filtered = sortRows(
    users.filter((u) => {
      if (statusFilter === "enabled" && u.enabled !== true) return false;
      if (statusFilter === "disabled" && u.enabled !== false) return false;
      if (typeFilter === "member" && u.extra.user_type === "Guest") return false;
      if (typeFilter === "guest" && u.extra.user_type !== "Guest") return false;
      if (directoryFilter && getDirectoryLabel(u) !== directoryFilter) return false;
      return true;
    }),
    sortKey,
    sortDir,
    (u, key) => {
      if (key === "department") return u.extra.department;
      if (key === "job_title") return u.extra.job_title;
      if (key === "created_datetime") return u.extra.created_datetime;
      if (key === "on_prem_domain") return getDirectoryLabel(u);
      return (u as unknown as Record<string, unknown>)[key] as string;
    },
  );
  const filterKey = [search, statusFilter, typeFilter, directoryFilter, sortKey, sortDir].join("|");
  const scroll = useInfiniteScrollCount(filtered.length, 50, filterKey);
  const visibleUsers = filtered.slice(0, scroll.visibleCount);

  if (isLoading) {
    return <div className="text-sm text-slate-500">Loading Azure AD users...</div>;
  }

  if (isError || !users) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load users: {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }

  function pillClass(active: boolean) {
    return [
      "rounded-full border px-4 py-1.5 text-sm font-medium transition",
      active
        ? "border-sky-500 bg-sky-50 text-sky-700"
        : "border-slate-300 bg-white text-slate-600 hover:border-slate-400 hover:bg-slate-50",
    ].join(" ");
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Users</h1>
        <p className="mt-1 text-sm text-slate-500">
          Azure AD user directory — status, department, job title, and account details.
        </p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Total" value={totalCount.toLocaleString()} />
        <StatCard label="Enabled" value={enabledCount.toLocaleString()} tone="text-emerald-700" />
        <StatCard label="Disabled" value={disabledCount.toLocaleString()} tone="text-red-700" />
        <StatCard label="Members" value={memberCount.toLocaleString()} tone="text-sky-700" />
        <StatCard label="Guests" value={guestCount.toLocaleString()} tone="text-amber-700" />
        <StatCard label="On-Prem Synced" value={onPremCount.toLocaleString()} tone="text-violet-700" />
      </div>

      {/* Filters */}
      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm space-y-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search name, email, department..."
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-sky-500"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-400 self-center">Status</span>
          {(["all", "enabled", "disabled"] as StatusFilter[]).map((value) => (
            <button key={value} type="button" onClick={() => setStatusFilter(value)} className={pillClass(statusFilter === value)}>
              {value === "all" ? "All" : value === "enabled" ? "Enabled" : "Disabled"}
            </button>
          ))}
          <span className="mx-2 self-center text-slate-300">|</span>
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-400 self-center">Type</span>
          {(["all", "member", "guest"] as TypeFilter[]).map((value) => (
            <button key={value} type="button" onClick={() => setTypeFilter(value)} className={pillClass(typeFilter === value)}>
              {value === "all" ? "All" : value === "member" ? "Members" : "Guests"}
            </button>
          ))}
          {directoryOptions.length > 1 ? (
            <>
              <span className="mx-2 self-center text-slate-300">|</span>
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-400 self-center">Directory</span>
              <select
                value={directoryFilter}
                onChange={(e) => setDirectoryFilter(e.target.value)}
                className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 hover:border-slate-400"
              >
                <option value="">All</option>
                {directoryOptions.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </>
          ) : null}
        </div>
      </div>

      {/* Table */}
      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3 text-sm text-slate-500">
          Showing <span className="font-semibold text-slate-900">{visibleUsers.length.toLocaleString()}</span> of{" "}
          {filtered.length.toLocaleString()} filtered
          <span className="text-slate-400"> | </span>
          {totalCount.toLocaleString()} total users
        </div>
        <div className="max-h-[70vh] overflow-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <SortHeader col="display_name" label="Name" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="principal_name" label="UPN" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="mail" label="Email" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="department" label="Department" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="job_title" label="Job Title" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <SortHeader col="on_prem_domain" label="Directory" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Type</th>
                <SortHeader col="created_datetime" label="Created" sortKey={sortKey} sortDir={sortDir} onSort={toggleSort} />
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-sm text-slate-500">
                    No users matched the current filters.
                  </td>
                </tr>
              ) : null}
              {visibleUsers.map((user, index) => (
                <tr
                  key={user.id}
                  onClick={() => setSelectedUser(user)}
                  className={[
                    "cursor-pointer transition hover:bg-sky-50/60",
                    selectedUser?.id === user.id ? "bg-sky-50" : index % 2 === 0 ? "bg-white" : "bg-slate-50/50",
                  ].join(" ")}
                >
                  <td className="px-4 py-3 font-medium text-slate-900">{user.display_name}</td>
                  <td className="px-4 py-3 text-xs text-slate-500 max-w-[180px] truncate">{user.principal_name}</td>
                  <td className="px-4 py-3 text-slate-700">{user.mail || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{user.extra.department || "—"}</td>
                  <td className="px-4 py-3 text-slate-700">{user.extra.job_title || "—"}</td>
                  <td className="px-4 py-3 text-xs text-slate-600 font-mono">{getDirectoryLabel(user)}</td>
                  <td className="px-4 py-3"><StatusChip enabled={user.enabled} /></td>
                  <td className="px-4 py-3"><TypeChip userType={user.extra.user_type || "Member"} /></td>
                  <td className="px-4 py-3 text-slate-700 whitespace-nowrap">{formatDate(user.extra.created_datetime)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {scroll.hasMore ? (
            <div ref={scroll.sentinelRef} className="border-t border-slate-200 px-4 py-3 text-center text-xs text-slate-400">
              Showing {visibleUsers.length.toLocaleString()} of {filtered.length.toLocaleString()} users — scroll for more
            </div>
          ) : null}
        </div>
      </section>

      {selectedUser ? (
        <UserDetailDrawer user={selectedUser} onClose={() => setSelectedUser(null)} />
      ) : null}
    </div>
  );
}
