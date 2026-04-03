import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero, AzureSecurityMetricCard, azureSecurityToneClasses } from "../components/AzureSecurityLane.tsx";
import {
  api,
  type SecurityDeviceActionJob,
  type SecurityDeviceActionRequest,
  type SecurityDeviceActionType,
  type SecurityDeviceComplianceDevice,
} from "../lib/api.ts";
import { formatDateTime } from "../lib/azureSecurityUsers.ts";

type RiskFilter = "all" | "critical" | "high" | "medium" | "low";
type ReadinessFilter = "all" | "ready" | "blocked";

const ACTION_LABELS: Record<SecurityDeviceActionType, string> = {
  device_sync: "Device sync",
  device_remote_lock: "Remote lock",
  device_retire: "Retire",
  device_wipe: "Wipe",
};

const DESTRUCTIVE_ACTIONS = new Set<SecurityDeviceActionType>(["device_retire", "device_wipe"]);

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "No refresh recorded";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function titleCase(value: string): string {
  if (!value) return "Unknown";
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

function matchesSearch(device: SecurityDeviceComplianceDevice, search: string): boolean {
  if (!search) return true;
  const normalized = search.toLowerCase();
  return [
    device.device_name,
    device.operating_system,
    device.compliance_state,
    device.management_state,
    device.owner_type,
    ...device.finding_tags,
    ...device.recommended_actions,
    ...device.primary_users.map((user) => `${user.display_name} ${user.principal_name}`),
  ]
    .join(" ")
    .toLowerCase()
    .includes(normalized);
}

function riskTone(risk: SecurityDeviceComplianceDevice["risk_level"]): "rose" | "amber" | "violet" | "emerald" {
  if (risk === "critical" || risk === "high") return "rose";
  if (risk === "medium") return "amber";
  if (risk === "low") return "emerald";
  return "violet";
}

function readinessText(device: SecurityDeviceComplianceDevice): string {
  if (device.action_ready) return "Action ready";
  if (device.action_blockers.length > 0) return device.action_blockers[0];
  return "Review only";
}

function buildRawUserRoute(userId: string): string {
  return `/users?userId=${encodeURIComponent(userId)}`;
}

function buildUserReviewRoute(user: { display_name: string; principal_name: string }): string {
  const search = user.display_name || user.principal_name;
  return `/security/user-review${search ? `?search=${encodeURIComponent(search)}` : ""}`;
}

function DeviceCard({
  device,
  selected,
  onToggle,
}: {
  device: SecurityDeviceComplianceDevice;
  selected: boolean;
  onToggle: (deviceId: string, selected: boolean) => void;
}) {
  const primaryUser = device.primary_users[0];
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <label className="flex min-w-0 items-start gap-3">
          <input
            type="checkbox"
            checked={selected}
            onChange={(event) => onToggle(device.id, event.target.checked)}
            disabled={!device.action_ready}
            aria-label={`Select ${device.device_name}`}
            className="mt-1 h-4 w-4 rounded border-slate-300 text-sky-700 focus:ring-sky-200"
          />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-semibold text-slate-900">{device.device_name}</h3>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(riskTone(device.risk_level))}`}>
                {titleCase(device.risk_level)}
              </span>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${device.action_ready ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                {readinessText(device)}
              </span>
            </div>
            <div className="mt-1 text-sm text-slate-500">
              {device.operating_system || "Unknown OS"}
              {device.operating_system_version ? ` • ${device.operating_system_version}` : ""}
              {device.azure_ad_device_id ? ` • Azure AD ${device.azure_ad_device_id}` : ""}
            </div>
          </div>
        </label>
        <div className="flex flex-wrap gap-2">
          {primaryUser ? (
            <>
              <Link
                to={buildUserReviewRoute(primaryUser)}
                className="inline-flex items-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                Open user review
              </Link>
              <Link
                to={buildRawUserRoute(primaryUser.id)}
                className="inline-flex items-center rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                Open source record
              </Link>
            </>
          ) : null}
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Compliance</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{titleCase(device.compliance_state)}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Management</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{titleCase(device.management_state)}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Owner type</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{titleCase(device.owner_type)}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Enrollment</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{titleCase(device.enrollment_type)}</div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Last sync</div>
          <div className="mt-1 text-sm font-medium text-slate-900">
            {device.last_sync_date_time ? formatDateTime(device.last_sync_date_time) : "No sync recorded"}
          </div>
        </div>
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Primary user</div>
          <div className="mt-1 text-sm font-medium text-slate-900">
            {primaryUser ? primaryUser.display_name || primaryUser.principal_name : "Unassigned"}
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {device.finding_tags.map((tag) => (
          <span key={`${device.id}-${tag}`} className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-800">
            {titleCase(tag)}
          </span>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <h4 className="text-sm font-semibold text-slate-900">Recommended actions</h4>
          <div className="mt-2 space-y-2">
            {device.recommended_actions.map((action) => (
              <div key={`${device.id}-${action}`} className="rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
                {action}
              </div>
            ))}
          </div>
        </div>
        <div>
          <h4 className="text-sm font-semibold text-slate-900">Action readiness</h4>
          <div className="mt-2 space-y-2">
            {device.action_ready ? (
              <div className="rounded-xl bg-white px-4 py-3 text-sm text-slate-700 ring-1 ring-slate-200">
                Supported actions: {device.supported_actions.map((action) => ACTION_LABELS[action]).join(", ")}
              </div>
            ) : (
              device.action_blockers.map((blocker) => (
                <div key={`${device.id}-${blocker}`} className="rounded-xl bg-slate-100 px-4 py-3 text-sm text-slate-700">
                  {blocker}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

export default function AzureSecurityDeviceCompliancePage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("all");
  const [complianceFilter, setComplianceFilter] = useState("all");
  const [osFilter, setOsFilter] = useState("all");
  const [ownerFilter, setOwnerFilter] = useState("all");
  const [readinessFilter, setReadinessFilter] = useState<ReadinessFilter>("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [actionType, setActionType] = useState<SecurityDeviceActionType>("device_sync");
  const [reason, setReason] = useState("");
  const [destructiveConfirmed, setDestructiveConfirmed] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string>("");
  const deferredSearch = useDeferredValue(search);

  const query = useQuery({
    queryKey: ["azure", "security", "device-compliance"],
    queryFn: () => api.getAzureSecurityDeviceCompliance(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const devices = useMemo(() => query.data?.devices ?? [], [query.data?.devices]);
  const filteredDevices = useMemo(() => {
    return devices.filter((device) => {
      if (riskFilter !== "all" && device.risk_level !== riskFilter) return false;
      if (complianceFilter !== "all" && (device.compliance_state || "unknown") !== complianceFilter) return false;
      if (osFilter !== "all" && (device.operating_system || "unknown") !== osFilter) return false;
      if (ownerFilter !== "all" && (device.owner_type || "unknown") !== ownerFilter) return false;
      if (readinessFilter === "ready" && !device.action_ready) return false;
      if (readinessFilter === "blocked" && device.action_ready) return false;
      return matchesSearch(device, deferredSearch);
    });
  }, [devices, riskFilter, complianceFilter, osFilter, ownerFilter, readinessFilter, deferredSearch]);

  const selectedDevices = useMemo(
    () => devices.filter((device) => selectedIds.includes(device.id)),
    [devices, selectedIds],
  );
  const destructiveAction = DESTRUCTIVE_ACTIONS.has(actionType);
  const selectedNames = useMemo(
    () => [...selectedDevices.map((device) => device.device_name).filter(Boolean)].sort((a, b) => a.localeCompare(b)),
    [selectedDevices],
  );

  const jobMutation = useMutation({
    mutationFn: (body: SecurityDeviceActionRequest) => api.createAzureSecurityDeviceAction(body),
    onSuccess: (job) => {
      setActiveJobId(job.job_id);
      setSelectedIds([]);
      setDestructiveConfirmed(false);
      void queryClient.invalidateQueries({ queryKey: ["azure", "security", "device-compliance"] });
    },
  });

  const activeJobQuery = useQuery({
    queryKey: ["azure", "security", "device-compliance", "job", activeJobId],
    queryFn: () => api.getAzureSecurityDeviceActionJob(activeJobId),
    enabled: Boolean(activeJobId),
    refetchInterval: (current) => {
      const job = current.state.data as SecurityDeviceActionJob | undefined;
      if (!job) return 2_000;
      return job.status === "completed" || job.status === "failed" ? false : 2_000;
    },
  });

  const resultsQuery = useQuery({
    queryKey: ["azure", "security", "device-compliance", "job-results", activeJobId],
    queryFn: () => api.getAzureSecurityDeviceActionJobResults(activeJobId),
    enabled: Boolean(activeJobId) && Boolean(activeJobQuery.data?.results_ready),
  });

  useEffect(() => {
    if (activeJobQuery.data?.results_ready) {
      void queryClient.invalidateQueries({ queryKey: ["azure", "security", "device-compliance"] });
    }
  }, [activeJobQuery.data?.results_ready, queryClient]);

  const distinctComplianceStates = useMemo(
    () => [...new Set(devices.map((device) => device.compliance_state || "unknown"))].sort((a, b) => a.localeCompare(b)),
    [devices],
  );
  const distinctOperatingSystems = useMemo(
    () => [...new Set(devices.map((device) => device.operating_system || "unknown"))].sort((a, b) => a.localeCompare(b)),
    [devices],
  );
  const distinctOwnerTypes = useMemo(
    () => [...new Set(devices.map((device) => device.owner_type || "unknown"))].sort((a, b) => a.localeCompare(b)),
    [devices],
  );

  function toggleSelection(deviceId: string, nextSelected: boolean) {
    setSelectedIds((current) => {
      if (nextSelected) {
        if (current.includes(deviceId)) return current;
        return [...current, deviceId];
      }
      return current.filter((item) => item !== deviceId);
    });
  }

  function selectFilteredReady() {
    setSelectedIds(filteredDevices.filter((device) => device.action_ready).map((device) => device.id));
  }

  function clearSelection() {
    setSelectedIds([]);
    setDestructiveConfirmed(false);
  }

  function submitAction() {
    if (!selectedDevices.length) return;
    jobMutation.mutate({
      action_type: actionType,
      device_ids: selectedDevices.map((device) => device.id),
      reason,
      confirm_device_count: destructiveAction && destructiveConfirmed ? selectedDevices.length : undefined,
      confirm_device_names: destructiveAction && destructiveConfirmed ? selectedNames : undefined,
    });
  }

  if (query.isLoading) {
    return <AzurePageSkeleton titleWidth="w-80" subtitleWidth="w-[46rem]" statCount={7} sectionCount={4} />;
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Failed to load device compliance review: {query.error instanceof Error ? query.error.message : "Unknown error"}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <AzureSecurityLaneHero
        title="Device Compliance Review"
        accent="emerald"
        description="Review tenant-wide Intune managed-device posture, stale sync, missing primary users, personal-device risk, and remediation readiness from one security lane. Bulk actions are queued on the Azure host so compliance work does not depend on the primary-host user drawer."
        refreshLabel="Device compliance refresh"
        refreshValue={formatTimestamp(query.data.device_last_refresh)}
        actions={[
          { label: "Back to Security workspace", to: "/security", tone: "secondary" },
          { label: "Open User Review", to: "/security/user-review" },
          { label: "Open Security Copilot", to: "/security/copilot", tone: "secondary" },
        ]}
      />

      <section className="grid gap-4 xl:grid-cols-4 md:grid-cols-2">
        {query.data.metrics.map((metric) => (
          <AzureSecurityMetricCard key={metric.key} label={metric.label} value={metric.value} detail={metric.detail} tone={metric.tone} />
        ))}
      </section>

      {!query.data.access_available ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
          <h2 className="text-lg font-semibold text-amber-900">Access required</h2>
          <div className="mt-2 text-sm text-amber-900">{query.data.access_message}</div>
        </section>
      ) : null}

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

      {query.data.access_available ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Bulk remediation</h2>
              <div className="mt-1 text-sm text-slate-500">
                Queue safe device actions against the selected devices. Retire and wipe require an explicit confirmation of the selected count and names.
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={selectFilteredReady}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                Select filtered ready
              </button>
              <button
                type="button"
                onClick={clearSelection}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                Clear selection
              </button>
            </div>
          </div>

          <div className="mt-4 grid gap-3 xl:grid-cols-[220px_1fr_220px]">
            <select
              value={actionType}
              onChange={(event) => {
                setActionType(event.target.value as SecurityDeviceActionType);
                setDestructiveConfirmed(false);
              }}
              className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
            >
              <option value="device_sync">Device sync</option>
              <option value="device_remote_lock">Remote lock</option>
              <option value="device_retire">Retire</option>
              <option value="device_wipe">Wipe</option>
            </select>
            <input
              type="text"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Reason for this action (optional but recommended)..."
              className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
            />
            <button
              type="button"
              onClick={submitAction}
              disabled={selectedDevices.length === 0 || jobMutation.isPending || (destructiveAction && !destructiveConfirmed)}
              className="rounded-xl bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {jobMutation.isPending ? "Queueing..." : `Run ${ACTION_LABELS[actionType]}`}
            </button>
          </div>

          <div className="mt-3 text-sm text-slate-500">{selectedDevices.length.toLocaleString()} device(s) selected</div>

          {destructiveAction && selectedDevices.length > 0 ? (
            <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 p-4">
              <div className="text-sm font-semibold text-rose-900">
                Confirm {ACTION_LABELS[actionType].toLowerCase()} for {selectedDevices.length.toLocaleString()} device(s)
              </div>
              <div className="mt-2 text-sm text-rose-900">{selectedNames.join(", ")}</div>
              <label className="mt-3 flex items-start gap-3 text-sm text-rose-900">
                <input
                  type="checkbox"
                  checked={destructiveConfirmed}
                  onChange={(event) => setDestructiveConfirmed(event.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-rose-300 text-rose-700 focus:ring-rose-200"
                />
                <span>I confirm the selected device count and names for this destructive action.</span>
              </label>
            </div>
          ) : null}

          {jobMutation.isError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {jobMutation.error instanceof Error ? jobMutation.error.message : "Failed to queue device action."}
            </div>
          ) : null}
        </section>
      ) : null}

      {activeJobQuery.data ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Active device action job</h2>
              <div className="mt-1 text-sm text-slate-500">
                {ACTION_LABELS[activeJobQuery.data.action_type]} • {activeJobQuery.data.progress_current.toLocaleString()} of {activeJobQuery.data.progress_total.toLocaleString()} processed
              </div>
            </div>
            <span
              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                activeJobQuery.data.status === "failed"
                  ? "bg-rose-50 text-rose-700"
                  : activeJobQuery.data.status === "completed"
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-amber-50 text-amber-700"
              }`}
            >
              {titleCase(activeJobQuery.data.status)}
            </span>
          </div>
          <div className="mt-3 text-sm text-slate-700">{activeJobQuery.data.progress_message}</div>
          {activeJobQuery.data.error ? (
            <div className="mt-3 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-800">{activeJobQuery.data.error}</div>
          ) : null}
          {resultsQuery.data && resultsQuery.data.length > 0 ? (
            <div className="mt-4 space-y-2">
              {resultsQuery.data.map((result) => (
                <div
                  key={`${result.device_id}-${result.summary}`}
                  className={`rounded-xl px-4 py-3 text-sm ${result.success ? "bg-emerald-50 text-emerald-900" : "bg-rose-50 text-rose-900"}`}
                >
                  <div className="font-semibold">{result.device_name || result.device_id}</div>
                  <div className="mt-1">{result.success ? result.summary : result.error || result.summary}</div>
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Review queue</h2>
            <div className="mt-1 text-sm text-slate-500">
              Filter by compliance state, risk, operating system, owner type, and remediation readiness.
            </div>
          </div>
          <div className="text-sm text-slate-500">{filteredDevices.length.toLocaleString()} device(s)</div>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1.2fr)_180px_180px_180px_180px]">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search devices, users, tags, or recommendations..."
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          />
          <select
            value={riskFilter}
            onChange={(event) => setRiskFilter(event.target.value as RiskFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          >
            <option value="all">All risks</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <select
            value={complianceFilter}
            onChange={(event) => setComplianceFilter(event.target.value)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          >
            <option value="all">All compliance</option>
            {distinctComplianceStates.map((state) => (
              <option key={state} value={state}>
                {titleCase(state)}
              </option>
            ))}
          </select>
          <select
            value={osFilter}
            onChange={(event) => setOsFilter(event.target.value)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          >
            <option value="all">All OS</option>
            {distinctOperatingSystems.map((value) => (
              <option key={value} value={value}>
                {titleCase(value)}
              </option>
            ))}
          </select>
          <select
            value={ownerFilter}
            onChange={(event) => setOwnerFilter(event.target.value)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          >
            <option value="all">All owners</option>
            {distinctOwnerTypes.map((value) => (
              <option key={value} value={value}>
                {titleCase(value)}
              </option>
            ))}
          </select>
        </div>

        <div className="mt-3 grid gap-3 lg:max-w-[360px]">
          <select
            value={readinessFilter}
            onChange={(event) => setReadinessFilter(event.target.value as ReadinessFilter)}
            className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
          >
            <option value="all">All readiness states</option>
            <option value="ready">Action ready</option>
            <option value="blocked">Blocked / review only</option>
          </select>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        {filteredDevices.length > 0 ? (
          filteredDevices.map((device) => (
            <DeviceCard
              key={device.id}
              device={device}
              selected={selectedIds.includes(device.id)}
              onToggle={toggleSelection}
            />
          ))
        ) : (
          <div className="rounded-2xl border border-slate-200 bg-white px-5 py-6 text-sm text-slate-500 shadow-sm">
            No managed devices matched the current filters.
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
