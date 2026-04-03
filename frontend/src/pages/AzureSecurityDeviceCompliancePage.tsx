import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import AzurePageSkeleton from "../components/AzurePageSkeleton.tsx";
import { AzureSecurityLaneHero, AzureSecurityMetricCard, azureSecurityToneClasses } from "../components/AzureSecurityLane.tsx";
import {
  api,
  type AzureDirectoryObject,
  type SecurityDeviceActionBatchStatus,
  type SecurityDeviceActionRequest,
  type SecurityDeviceActionType,
  type SecurityDeviceComplianceDevice,
  type SecurityDeviceFixPlanDevice,
  type SecurityDeviceFixPlanExecuteRequest,
  type SecurityDeviceFixPlanResponse,
} from "../lib/api.ts";
import { formatDateTime } from "../lib/azureSecurityUsers.ts";

type RiskFilter = "all" | "critical" | "high" | "medium" | "low";
type ReadinessFilter = "all" | "ready" | "blocked";

const ACTION_LABELS: Record<SecurityDeviceActionType, string> = {
  device_sync: "Device sync",
  device_remote_lock: "Remote lock",
  device_retire: "Retire",
  device_wipe: "Wipe",
  device_reassign_primary_user: "Assign primary user",
};

const DIRECT_ACTION_ORDER: SecurityDeviceActionType[] = [
  "device_sync",
  "device_remote_lock",
  "device_retire",
  "device_wipe",
  "device_reassign_primary_user",
];

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
    device.recommended_fix_label,
    device.recommended_fix_reason,
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

function directActionReason(actionType: SecurityDeviceActionType, device: SecurityDeviceComplianceDevice): string {
  if (device.recommended_fix_action === actionType && device.recommended_fix_reason) {
    return device.recommended_fix_reason;
  }
  if (actionType === "device_reassign_primary_user") {
    return "Assign a primary user from the Device Compliance Review lane.";
  }
  return `Run ${ACTION_LABELS[actionType].toLowerCase()} from the Device Compliance Review lane.`;
}

function userOptionLabel(user: AzureDirectoryObject): string {
  return user.display_name || user.principal_name || user.mail || user.id;
}

function userOptionSecondary(user: AzureDirectoryObject): string {
  return user.principal_name || user.mail || user.id;
}

function AssignmentPicker({
  title,
  confirmLabel,
  busy,
  selectedUser,
  onConfirm,
}: {
  title: string;
  confirmLabel: string;
  busy?: boolean;
  selectedUser: AzureDirectoryObject | null;
  onConfirm: (user: AzureDirectoryObject) => void;
}) {
  const [search, setSearch] = useState("");
  const [localSelection, setLocalSelection] = useState<AzureDirectoryObject | null>(selectedUser);
  const deferredSearch = useDeferredValue(search);

  useEffect(() => {
    setLocalSelection(selectedUser);
  }, [selectedUser]);

  const usersQuery = useQuery({
    queryKey: ["azure", "directory", "users", "device-compliance-picker", deferredSearch],
    queryFn: () => api.getAzureUsers(deferredSearch),
    enabled: deferredSearch.trim().length >= 2,
    staleTime: 30_000,
  });

  const options = usersQuery.data ?? [];

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-sm font-semibold text-slate-900">{title}</div>
      <input
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Search cached users by name, UPN, or mail..."
        className="mt-3 w-full rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
      />
      <div className="mt-2 text-xs text-slate-500">Enter at least 2 characters to search the cached Azure user directory.</div>

      {usersQuery.isError ? (
        <div className="mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Failed to search users: {usersQuery.error instanceof Error ? usersQuery.error.message : "Unknown error"}
        </div>
      ) : null}

      {localSelection ? (
        <div className="mt-3 rounded-xl bg-white px-4 py-3 text-sm text-slate-800 ring-1 ring-slate-200">
          Selected user: <span className="font-semibold">{userOptionLabel(localSelection)}</span>
          <div className="mt-1 text-xs text-slate-500">{userOptionSecondary(localSelection)}</div>
        </div>
      ) : null}

      {options.length > 0 ? (
        <div className="mt-3 max-h-56 space-y-2 overflow-y-auto">
          {options.slice(0, 8).map((user) => (
            <button
              key={user.id}
              type="button"
              onClick={() => setLocalSelection(user)}
              className={`flex w-full items-start justify-between rounded-xl px-4 py-3 text-left text-sm transition ${
                localSelection?.id === user.id ? "bg-emerald-50 text-emerald-900 ring-1 ring-emerald-200" : "bg-white text-slate-800 ring-1 ring-slate-200 hover:bg-slate-50"
              }`}
            >
              <span className="font-medium">{userOptionLabel(user)}</span>
              <span className="ml-3 text-xs text-slate-500">{userOptionSecondary(user)}</span>
            </button>
          ))}
        </div>
      ) : deferredSearch.trim().length >= 2 && !usersQuery.isLoading ? (
        <div className="mt-3 rounded-xl bg-white px-4 py-3 text-sm text-slate-500 ring-1 ring-slate-200">No cached users matched that search.</div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => {
            if (localSelection) onConfirm(localSelection);
          }}
          disabled={!localSelection || busy}
          className="rounded-xl bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {busy ? "Submitting..." : confirmLabel}
        </button>
      </div>
    </div>
  );
}

function DeviceCard({
  device,
  selected,
  busy,
  onToggle,
  onRunAction,
}: {
  device: SecurityDeviceComplianceDevice;
  selected: boolean;
  busy: boolean;
  onToggle: (deviceId: string, selected: boolean) => void;
  onRunAction: (
    actionType: SecurityDeviceActionType,
    device: SecurityDeviceComplianceDevice,
    params?: Record<string, unknown>,
  ) => void;
}) {
  const primaryUser = device.primary_users[0];
  const [showAssignmentPicker, setShowAssignmentPicker] = useState(false);
  const directActions = DIRECT_ACTION_ORDER.filter((action) => device.supported_actions.includes(action));

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
          <h4 className="text-sm font-semibold text-slate-900">Remediation actions</h4>
          <div className="mt-2 space-y-3">
            {device.recommended_fix_action ? (
              <button
                type="button"
                onClick={() => {
                  if (device.recommended_fix_requires_user_picker) {
                    setShowAssignmentPicker(true);
                    return;
                  }
                  const recommendedAction = device.recommended_fix_action;
                  if (recommendedAction) {
                    onRunAction(recommendedAction, device);
                  }
                }}
                disabled={busy}
                className="w-full rounded-xl bg-emerald-700 px-4 py-3 text-left text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                Recommended fix: {device.recommended_fix_label}
                {device.recommended_fix_reason ? <div className="mt-1 text-xs font-medium text-emerald-100">{device.recommended_fix_reason}</div> : null}
              </button>
            ) : null}

            <div className="flex flex-wrap gap-2">
              {directActions.map((action) => {
                const destructive = DESTRUCTIVE_ACTIONS.has(action);
                return (
                  <button
                    key={`${device.id}-${action}`}
                    type="button"
                    onClick={() => {
                      if (action === "device_reassign_primary_user") {
                        setShowAssignmentPicker((current) => !current);
                        return;
                      }
                      onRunAction(action, device);
                    }}
                    disabled={busy}
                    className={`rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500 ${
                      destructive ? "bg-rose-50 text-rose-700 hover:bg-rose-100" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                    }`}
                  >
                    {ACTION_LABELS[action]}
                  </button>
                );
              })}
            </div>

            {showAssignmentPicker ? (
              <AssignmentPicker
                title={`Assign primary user for ${device.device_name}`}
                confirmLabel={`Assign ${device.device_name}`}
                busy={busy}
                selectedUser={null}
                onConfirm={(user) => {
                  onRunAction("device_reassign_primary_user", device, {
                    primary_user_id: user.id,
                    primary_user_display_name: userOptionLabel(user),
                  });
                  setShowAssignmentPicker(false);
                }}
              />
            ) : null}

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

function SmartPlanDeviceRow({
  item,
  assignedUser,
  busy,
  onAssign,
}: {
  item: SecurityDeviceFixPlanDevice;
  assignedUser: AzureDirectoryObject | null;
  busy: boolean;
  onAssign: (deviceId: string, user: AzureDirectoryObject) => void;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">{item.device_name}</div>
          <div className="mt-1 text-xs text-slate-500">{item.action_reason}</div>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${azureSecurityToneClasses(riskTone(item.risk_level))}`}>
          {titleCase(item.risk_level)}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {item.finding_tags.map((tag) => (
          <span key={`${item.device_id}-${tag}`} className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-800">
            {titleCase(tag)}
          </span>
        ))}
      </div>
      <div className="mt-3">
        <AssignmentPicker
          title={`Select the primary user for ${item.device_name}`}
          confirmLabel="Use selected user"
          busy={busy}
          selectedUser={assignedUser}
          onConfirm={(user) => onAssign(item.device_id, user)}
        />
      </div>
    </div>
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
  const [bulkAssignmentUser, setBulkAssignmentUser] = useState<AzureDirectoryObject | null>(null);
  const [activeJobId, setActiveJobId] = useState("");
  const [activeBatchId, setActiveBatchId] = useState("");
  const [fixPlan, setFixPlan] = useState<SecurityDeviceFixPlanResponse | null>(null);
  const [fixPlanAssignments, setFixPlanAssignments] = useState<Record<string, AzureDirectoryObject>>({});
  const [fixPlanDestructiveConfirmed, setFixPlanDestructiveConfirmed] = useState(false);
  const deferredSearch = useDeferredValue(search);
  const selectedIdsKey = useMemo(() => selectedIds.join("|"), [selectedIds]);

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
      setActiveBatchId("");
      setSelectedIds([]);
      setBulkAssignmentUser(null);
      setDestructiveConfirmed(false);
      setFixPlan(null);
      setFixPlanAssignments({});
      setFixPlanDestructiveConfirmed(false);
      void queryClient.invalidateQueries({ queryKey: ["azure", "security", "device-compliance"] });
    },
  });

  const previewMutation = useMutation({
    mutationFn: (deviceIds: string[]) => api.previewAzureSecurityDeviceFixPlan({ device_ids: deviceIds }),
    onSuccess: (plan) => {
      setFixPlan(plan);
      setFixPlanAssignments({});
      setFixPlanDestructiveConfirmed(false);
      setActiveBatchId("");
    },
  });

  const executePlanMutation = useMutation({
    mutationFn: (body: SecurityDeviceFixPlanExecuteRequest) => api.executeAzureSecurityDeviceFixPlan(body),
    onSuccess: (batch) => {
      setActiveBatchId(batch.batch_id);
      setActiveJobId("");
      setSelectedIds([]);
      setFixPlan(null);
      setFixPlanAssignments({});
      setFixPlanDestructiveConfirmed(false);
      setBulkAssignmentUser(null);
      setDestructiveConfirmed(false);
      void queryClient.invalidateQueries({ queryKey: ["azure", "security", "device-compliance"] });
    },
  });

  const activeJobQuery = useQuery({
    queryKey: ["azure", "security", "device-compliance", "job", activeJobId],
    queryFn: () => api.getAzureSecurityDeviceActionJob(activeJobId),
    enabled: Boolean(activeJobId),
    refetchInterval: (current) => {
      const job = current.state.data;
      if (!job) return 2_000;
      return job.status === "completed" || job.status === "failed" ? false : 2_000;
    },
  });

  const resultsQuery = useQuery({
    queryKey: ["azure", "security", "device-compliance", "job-results", activeJobId],
    queryFn: () => api.getAzureSecurityDeviceActionJobResults(activeJobId),
    enabled: Boolean(activeJobId) && Boolean(activeJobQuery.data?.results_ready),
  });

  const activeBatchQuery = useQuery({
    queryKey: ["azure", "security", "device-compliance", "batch", activeBatchId],
    queryFn: () => api.getAzureSecurityDeviceActionBatch(activeBatchId),
    enabled: Boolean(activeBatchId),
    refetchInterval: (current) => {
      const batch = current.state.data as SecurityDeviceActionBatchStatus | undefined;
      if (!batch) return 2_000;
      return batch.status === "completed" || batch.status === "failed" ? false : 2_000;
    },
  });

  const activeBatchResultsQuery = useQuery({
    queryKey: ["azure", "security", "device-compliance", "batch-results", activeBatchId],
    queryFn: () => api.getAzureSecurityDeviceActionBatchResults(activeBatchId),
    enabled: Boolean(activeBatchId),
    refetchInterval: () => {
      const batch = activeBatchQuery.data;
      if (!batch) return 2_000;
      return batch.status === "completed" || batch.status === "failed" ? false : 2_000;
    },
  });

  useEffect(() => {
    if (activeJobQuery.data?.results_ready) {
      void queryClient.invalidateQueries({ queryKey: ["azure", "security", "device-compliance"] });
    }
  }, [activeJobQuery.data?.results_ready, queryClient]);

  useEffect(() => {
    if (activeBatchQuery.data?.results_ready) {
      void queryClient.invalidateQueries({ queryKey: ["azure", "security", "device-compliance"] });
    }
  }, [activeBatchQuery.data?.results_ready, queryClient]);

  useEffect(() => {
    setFixPlan(null);
    setFixPlanAssignments({});
    setFixPlanDestructiveConfirmed(false);
  }, [selectedIdsKey]);

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

  const fixPlanAssignmentsResolved = useMemo(() => {
    if (!fixPlan) return false;
    return fixPlan.devices_requiring_primary_user.every((item) => Boolean(fixPlanAssignments[item.device_id]));
  }, [fixPlan, fixPlanAssignments]);

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
    setBulkAssignmentUser(null);
    setFixPlan(null);
    setFixPlanAssignments({});
    setFixPlanDestructiveConfirmed(false);
  }

  function queueDirectAction(
    action: SecurityDeviceActionType,
    device: SecurityDeviceComplianceDevice,
    params: Record<string, unknown> = {},
  ) {
    if (DESTRUCTIVE_ACTIONS.has(action)) {
      const confirmed = window.confirm(`Confirm ${ACTION_LABELS[action].toLowerCase()} for ${device.device_name}?`);
      if (!confirmed) return;
    }
    jobMutation.mutate({
      action_type: action,
      device_ids: [device.id],
      reason: directActionReason(action, device),
      confirm_device_count: DESTRUCTIVE_ACTIONS.has(action) ? 1 : undefined,
      confirm_device_names: DESTRUCTIVE_ACTIONS.has(action) ? [device.device_name] : undefined,
      params,
    });
  }

  function submitExplicitBulkAction() {
    if (!selectedDevices.length) return;
    const params =
      actionType === "device_reassign_primary_user" && bulkAssignmentUser
        ? {
            primary_user_id: bulkAssignmentUser.id,
            primary_user_display_name: userOptionLabel(bulkAssignmentUser),
          }
        : undefined;
    jobMutation.mutate({
      action_type: actionType,
      device_ids: selectedDevices.map((device) => device.id),
      reason,
      confirm_device_count: destructiveAction && destructiveConfirmed ? selectedDevices.length : undefined,
      confirm_device_names: destructiveAction && destructiveConfirmed ? selectedNames : undefined,
      params,
    });
  }

  function executeSmartPlan() {
    if (!fixPlan) return;
    executePlanMutation.mutate({
      device_ids: fixPlan.device_ids,
      reason,
      assignment_map: Object.fromEntries(
        Object.entries(fixPlanAssignments)
          .filter(([, user]) => Boolean(user))
          .map(([deviceId, user]) => [deviceId, user.id]),
      ),
      confirm_device_count: fixPlan.requires_destructive_confirmation && fixPlanDestructiveConfirmed ? fixPlan.destructive_device_count : undefined,
      confirm_device_names: fixPlan.requires_destructive_confirmation && fixPlanDestructiveConfirmed ? fixPlan.destructive_device_names : undefined,
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
        description="Review tenant-wide Intune managed-device posture, fix common compliance findings, assign missing owners, and run queued remediation from one security lane."
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
                Keep explicit one-action bulk runs, or preview a smart remediation plan that groups selected devices by their recommended fixes.
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

          <div className="mt-4 grid gap-3 xl:grid-cols-[220px_1fr_220px_220px]">
            <select
              value={actionType}
              onChange={(event) => {
                setActionType(event.target.value as SecurityDeviceActionType);
                setDestructiveConfirmed(false);
                setBulkAssignmentUser(null);
              }}
              className="rounded-xl border border-slate-300 px-4 py-3 text-sm text-slate-700 outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
            >
              <option value="device_sync">Device sync</option>
              <option value="device_remote_lock">Remote lock</option>
              <option value="device_retire">Retire</option>
              <option value="device_wipe">Wipe</option>
              <option value="device_reassign_primary_user">Assign primary user</option>
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
              onClick={submitExplicitBulkAction}
              disabled={
                selectedDevices.length === 0 ||
                jobMutation.isPending ||
                executePlanMutation.isPending ||
                (destructiveAction && !destructiveConfirmed) ||
                (actionType === "device_reassign_primary_user" && !bulkAssignmentUser)
              }
              className="rounded-xl bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {jobMutation.isPending ? "Queueing..." : `Run ${ACTION_LABELS[actionType]}`}
            </button>
            <button
              type="button"
              onClick={() => previewMutation.mutate(selectedDevices.map((device) => device.id))}
              disabled={selectedDevices.length === 0 || previewMutation.isPending || jobMutation.isPending}
              className="rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-800 transition hover:bg-emerald-100 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400"
            >
              {previewMutation.isPending ? "Planning fixes..." : "Fix selected"}
            </button>
          </div>

          {actionType === "device_reassign_primary_user" ? (
            <div className="mt-4">
              <AssignmentPicker
                title="Select the primary user to assign across the selected devices"
                confirmLabel="Use selected user for bulk assignment"
                busy={jobMutation.isPending}
                selectedUser={bulkAssignmentUser}
                onConfirm={(user) => setBulkAssignmentUser(user)}
              />
            </div>
          ) : null}

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

          {previewMutation.isError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {previewMutation.error instanceof Error ? previewMutation.error.message : "Failed to build the remediation plan."}
            </div>
          ) : null}
        </section>
      ) : null}

      {fixPlan ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Smart fix preview</h2>
              <div className="mt-1 text-sm text-slate-500">
                The backend generated a deterministic remediation plan from the selected device findings. Review it before anything is queued.
              </div>
            </div>
            <div className="text-sm text-slate-500">{fixPlan.device_ids.length.toLocaleString()} device(s) in scope</div>
          </div>

          {fixPlan.warnings.length > 0 ? (
            <div className="mt-4 space-y-2">
              {fixPlan.warnings.map((warning) => (
                <div key={warning} className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                  {warning}
                </div>
              ))}
            </div>
          ) : null}

          {fixPlan.groups.length > 0 ? (
            <div className="mt-5 grid gap-3 xl:grid-cols-2">
              {fixPlan.groups.map((group) => (
                <div key={group.action_type} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-slate-900">{group.action_label}</div>
                      <div className="mt-1 text-xs text-slate-500">{group.device_count.toLocaleString()} device(s)</div>
                    </div>
                    {group.requires_confirmation ? (
                      <span className="rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700">Requires destructive confirmation</span>
                    ) : null}
                  </div>
                  <div className="mt-3 text-sm text-slate-700">{group.device_names.join(", ")}</div>
                </div>
              ))}
            </div>
          ) : null}

          {fixPlan.devices_requiring_primary_user.length > 0 ? (
            <div className="mt-5 space-y-3">
              <h3 className="text-base font-semibold text-slate-900">Devices that need a primary user selected</h3>
              {fixPlan.devices_requiring_primary_user.map((item) => (
                <SmartPlanDeviceRow
                  key={item.device_id}
                  item={item}
                  assignedUser={fixPlanAssignments[item.device_id] ?? null}
                  busy={executePlanMutation.isPending}
                  onAssign={(deviceId, user) =>
                    setFixPlanAssignments((current) => ({
                      ...current,
                      [deviceId]: user,
                    }))
                  }
                />
              ))}
            </div>
          ) : null}

          {fixPlan.skipped_devices.length > 0 ? (
            <div className="mt-5 space-y-2">
              <h3 className="text-base font-semibold text-slate-900">Skipped devices</h3>
              {fixPlan.skipped_devices.map((item) => (
                <div key={item.device_id} className="rounded-xl bg-slate-100 px-4 py-3 text-sm text-slate-700">
                  <span className="font-semibold">{item.device_name}</span>: {item.skip_reason}
                </div>
              ))}
            </div>
          ) : null}

          {fixPlan.requires_destructive_confirmation ? (
            <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 p-4">
              <div className="text-sm font-semibold text-rose-900">
                Confirm retire actions for {fixPlan.destructive_device_count.toLocaleString()} device(s)
              </div>
              <div className="mt-2 text-sm text-rose-900">{fixPlan.destructive_device_names.join(", ")}</div>
              <label className="mt-3 flex items-start gap-3 text-sm text-rose-900">
                <input
                  type="checkbox"
                  checked={fixPlanDestructiveConfirmed}
                  onChange={(event) => setFixPlanDestructiveConfirmed(event.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-rose-300 text-rose-700 focus:ring-rose-200"
                />
                <span>I confirm the destructive device count and names for this smart remediation plan.</span>
              </label>
            </div>
          ) : null}

          {executePlanMutation.isError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {executePlanMutation.error instanceof Error ? executePlanMutation.error.message : "Failed to execute the remediation plan."}
            </div>
          ) : null}

          <div className="mt-5 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={executeSmartPlan}
              disabled={
                executePlanMutation.isPending ||
                (fixPlan.devices_requiring_primary_user.length > 0 && !fixPlanAssignmentsResolved) ||
                (fixPlan.requires_destructive_confirmation && !fixPlanDestructiveConfirmed)
              }
              className="rounded-xl bg-emerald-700 px-4 py-3 text-sm font-semibold text-white transition hover:bg-emerald-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {executePlanMutation.isPending ? "Queueing remediation..." : "Execute fix plan"}
            </button>
            <button
              type="button"
              onClick={() => {
                setFixPlan(null);
                setFixPlanAssignments({});
                setFixPlanDestructiveConfirmed(false);
              }}
              className="rounded-xl border border-slate-300 px-4 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50"
            >
              Dismiss preview
            </button>
          </div>
        </section>
      ) : null}

      {activeBatchQuery.data ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Active fix batch</h2>
              <div className="mt-1 text-sm text-slate-500">
                {activeBatchQuery.data.progress_current.toLocaleString()} of {activeBatchQuery.data.progress_total.toLocaleString()} device action(s) processed
              </div>
            </div>
            <span
              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                activeBatchQuery.data.status === "failed"
                  ? "bg-rose-50 text-rose-700"
                  : activeBatchQuery.data.status === "completed"
                    ? "bg-emerald-50 text-emerald-700"
                    : "bg-amber-50 text-amber-700"
              }`}
            >
              {titleCase(activeBatchQuery.data.status)}
            </span>
          </div>
          <div className="mt-3 text-sm text-slate-700">{activeBatchQuery.data.progress_message}</div>
          {activeBatchQuery.data.error ? (
            <div className="mt-3 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-800">{activeBatchQuery.data.error}</div>
          ) : null}
          <div className="mt-4 grid gap-3 xl:grid-cols-2">
            {activeBatchQuery.data.child_jobs.map((job) => (
              <div key={job.child_job_id} className="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-700">
                <div className="font-semibold text-slate-900">{job.action_label}</div>
                <div className="mt-1">
                  {job.progress_current.toLocaleString()} of {job.progress_total.toLocaleString()} processed
                </div>
                <div className="mt-1 text-xs text-slate-500">{job.device_names.join(", ")}</div>
              </div>
            ))}
          </div>
          {activeBatchResultsQuery.data && activeBatchResultsQuery.data.length > 0 ? (
            <div className="mt-4 space-y-2">
              {activeBatchResultsQuery.data.map((result) => (
                <div
                  key={`${result.child_job_id}-${result.device_id}-${result.action_type}`}
                  className={`rounded-xl px-4 py-3 text-sm ${
                    result.success === false
                      ? "bg-rose-50 text-rose-900"
                      : result.success === true
                        ? "bg-emerald-50 text-emerald-900"
                        : "bg-slate-100 text-slate-700"
                  }`}
                >
                  <div className="font-semibold">
                    {result.device_name} • {result.action_label}
                  </div>
                  <div className="mt-1">
                    {result.success === false ? result.error || result.summary : result.summary || titleCase(result.status)}
                  </div>
                  {result.assignment_user_display_name ? (
                    <div className="mt-1 text-xs text-slate-500">Assigned user: {result.assignment_user_display_name}</div>
                  ) : null}
                </div>
              ))}
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
              busy={jobMutation.isPending || executePlanMutation.isPending}
              onToggle={toggleSelection}
              onRunAction={queueDirectAction}
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
