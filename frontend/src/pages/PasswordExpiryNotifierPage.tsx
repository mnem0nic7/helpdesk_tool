import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api, {
  type PasswordExpiryNotification,
  type PasswordExpiryRun,
  type PasswordExpiryStatus,
} from "../lib/api.ts";

type Tab = "runs" | "notifications";

const RUNS_PAGE_SIZE = 30;
const NOTIF_PAGE_SIZE = 50;

function ModeBadge({ testMode }: { testMode: number }) {
  return testMode === 0 ? (
    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700">
      LIVE
    </span>
  ) : (
    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
      TEST
    </span>
  );
}

function fmt(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.ceil(total / pageSize);
  if (pages <= 1) return null;
  return (
    <div className="mt-3 flex items-center gap-2 text-sm text-slate-500">
      <button
        disabled={page === 0}
        onClick={() => onPage(page - 1)}
        className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40"
      >
        ‹ Prev
      </button>
      <span>
        Page {page + 1} of {pages}
      </span>
      <button
        disabled={page >= pages - 1}
        onClick={() => onPage(page + 1)}
        className="rounded border border-slate-200 px-2 py-1 disabled:opacity-40"
      >
        Next ›
      </button>
    </div>
  );
}

function RunsTable({
  data,
  isLoading,
  error,
  page,
  onPage,
}: {
  data: { items: PasswordExpiryRun[]; total: number } | undefined;
  isLoading: boolean;
  error: Error | null;
  page: number;
  onPage: (p: number) => void;
}) {
  if (isLoading) {
    return <div className="py-12 text-center text-sm text-slate-400">Loading…</div>;
  }
  if (error) {
    return <p className="text-sm text-red-600">Failed to load runs: {String(error)}</p>;
  }
  const items = data?.items ?? [];
  return (
    <>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
            <th className="pb-2 pr-4">Date</th>
            <th className="pb-2 pr-4">Ran At (UTC)</th>
            <th className="pb-2 pr-4">Users Notified</th>
            <th className="pb-2">Mode</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={4} className="py-8 text-center text-sm text-slate-400">
                No runs recorded yet.
              </td>
            </tr>
          ) : (
            items.map((row) => (
              <tr key={row.run_date} className="border-b border-slate-100">
                <td className="py-2 pr-4 font-mono text-xs">{row.run_date}</td>
                <td className="py-2 pr-4 text-xs text-slate-500">{fmt(row.ran_at)}</td>
                <td className="py-2 pr-4 font-medium">{row.users_notified}</td>
                <td className="py-2">
                  <ModeBadge testMode={row.test_mode} />
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      <Pager page={page} pageSize={RUNS_PAGE_SIZE} total={data?.total ?? 0} onPage={onPage} />
    </>
  );
}

function NotificationsTable({
  data,
  isLoading,
  error,
  page,
  onPage,
}: {
  data: { items: PasswordExpiryNotification[]; total: number } | undefined;
  isLoading: boolean;
  error: Error | null;
  page: number;
  onPage: (p: number) => void;
}) {
  if (isLoading) {
    return <div className="py-12 text-center text-sm text-slate-400">Loading…</div>;
  }
  if (error) {
    return <p className="text-sm text-red-600">Failed to load notifications: {String(error)}</p>;
  }
  const items = data?.items ?? [];
  return (
    <>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
            <th className="pb-2 pr-4">User (SAM)</th>
            <th className="pb-2 pr-4">Email</th>
            <th className="pb-2 pr-4">Expiry Date</th>
            <th className="pb-2 pr-4">Days</th>
            <th className="pb-2 pr-4">Notified At</th>
            <th className="pb-2">Mode</th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td colSpan={6} className="py-8 text-center text-sm text-slate-400">
                No notifications recorded yet.
              </td>
            </tr>
          ) : (
            items.map((row) => (
              <tr key={row.id} className="border-b border-slate-100">
                <td className="py-2 pr-4 font-mono text-xs">{row.sam_account_name}</td>
                <td className="py-2 pr-4 text-xs text-slate-600">{row.email}</td>
                <td className="py-2 pr-4 font-mono text-xs">{row.expiry_date}</td>
                <td className="py-2 pr-4 font-medium">{row.days_until_expiry}</td>
                <td className="py-2 pr-4 text-xs text-slate-500">{fmt(row.notified_at)}</td>
                <td className="py-2">
                  <ModeBadge testMode={row.test_mode} />
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
      <Pager
        page={page}
        pageSize={NOTIF_PAGE_SIZE}
        total={data?.total ?? 0}
        onPage={onPage}
      />
    </>
  );
}

export default function PasswordExpiryNotifierPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("runs");
  const [runsPage, setRunsPage] = useState(0);
  const [notifPage, setNotifPage] = useState(0);

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => api.getMe(),
    staleTime: 5 * 60 * 1000,
  });
  const isAdmin = !!meQuery.data?.is_admin;

  const statusQuery = useQuery<PasswordExpiryStatus>({
    queryKey: ["password-expiry", "status"],
    queryFn: () => api.getPasswordExpiryStatus(),
  });

  const runsQuery = useQuery({
    queryKey: ["password-expiry", "runs", runsPage],
    queryFn: () => api.getPasswordExpiryRuns(RUNS_PAGE_SIZE, runsPage * RUNS_PAGE_SIZE),
    enabled: tab === "runs",
  });

  const notifQuery = useQuery({
    queryKey: ["password-expiry", "notifications", notifPage],
    queryFn: () =>
      api.getPasswordExpiryNotifications(NOTIF_PAGE_SIZE, notifPage * NOTIF_PAGE_SIZE),
    enabled: tab === "notifications",
  });

  const toggleMut = useMutation({
    mutationFn: (enabled: boolean) => api.patchPasswordExpirySettings(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["password-expiry", "status"] }),
  });

  const status = statusQuery.data;
  const enabled = status?.enabled ?? false;

  function handleRefresh() {
    qc.invalidateQueries({ queryKey: ["password-expiry"] });
  }

  return (
    <div className="p-6 max-w-5xl">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-800">Password Expiry Notifier</h1>
          <p className="text-sm text-slate-500">Daily notifications for expiring AD passwords</p>
        </div>
        <button
          onClick={handleRefresh}
          className="rounded border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>

      {statusQuery.error && (
        <p className="mb-4 text-sm text-red-600">
          Failed to load status: {String(statusQuery.error)}
        </p>
      )}

      {/* Status bar */}
      <div className="mb-6 flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-white px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-500">Live emails</span>
          <button
            role="switch"
            aria-checked={enabled}
            aria-label="Enable live emails"
            disabled={!isAdmin || toggleMut.isPending}
            title={!isAdmin ? "Admin access required" : undefined}
            onClick={() => toggleMut.mutate(!enabled)}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
              enabled ? "bg-emerald-500" : "bg-slate-300"
            }`}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                enabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
          <ModeBadge testMode={enabled ? 0 : 1} />
        </div>

        <div className="h-4 w-px bg-slate-200" />

        <div className="text-sm text-slate-600">
          {status ? (
            status.last_run ? (
              <>
                Last run: <strong>{status.last_run.run_date}</strong> ·{" "}
                <strong>{status.last_run.users_notified}</strong> notified
              </>
            ) : (
              "No runs yet"
            )
          ) : (
            "Loading…"
          )}
        </div>

        {status && (
          <>
            <div className="h-4 w-px bg-slate-200" />
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              Window: {status.config.days_before} days
            </span>
            <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
              Max age: {status.config.max_age_days} days
            </span>
          </>
        )}
      </div>

      {/* Tabs */}
      <div className="mb-4 flex gap-0 border-b border-slate-200">
        {(["runs", "notifications"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? "border-b-2 border-blue-600 text-blue-600"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t === "runs" ? "Run History" : "Notification Log"}
          </button>
        ))}
      </div>

      {tab === "runs" && (
        <RunsTable
          data={runsQuery.data}
          isLoading={runsQuery.isLoading}
          error={runsQuery.error as Error | null}
          page={runsPage}
          onPage={(p) => setRunsPage(p)}
        />
      )}
      {tab === "notifications" && (
        <NotificationsTable
          data={notifQuery.data}
          isLoading={notifQuery.isLoading}
          error={notifQuery.error as Error | null}
          page={notifPage}
          onPage={(p) => setNotifPage(p)}
        />
      )}
    </div>
  );
}
